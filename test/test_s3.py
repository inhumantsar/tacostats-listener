from typing import Dict, Union
import boto3
from botocore.exceptions import ClientError
import pytest

from moto import mock_s3

from tacostats_listener import util
from tacostats_listener.s3 import AlreadyLocked, LOCK_TAG_KEY, LockError, _to_tag_set, _from_tag_set, lock, unlock
from test.utils import create_bucket, create_obj


def test_to_tag_set():
    assert _to_tag_set({'tagkey': 'tagvalue'}) == [{'Key': 'tagkey', 'Value': 'tagvalue'}]
    assert _to_tag_set({}) == []
    assert _to_tag_set(None) == [] # type: ignore
    assert _to_tag_set({'tagkey': 'tagvalue', 'key2': 'v2'}) == [{'Key': 'tagkey', 'Value': 'tagvalue'}, {'Key': 'key2', 'Value': 'v2'}]

def test_from_tag_set():
    assert {'tagkey': 'tagvalue'} == _from_tag_set([{'Key': 'tagkey', 'Value': 'tagvalue'}])
    assert {} == _from_tag_set([])
    assert {} == _from_tag_set(None) # type: ignore
    assert {'tagkey': 'tagvalue', 'key2': 'v2'} == _from_tag_set([{'Key': 'tagkey', 'Value': 'tagvalue'}, {'Key': 'key2', 'Value': 'v2'}])

def test_unlock():
    # no bucket (to force an unhandled clienterror which leads to a LockError)
    with mock_s3():
        with pytest.raises(LockError) as e:
            lock('fakeuser')
    
    # obj does not exist
    with mock_s3():
        create_bucket()
        result = lock('fakeuser')
        assert LOCK_TAG_KEY in result.keys() and int(result[LOCK_TAG_KEY]) > util.now() - 10

    # obj exists, no tags
    with mock_s3():
        create_bucket()
        create_obj(key = 'fakeuser.json', tags="")
        result = unlock('fakeuser')
        assert LOCK_TAG_KEY not in result.keys()

    # obj exists, has tags, no lock
    with mock_s3():
        create_bucket()
        create_obj(key = 'fakeuser.json', tags="sometag=othertag")
        result = unlock('fakeuser')
        assert LOCK_TAG_KEY not in result.keys()
        assert 'sometag' in result.keys() and result['sometag'] == 'othertag'

    # obj exists, has tags and lock
    with mock_s3():
        create_bucket()
        create_obj(key = 'fakeuser.json', tags=f"sometag=othertag&{LOCK_TAG_KEY}=1234567890")
        result = unlock('fakeuser')
        assert LOCK_TAG_KEY not in result.keys()
        assert 'sometag' in result.keys() and result['sometag'] == 'othertag'


def test_lock():
    # obj exists, no tags
    with mock_s3():
        create_bucket()
        create_obj(key = 'fakeuser.json', tags="")
        result = lock('fakeuser')
        assert LOCK_TAG_KEY in result.keys() and int(result[LOCK_TAG_KEY]) > util.now() - 10

    # obj exists, has tags
    with mock_s3():
        create_bucket()
        create_obj(key = 'fakeuser.json', tags="sometag=othertag")
        result = lock('fakeuser')
        assert LOCK_TAG_KEY in result.keys() and int(result[LOCK_TAG_KEY]) > util.now() - 10
        assert 'sometag' in result.keys() and result['sometag'] == 'othertag'

    # obj does not exist
    with mock_s3():
        create_bucket()
        result = lock('fakeuser')
        assert LOCK_TAG_KEY in result.keys() and int(result[LOCK_TAG_KEY]) > util.now() - 10

    # obj is already locked
    with mock_s3():
        create_bucket()
        create_obj(key = 'fakeuser.json', tags=f"Locked={util.now()-5}")
        with pytest.raises(AlreadyLocked) as e:
            lock('fakeuser')

    # no bucket (to force an unhandled clienterror which leads to a LockError)
    with mock_s3():
        with pytest.raises(LockError) as e:
            lock('fakeuser')