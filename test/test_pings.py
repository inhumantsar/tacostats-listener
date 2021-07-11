import time
import random

from math import floor
from test.utils import create_bucket, create_obj
from typing import Union

import pytest

from moto import mock_s3
from praw import Reddit
from praw.reddit import Comment, Submission

from tacostats_listener import util
from tacostats_listener.listener import InvalidTargetError, PING_REGEX, RejectedPingError, _can_ping, _get_requested_days, _parse_ping, _update_history
from tacostats_listener.config import REDDIT, DEFAULT_HISTORY_DAYS, SQS_URL, VERSION

reddit_client = Reddit(**REDDIT)

# TODO: replace these with actual comments, esp ones that caused errors
loremipsum = [
    'Lorem ipsum dolor sit amet, consectetur adipiscing elit!',
    'Aenean eget !nibh varius, accumsan arcu id, malesuada lacus.',
    'Sed elementum ipsum eu sem !rutrum, mystats eget malesuada leo tempus.',
    'Nulla vehicula metus id nulla posuere dapibus.',
    'Integer volutpat neque in dolor pulvinar, quis tristique lacus malesuada!',
    'Nulla a odio sollicitudin, pharetra ligula id, consectetur turpis.',
    'Nullam id dui eu nulla porta faucibus et suscipit nisi.',
    'Sed iaculis turpis my sollicitudin, posuere turpis in, laoreet eros.',
    'Etiam rhoncus magna non aliquet maximus.',
    'Aliquam condimentum mauris vel augue weekly malesuada ullamcorper!',
    '!Integer nec velit aliquet, consequat metus vitae, condimentum lectus.',
    'Curabitur et felis tincidunt, malesuada felis sed, fringilla orci.',
    'Nunc ornare est aliquet, rhoncus ipsum quis, blandit purus.',
    'Fusce sed sem !my interdum lorem daily finibus tincidunt.',
    'Quisque nec magna congue, fringilla monthly sapien sed, auctor odio.',
    'Morbi dictum tortor et metus laoreet, stats lobortis venenatis felis tempor.',
    'Ut ac arcu nec diam ultricies faucibus pretium a orci.',
    'Vestibulum ut neque nec nisl lobortis placerat eu commodo urna.',
    'Sed et metus sit dailystats amet urna all sagittis porta in in ligula.',
    'Maecenas in nisi quis erat ornare molestie vel in lectus.',
    "\n\nSed et metus sit dailystats amet\n\nurna all sagittis porta in in ligula.\n\n",
    "Sed et metus sit dailystats amet\n\nurna all sagittis porta in in ligula.",
    "Maecenas in nisi quis erat ornare molestie vel in lectus.\n\n!Mauris sit amet leo vel dolor stats tincidunt fringilla.",
    "\n\nSed et metus sit dailystats amet\n\nurna all sagittis porta in in ligula.\n\n",
    "Maecenas in nisi quis erat ornare molestie vel in lectus.\n\n",
    "\n\n!Mauris sit amet leo vel dolor stats tincidunt fringilla.",
]


def _get_fake_ping_bodies(pings, count=20000):
    for _ in range(count):
        has_body = random.random() > 0.2
        lorem_count = round(random.paretovariate(4)) if has_body else 0
        ping_idx = round(random.uniform(0,lorem_count)) if has_body else 0

        sentences = [random.choice(loremipsum) for i in range(lorem_count)]
        sentences.insert(ping_idx, random.choice(pings))
        joiner = '' if random.random() <= 0.1 else ' '
        yield joiner.join(sentences)

def _generate_all_possible_pings():
    for span in ['', 'daily', 'weekly', 'monthly', 'all']:
        for my in ['', 'my']:
            for joiner in ['', ' ']:
                yield '!' + my + 'stats' + joiner + span

def test_ping_regex():
    pings = list(_generate_all_possible_pings())
    for body in _get_fake_ping_bodies(pings):
        assert (match := PING_REGEX.search(body))
        assert len(match.groups()) == 2
        assert _get_requested_days(match.groups()[1])
        assert '!'+' '.join([i for i in match.groups() if i]) in pings

def test_get_history_days():
    spans = [
        (None, DEFAULT_HISTORY_DAYS), 
        ('daily', 1), 
        ('weekly',7), 
        ('monthly', 30), 
        ('all', 1000)
    ]
    for span in spans:
        assert span[1] == _get_requested_days(span[0])
    with pytest.raises(InvalidTargetError) as e:
        _get_requested_days('moo')

def _timestamp_mins_ago(mins: Union[int, float] = 1.0):
    return util.now() - round(60*mins)

