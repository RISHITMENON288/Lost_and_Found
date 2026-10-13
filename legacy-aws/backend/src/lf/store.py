"""All AWS access (DynamoDB, S3, SQS) lives here so everything else stays testable."""
import json
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config
from botocore.exceptions import ClientError

from . import config
from . import constants as C

MODEL_KEY = "models/weights.json"
MODEL_TTL_SECONDS = 300


def _to_ddb(value):
    if isinstance(value, float):
        return Decimal(str(round(value, 6)))
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_to_ddb(v) for v in value]
    return value


def _to_native(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _to_native(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_native(v) for v in value]
    if hasattr(value, "value") and type(value).__name__ == "Binary":
        return bytes(value.value)
    return value


def _is_conditional_failure(error):
    return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


class Store:
    def __init__(self):
        ddb = boto3.resource("dynamodb")
        self._items = ddb.Table(config.items_table())
        self._matches = ddb.Table(config.matches_table())
        self._ddb = ddb
        self._s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
        self._sqs = boto3.client("sqs")
        self._rekognition = boto3.client("rekognition")
        self._model = None
        self._model_loaded_at = 0.0

    # ----- generic query helper -----
    @staticmethod
    def _query(table, max_items=300, **kwargs):
        results = []
        while True:
            resp = table.query(**kwargs)
            results.extend(_to_native(i) for i in resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last or len(results) >= max_items:
                break
            kwargs["ExclusiveStartKey"] = last
        return results[:max_items]

    # ----- items -----
    def put_item(self, item):
        self._items.put_item(Item=_to_ddb(item), ConditionExpression="attribute_not_exists(itemId)")

    def get_item(self, item_id):
        resp = self._items.get_item(Key={"itemId": item_id})
        return _to_native(resp["Item"]) if "Item" in resp else None

    def batch_get_items(self, ids):
        ids = list(ids)
        found = []
        for start in range(0, len(ids), 100):
            request = {self._items.name: {"Keys": [{"itemId": i} for i in ids[start:start + 100]]}}
            while request:
                resp = self._ddb.batch_get_item(RequestItems=request)
                found.extend(_to_native(i) for i in resp["Responses"].get(self._items.name, []))
                request = resp.get("UnprocessedKeys") or None
        return found

    def query_feed(self, item_type, limit=100):
        return self._query(
            self._items, max_items=limit, IndexName="ByType",
            KeyConditionExpression=Key("type").eq(item_type),
            FilterExpression=Attr("status").is_in(list(C.OPEN_STATUSES)),
            ScanIndexForward=False,
        )

    def query_by_reporter(self, sub, limit=200):
        return self._query(
            self._items, max_items=limit, IndexName="ByReporter",
            KeyConditionExpression=Key("reporterId").eq(sub), ScanIndexForward=False,
        )

    def query_candidates(self, category, item_type, limit=300):
        return self._query(
            self._items, max_items=limit, IndexName="ByCategory",
            KeyConditionExpression=Key("category").eq(category),
            FilterExpression=Attr("type").eq(item_type) & Attr("status").is_in(list(C.OPEN_STATUSES)),
            ScanIndexForward=False,
        )

    def query_older(self, item_type, cutoff_ms, limit=500):
        return self._query(
            self._items, max_items=limit, IndexName="ByType",
            KeyConditionExpression=Key("type").eq(item_type) & Key("createdAt").lt(cutoff_ms),
            FilterExpression=Attr("status").is_in(list(C.OPEN_STATUSES)),
        )

    def update_status(self, item_id, new_status, expected=None):
        kwargs = {
            "Key": {"itemId": item_id},
            "UpdateExpression": "SET #s = :new",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":new": new_status},
            "ConditionExpression": "attribute_exists(itemId)",
        }
        if expected:
            names = []
            for n, status in enumerate(expected):
                kwargs["ExpressionAttributeValues"][f":e{n}"] = status
                names.append(f":e{n}")
            kwargs["ConditionExpression"] = "#s IN ({})".format(", ".join(names))
        try:
            self._items.update_item(**kwargs)
            return True
        except ClientError as e:
            if _is_conditional_failure(e):
                return False
            raise

    def set_embedding(self, item_id, embedding):
        self._items.update_item(
            Key={"itemId": item_id},
            UpdateExpression="SET embedding = :e",
            ExpressionAttributeValues={":e": embedding},
            ConditionExpression="attribute_exists(itemId)",
        )

    def set_labels(self, item_id, labels):
        self._items.update_item(
            Key={"itemId": item_id},
            UpdateExpression="SET imageLabels = :l",
            ExpressionAttributeValues={":l": labels},
            ConditionExpression="attribute_exists(itemId)",
        )

    def detect_labels(self, key):
        """What Amazon Rekognition sees in the photo: lower-case object names, most confident first."""
        resp = self._rekognition.detect_labels(
            Image={"S3Object": {"Bucket": config.bucket(), "Name": key}},
            MaxLabels=C.MAX_PHOTO_LABELS,
            MinConfidence=C.MIN_LABEL_CONFIDENCE,
        )
        names = [label["Name"].lower() for label in resp.get("Labels", [])]
        return [n for n in names if n not in C.IGNORED_LABELS]

    # ----- matches -----
    def put_match(self, match):
        try:
            self._matches.put_item(Item=_to_ddb(match), ConditionExpression="attribute_not_exists(matchId)")
            return True
        except ClientError as e:
            if _is_conditional_failure(e):
                return False
            raise

    def get_match(self, match_id):
        resp = self._matches.get_item(Key={"matchId": match_id})
        return _to_native(resp["Item"]) if "Item" in resp else None

    def query_matches_for_user(self, sub, limit=200):
        merged = {}
        for index, attr in (("ByLostReporter", "lostReporterId"), ("ByFoundReporter", "foundReporterId")):
            for m in self._query(self._matches, max_items=limit, IndexName=index,
                                 KeyConditionExpression=Key(attr).eq(sub), ScanIndexForward=False):
                merged[m["matchId"]] = m
        return list(merged.values())

    def query_matches_for_item(self, item_id):
        merged = {}
        for index, attr in (("ByLostItem", "lostItemId"), ("ByFoundItem", "foundItemId")):
            for m in self._query(self._matches, max_items=200, IndexName=index,
                                 KeyConditionExpression=Key(attr).eq(item_id)):
                merged[m["matchId"]] = m
        return list(merged.values())

    def update_match_state(self, match_id, new_state, expected_state):
        try:
            self._matches.update_item(
                Key={"matchId": match_id},
                UpdateExpression="SET #s = :new",
                ConditionExpression="#s = :old",
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues={":new": new_state, ":old": expected_state},
            )
            return True
        except ClientError as e:
            if _is_conditional_failure(e):
                return False
            raise

    # ----- S3 -----
    def image_url(self, key):
        return self._s3.generate_presigned_url(
            "get_object", Params={"Bucket": config.bucket(), "Key": key}, ExpiresIn=3600
        )

    def image_exists(self, key):
        try:
            self._s3.head_object(Bucket=config.bucket(), Key=key)
            return True
        except ClientError:
            return False

    def create_upload(self, key):
        post = self._s3.generate_presigned_post(
            Bucket=config.bucket(),
            Key=key,
            Fields={"Content-Type": "image/jpeg"},
            Conditions=[
                {"Content-Type": "image/jpeg"},
                ["content-length-range", 1, C.MAX_IMAGE_BYTES],
            ],
            ExpiresIn=300,
        )
        return {"url": post["url"], "fields": post["fields"]}

    def load_model(self):
        """Optional trained scorer (JSON). Cached; missing file means 'use defaults'."""
        if time.time() - self._model_loaded_at < MODEL_TTL_SECONDS:
            return self._model
        try:
            body = self._s3.get_object(Bucket=config.bucket(), Key=MODEL_KEY)["Body"].read(64 * 1024)
            self._model = json.loads(body)
        except (ClientError, ValueError):
            self._model = None
        self._model_loaded_at = time.time()
        return self._model

    # ----- SQS -----
    def enqueue(self, item_id, has_image):
        extract_url = config.extract_queue_url()
        url = extract_url if (has_image and extract_url) else config.match_queue_url()
        self._sqs.send_message(QueueUrl=url, MessageBody=json.dumps({"itemId": item_id}))

    def enqueue_match(self, item_id):
        self._sqs.send_message(QueueUrl=config.match_queue_url(), MessageBody=json.dumps({"itemId": item_id}))
