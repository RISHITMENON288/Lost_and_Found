"""Emails through Amazon SES. A failed email must never break matching or the API."""
import logging

from . import config

logger = logging.getLogger()
_client = None


def send(to, subject, body):
    sender = config.sender_email()
    if not sender or not to:
        return False
    global _client
    try:
        if _client is None:
            import boto3  # lazy: unit tests need no AWS libraries
            _client = boto3.client("ses")
        _client.send_email(
            Source=sender,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": " ".join(subject.split()), "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )
        return True
    except Exception as e:  # SES sandbox rejects unverified recipients; log the type only, not the address
        logger.warning("Email not sent: %s", type(e).__name__)
        return False