def test_can_ping():
    ineligible = [
        ({'banned': False}, True),
        ({'excluded': False}, True),
        ({'banned': None}, True),
        ({'excluded': None}, True),
        ({'banned': 1234567890}, False),
        ({'excluded': 1234567890}, False),
        ({'banned': 1234567890, 'excluded': 1234567890}, False),
        ({'banned': 1234567890, 'excluded': False}, False),
        ({'banned': 1234567890, 'excluded': None}, False),
        ({'banned': False, 'excluded': 1234567890}, False),
        ({'banned': False, 'excluded': False}, True),
        ({'banned': False, 'excluded': None}, True),
        ({'banned': None, 'excluded': 1234567890}, False),
        ({'banned': None, 'excluded': False}, True),
        ({'banned': None, 'excluded': None}, True),
    ]
    # can't post more than 1 every 2 mins
    ratelimited_2m = [
        # can_ping only cares about ping keys, values are irrelevant
        ({'pings': {_timestamp_mins_ago(1): None}}, False),
        ({'pings': {_timestamp_mins_ago(2): None}}, False),
        ({'pings': {_timestamp_mins_ago(i): None for i in range(3)}}, False),
        ({'pings': {_timestamp_mins_ago(2.1): None}}, True),
        ({'pings': {_timestamp_mins_ago(i): None for i in range(3,6)}}, True),
    ]
    # can't post more than 5 in an hour
    ratelimited_1h = [ 
        ({'pings': {_timestamp_mins_ago(i+2): None for i in range(5)}}, False),
        ({'pings': {_timestamp_mins_ago(i+56): None for i in range(5)}}, True),
        ({'pings': {_timestamp_mins_ago(i+60): None for i in range(5)}}, True),
    ]

    for history in ineligible:
        full_hist = {**history[0], 'username': 'tacostats'}
        if history[1]:
            assert _can_ping(full_hist)
        else:
            with pytest.raises(RejectedPingError):
                assert _can_ping(full_hist)

    for history in ratelimited_2m:
        full_hist = {**history[0], 'username': 'tacostats'}
        if history[1]:
            assert _can_ping(full_hist)
        else:
            with pytest.raises(RejectedPingError):
                assert _can_ping(full_hist)

    for history in ratelimited_1h:
        full_hist = {**history[0], 'username': 'tacostats'}
        if history[1]:
            assert _can_ping(full_hist)
        else:
            with pytest.raises(RejectedPingError):
                assert _can_ping(full_hist)


    # whitelist
    assert _can_ping({'username': 'tacostats'})
    with pytest.raises(RejectedPingError):
        assert _can_ping({'username': 'fakeuser'})


def test_update_history():
    # ban
    with mock_s3():
        create_bucket()
        create_obj(key = 'tacostats.json', tags="")
        fake_history = {'username': 'tacostats'}
        updated_history = _update_history(history=fake_history, ban=True)
        assert updated_history['banned']
        assert isinstance(updated_history['banned'], int)
        assert updated_history['banned'] > util.now() - 10
        
    # opt-out
    with mock_s3():
        create_bucket()
        create_obj(key = 'tacostats.json', tags="")
        fake_history = {'username': 'tacostats'}
        updated_history = _update_history(history=fake_history, optout=True)
        assert updated_history['excluded']
        assert isinstance(updated_history['excluded'], int)
        assert updated_history['excluded'] > util.now() - 10

    # add ping
    with mock_s3():
        create_bucket()
        create_obj(key = 'tacostats.json', tags="")
        fake_history = {'username': 'tacostats'}
        # history updater shouldn't care about what is in params.
        updated_history = _update_history(history=fake_history, params={'fakekey': 'fakeval'})
        assert updated_history['pings']
        assert isinstance(updated_history['pings'], dict)
        keys = list(updated_history['pings'].keys())
        assert keys[0] > util.now() - 10 
        
        # wait one second, add another
        time.sleep(1)
        updated_history = _update_history(history=updated_history, params={'fakekey': 'fakeval'})
        assert updated_history['pings']
        assert isinstance(updated_history['pings'], dict)
        keys = list(updated_history['pings'].keys())
        assert len(keys) == 2
        assert keys[0] > util.now() - 10 
        assert keys[1] > util.now() - 10 

    # prune ping history @ 100
    with mock_s3():
        create_bucket()
        create_obj(key = 'tacostats.json', tags="")
        now = util.now()
        # create a fake history with 100 items, starting with 10s ago
        ping_history = {now - i * 10: {'fakekey': 'fakeval'} for i in range(1, 101)}
        fake_history = {'username': 'tacostats', 'pings': ping_history}

        # add a 101st entry
        updated_history = _update_history(history=fake_history, params={'fakekey': 'fakeval'})
        assert updated_history['pings']
        assert isinstance(updated_history['pings'], dict)
        keys = list(updated_history['pings'].keys())
        assert len(keys) == 100
        # all but one entry should be fresher than 10s ago
        assert sorted(keys, reverse=True)[0] > util.now() - 10 
