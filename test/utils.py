import boto3

from tacostats_listener.config import LOCKFILE_BUCKET

# Moto automocks boto calls, these funcs help manage mock objects
def create_bucket(): 
    boto3.resource('s3', region_name="us-east-1").create_bucket(Bucket=LOCKFILE_BUCKET)

def create_obj(key: str, tags: str): 
    boto3.client('s3', region_name="us-east-1").put_object(Bucket=LOCKFILE_BUCKET, Key=key, Tagging=tags)
