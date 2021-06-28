import json
import re

from typing import Tuple, Union

import boto3

from praw import Reddit
from praw.reddit import Comment, Submission
from tacostats_listener.config import REDDIT, DEFAULT_HISTORY_DAYS, SQS_URL, VERSION

reddit_client = Reddit(**REDDIT)
sqs_client = boto3.client('sqs')

PING_REGEX = re.compile(r'\![\w]+stats')

def listen():
    """Listen to incoming comments and wait for ping command"""
    print(f"tactostats-listener {VERSION} started...")
    for comment in reddit_client.subreddit("neoliberal").stream.comments():
        if _is_dt(comment.submission) and (params := _parse_ping(comment)):
                print(f'found a ping: {comment.id}')
                sqs_client.send_message(QueueUrl=SQS_URL, MessageBody=json.dumps(params))

def _parse_ping(comment: Comment) -> Union[None, Tuple[str, str, int]]:
    """Looks for ping phrases and returns the appropriate parameters"""
    if (match := PING_REGEX.match(comment.body)):
        ping = match.string[1:]
        target_id, target_user = _get_targets(ping, comment)
        days = _get_history_days(ping)
        return (target_id, target_user, days)
        
def _get_history_days(ping: str) -> int:
    """if the ping contains a desired period, return it."""
    if ping.startswith('my'):
        ping = ping[2:]
    if ping == 'stats':
        return DEFAULT_HISTORY_DAYS
    if ping.startswith('daily'):
        return 1
    if ping.startswith('weekly'):
        return 7
    if ping.startswith('monthly'):
        return 30
    if ping.startswith('all'):
        return 1000
    raise ValueError('Invalid history prefix:', ping)

def _get_targets(ping: str, comment: Comment) -> Tuple[str, str]:
    if ping.startswith('my') and comment.author and comment.author.name:
        return (comment.id, comment.author.name)
    else:
        target_id = comment.parent.id[3:]
        return (target_id, reddit_client.comment(target_id).author.name)

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