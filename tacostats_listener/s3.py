import json

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Union

import boto3
from botocore.exceptions import ClientError

from tacostats_listener import util
from tacostats_listener.config import LOCKFILE_BUCKET

LOCK_TAG_KEY = 'Locked'

class LockError(Exception):
    pass

class AlreadyLocked(Exception):
    pass


def unlock(key: str):
    """Remove lock tag from s3 object"""
    tags = {}

    # get existing tags
    try:
        tags = _read_tags(key)
    except ClientError as e:
        # no obj is not a big deal
        if e.response['Error']['Code'] != 'NoSuchKey':
            raise LockError(e)
    
    # toss the lock if it exists
    _ = tags.pop(LOCK_TAG_KEY, None)

    # write tags
    try:
        return _write_tags(key, tags)
    except ClientError as e:
        raise LockError(e)


def lock(key: str) -> Dict[str,str]:
    """Add lock tag to s3 object creating an empty one if necessary.

    Exceptions:
        Raises `AlreadyLocked` if the file is already locked.
        Raises `LockError` if unable to lock the obj.
    """
    _s3_client = boto3.client('s3')
    tags = {}

    # eventual consistency could make this an issue but with reddit rate limits it seems unlikely
    now = util.now()

    # fetch existing tags
    try:
        tags = _read_tags(key)
    except ClientError as e:
        # no obj is not a big deal
        if e.response['Error']['Code'] == 'NoSuchKey':
            _s3_client.put_object(Bucket=LOCKFILE_BUCKET, Body='{}', Key=f"{key}.json", Tagging=f"{LOCK_TAG_KEY}={now}")
            return {LOCK_TAG_KEY: f"{now}"}
        else:
            raise LockError(e)

    # if there's a lock which is <10mins old, throw AlreadyLocked
    if LOCK_TAG_KEY in tags.keys():
        if int(tags[LOCK_TAG_KEY]) > now - 600:
            raise AlreadyLocked()

    # write tags
    try:
        return _write_tags(key, {**tags, LOCK_TAG_KEY: now})
    except ClientError as e:
        raise LockError(e)


def _read_tags(key: str) -> Dict[str, str]:
    _s3_client = boto3.client('s3')
    response = _s3_client.get_object_tagging(
        Bucket=LOCKFILE_BUCKET,
        Key=f"{key}.json",
    )
    return _from_tag_set(response['TagSet'])

def _write_tags(key: str, tags: Dict) -> Dict[str, str]:
    _s3_client = boto3.client('s3')
    tag_set = _to_tag_set(tags)

    # boto freaks out if you try put_object_tagging with an empty dict
    try:
        if tag_set:
            _s3_client.put_object_tagging(
                Bucket=LOCKFILE_BUCKET,
                Key=f"{key}.json",
                Tagging={'TagSet': tag_set}
            )
        else:
            _s3_client.delete_object_tagging(
                Bucket=LOCKFILE_BUCKET,
                Key=f"{key}.json"
            )
    except ClientError as e:
        # no obj is not a big deal
        if e.response['Error']['Code'] != 'NoSuchKey':
            raise LockError(e)

    return _from_tag_set(tag_set)

def _to_tag_set(tags: Dict) -> List[Dict[str, str]]:
    return [{'Key': k, 'Value': str(v)} for k, v in (tags or {}).items()]

def _from_tag_set(tag_set: List[Dict[str,str]]) -> Dict[str, str]:
    return {i['Key']: i['Value'] for i in (tag_set or [])}

def write(**kwargs):
    """write data to s3.
    
    Args:
        prefix - s3 "path" to write to. must not include trailing slash.
        kwargs - key is s3 "filename" to write, value is json-serializable data.
    """
    for key, value in kwargs.items():
        boto3.client('s3').put_object(
            Body=str(json.dumps(value)), 
            Bucket=LOCKFILE_BUCKET, 
            Key=f"{key}.json"
        )

def read(key: str) -> Dict[str, Any]:
    """Read json data stored in bucket."""
    try:
        object = boto3.client('s3').get_object(Bucket=LOCKFILE_BUCKET, Key=f"{key}.json")
        json_str = object["Body"].read().decode()
    except boto3.client('s3').exceptions.NoSuchKey as e:
        raise KeyError(e)

    return json.loads(json_str)
