from datetime import datetime, timezone
import json
import re
import logging
import logging.config

from typing import Any, Dict, Tuple, Union

import boto3
from botocore import exceptions

from praw import Reddit
from praw.reddit import Comment, Submission
from tacostats_listener.config import EXCLUDED_AUTHORS, REDDIT, DEFAULT_HISTORY_DAYS, SQS_URL, VERSION, WHITELIST, WHITELIST_ENABLED
from tacostats_listener import s3, util

reddit_client = Reddit(**REDDIT)
sqs_client = boto3.client('sqs')

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
logging.getLogger("praw").setLevel(logging.WARNING)
logging.getLogger("prawcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)


PING_REGEX = re.compile(r'\!((?:my)?stats)\s?(daily|weekly|monthly|all)?')

class InvalidTargetError(Exception):
    """Raised when attempting to gather stats against an invalid target."""
    pass

class RejectedPingError(Exception):
    """Raised when a ping is rejected, eg: because the requester is spamming"""
    pass

def listen():
    """Listen to incoming comments and wait for ping command"""
    log.info(f"tacostats-listener {VERSION} started...")
    for comment in reddit_client.subreddit("neoliberal").stream.comments(skip_existing=True):
        # skip invalid comments
        if not _is_dt(comment.submission) or not comment.author:
            continue

        # skip comments from excluded authors
        if comment.author.name in EXCLUDED_AUTHORS:
            continue

        author = comment.author.name
        body = comment.body

        # admin commands
        if author == 'inhumantsar':
            if '!ban' in body:
                _ban(comment)
                continue

        # optouts don't require locking
        if '!statsoptout' in body:
            _optout(author)
            continue
        
        _handle_ping(comment)

def _handle_ping(comment):
    author = comment.author.name
    if (params := _parse_ping(comment)):
        log.info(f'found a ping: {params}')
        s3.lock(author)
        try:
            history = _get_history(author)
            if _can_ping(history):
                log.info(f'posting to queue: {params}')
                sqs_client.send_message(QueueUrl=SQS_URL, MessageBody=json.dumps(params))
            _update_history(history, params)
        except Exception as e:
            if not isinstance(e, InvalidTargetError) and not isinstance(e, RejectedPingError):
                log.exception(e)
            log.info(f"sending error dm for error: {e}")
            _send_dm(author, str(e), subject="tacostats ping error")
        finally:
            s3.unlock(author)

def _send_dm(username: str, message: str,  subject: str = "Your latest tacostats ping."):
    """Sends a private message to a Redditor."""
    reddit_client.redditor(username).message(subject, message)

def _ban(comment: Comment):
    _, username = _get_requested_targets("ban", comment)
    reason = comment.body.replace('!ban', '')
    _update_history(_get_history(username), ban=True)
    msg = f"""You have been banned from using the tacostats pings.

    Reason: {reason}
    
    You will not be able to request stats for yourself or others.

    Other redditors will be able to request stats on you and your comments will still be collected for the daily leaderboard.
    """
    _send_dm(username, msg, "Banned by tacostats")
    log.info(f"{username} has been banned.")

def _optout(username: str):
    msg = """"You have successfully opted-out from tacostats pings. 
    
    Other users will not be able to request your personal stats, and I will ignore all pings from your account.
    
    Your DT comments will still be collected as a part of the aggregate daily stats collection and your username will be included in the leaderboards if you qualify.
    """
    _update_history(_get_history(username), optout=True)
    _send_dm(username, msg, "tacostats opt-out")
    log.info(f"{username} has opted out.")

def _get_history(username: str) -> Dict[str, Any]:
    try:
        history = s3.read(username)
        # treat blank dicts like not found errors, this can happen if a lock is created before the history
        if not history:
            raise KeyError()
        return history
    except KeyError:
        return {'username': username}

def _update_history(history: Dict[str, Any], params: Dict[str, Any] = None, ban: bool = False, optout: bool = False) -> Dict[str, Any]:
    """Updates user history with new info"""
    log.info(f"updating history for {history['username']}...")
    if ban:
        history['banned'] = util.now()

    if optout:
        history['excluded'] = util.now()
    
    if params:
        pings = history.get('pings', {})
        pings[util.now()] = params

        # keep only last 100
        sorted_keys = sorted([int(i) for i in pings.keys()], reverse=True)
        for key in sorted_keys[100:]:
            pings.pop(key)
    
        history['pings'] = pings
    
    update = {history['username']: history}
    s3.write(**update)
    log.info(f"history updated.")
    return history


def _can_ping(history: Dict[str, Any]) -> bool:
    """Check for bans and throttles. Raises RejectedPingError."""
    if WHITELIST_ENABLED and history['username'] not in WHITELIST:
        raise RejectedPingError("""The pinger is in test mode at the moment and you are not an authorized tester.
        
        If you would like to be added to the list of testers, reply to this message and ask nicely.
        """)

    if history.get('banned'):
        raise RejectedPingError(f"{history['username']} is on the ban list. Repeat pings will be reported to Reddit admins.")
    
    if history.get('excluded'):
        raise RejectedPingError(f"{history['username']} is on the opt-out list.")

    pings = history.get('pings', {})
    sorted_keys = sorted([int(i) for i in pings.keys()], reverse=True)

    # no history found, user can ping.
    if len(sorted_keys) == 0:
        return True

    # no more than 1 in the last two minutes
    curr_time = util.now()
    last_time = sorted_keys[0]
    if curr_time - last_time <= 120:
        raise RejectedPingError(f"Your last ping was only {curr_time - last_time}s ago. Please try again in a few minutes.")

    # no more than 3 in an hour
    hour_ago = util.now() - 3600
    posts_in_last_hour = len([p for p in sorted_keys if p > hour_ago])
    if posts_in_last_hour >= 5:
        raise RejectedPingError(f"Found {posts_in_last_hour} pings in the last hour. Please try again later.")

    return True


def _parse_ping(comment: Comment) -> Union[None, Dict[str, Union[str, int]]]:
    """Looks for ping phrases and returns the appropriate parameters"""
    if (match := PING_REGEX.search(comment.body)):
        ping, span = match.groups()
        target_id, target_user = _get_requested_targets(ping, comment)
        days = _get_requested_days(span)
        return {'comment_id': target_id, 'username': target_user, 'days': days, 'requester': comment.author.name, 'requester_comment_id': comment.id}
        

def _get_requested_days(span: Union[str, None]) -> int:
    """if the ping contains a desired period, return it."""
    if not span:
        return DEFAULT_HISTORY_DAYS
    if 'daily' == span:
        return 1
    if 'weekly' == span:
        return 7
    if 'monthly' == span:
        return 30
    if 'all' == span:
        return 1000
    raise InvalidTargetError('Ping rejected. Unable to get a valid length of time from this request: ', span)

def _get_requested_targets(ping: str, comment: Comment) -> Tuple[str, str]:
    """Determines whether requester meant to target self or the parent comment.
    
    Returns (comment_id, comment_author)
    """
    if ping.startswith('my') and comment.author and comment.author.name:
        return (comment.id, comment.author.name)
    else:
        parent = comment.parent()
        if parent.author.name in EXCLUDED_AUTHORS:
            raise InvalidTargetError(f'Ping rejected. {parent.author.name} is an excluded author.')
        if _get_history(parent.author.name).get('excluded', None):
            raise InvalidTargetError(f'Ping rejected. {parent.author.name} you attempted to get stats for has opted out.')
        if isinstance(parent, Submission):
            raise InvalidTargetError('Ping rejected. Attempted to request stats against the DT.')
        return (parent.id, parent.author.name)

def _is_dt(dt: Submission) -> bool:
    """Runs through a couple tests to be sure it's a DT (or Thunderdome?)"""
    return all(
        [
            dt.title == "Discussion Thread",
            dt.author.name == "jobautomator",  # add mod list?
        ]
    )

if __name__ == "__main__":
    listen()