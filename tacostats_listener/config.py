import os

from distutils.util import strtobool

import boto3

from dotenv import load_dotenv

load_dotenv(verbose=True)

VERSION = 'v0.1.19'

# don't write to sqs
DRY_RUN = bool(strtobool(os.getenv("DRY_RUN", "False")))
print("DRY_RUN set to", DRY_RUN)

SQS_URL = os.getenv("SQS_URL")
print("SQS_URL set to", SQS_URL)

LOCKFILE_BUCKET = os.getenv("LOCKFILE_BUCKET")
print("LOCKFILE_BUCKET set to", LOCKFILE_BUCKET)

_WHITELIST_USERS = "inhumantsar,tacostats"
WHITELIST_ENABLED = bool(strtobool(os.getenv("WHITELIST_ENABLED", "True")))
WHITELIST = os.getenv("WHITELIST", _WHITELIST_USERS).split(',')
print("WHITELIST set to ", WHITELIST)

DEFAULT_HISTORY_DAYS = int(os.getenv("DEFAULT_HISTORY_DAYS", 7))

secrets = boto3.client("secretsmanager")
get_secret = lambda x: secrets.get_secret_value(SecretId=x)["SecretString"]

REDDIT = {
    "client_id": os.getenv("REDDIT_ID", get_secret("tacostats-reddit-client-id")),
    "client_secret": os.getenv("REDDIT_SECRET", get_secret("tacostats-reddit-secret")),
    "user_agent": os.getenv("REDDIT_UA"),
    "username": os.getenv("REDDIT_USER"),
    "password": os.getenv("REDDIT_PASS", get_secret("tacostats-reddit-password")),
}

TRIGGERS = ['!stats', '!monthlystats', '!weeklystats', '!dailystats', '!mystats', '!mymonthlystats', '!myweeklystats', '!mydailystats']

EXCLUDED_AUTHORS = [
    "jobautomator",
    "AutoModerator",
    "EmojifierBot",
    "groupbot",
    "ShiversifyBot"
]
