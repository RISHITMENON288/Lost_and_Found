"""Container Lambda, triggered by SQS after a report with a photo is created.

Flow: read photo from S3 -> CLIP embedding -> store on the item -> ask the matcher to (re)run.
If the photo is unusable we still enqueue matching (text/location/time) instead of failing the report.
"""
import json
import logging
import os
from array import array

import boto3

import features

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_BYTES = 6 * 1024 * 1024

_s3 = boto3.client("s3")
_sqs = boto3.client("sqs")
_table = boto3.resource("dynamodb").Table(os.environ["ITEMS_TABLE"])


def _process(item_id):
    item = _table.get_item(Key={"itemId": item_id}).get("Item")
    if item is None:
        logger.warning("item %s no longer exists", item_id)
        return
    key = item.get("imageKey")
    if key and key.startswith("uploads/"):
        try:
            body = _s3.get_object(Bucket=os.environ["BUCKET"], Key=key)["Body"].read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise features.UnreadableImage("image too large")
            blob = array("f", features.embed(body)).tobytes()
            _table.update_item(
                Key={"itemId": item_id},
                UpdateExpression="SET embedding = :e",
                ExpressionAttributeValues={":e": blob},
                ConditionExpression="attribute_exists(itemId)",
            )
        except features.UnreadableImage as e:
            logger.warning("unusable image for %s: %s (matching without it)", item_id, e)
    _sqs.send_message(QueueUrl=os.environ["MATCH_QUEUE_URL"], MessageBody=json.dumps({"itemId": item_id}))


def handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            _process(json.loads(record["body"])["itemId"])
        except Exception:
            logger.exception("extraction failed for message %s", record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
