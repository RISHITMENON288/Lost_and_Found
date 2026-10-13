"""Tests the extractor handler with a stubbed model (no torch needed). Run: python -m unittest extractor/test_app.py"""
import json
import os
import sys
import types
import unittest

try:
    import boto3
    from moto import mock_aws
except ImportError:  # pragma: no cover
    mock_aws = None


class Unreadable(Exception):
    pass


@unittest.skipIf(mock_aws is None, "moto not installed")
class ExtractorTest(unittest.TestCase):
    def setUp(self):
        os.environ.update(AWS_ACCESS_KEY_ID="test", AWS_SECRET_ACCESS_KEY="test", AWS_DEFAULT_REGION="us-east-1",
                          ITEMS_TABLE="items", BUCKET="bucket")
        self.mock = mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        boto3.client("dynamodb").create_table(
            TableName="items", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "itemId", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "itemId", "KeyType": "HASH"}])
        boto3.client("s3").create_bucket(Bucket="bucket")
        self.queue = boto3.client("sqs").create_queue(QueueName="match")["QueueUrl"]
        os.environ["MATCH_QUEUE_URL"] = self.queue

        fake = types.ModuleType("features")
        fake.UnreadableImage = Unreadable
        fake.embed = lambda data: [1.0] + [0.0] * 511
        sys.modules["features"] = fake
        sys.modules.pop("app", None)
        sys.path.insert(0, os.path.dirname(__file__))
        import app
        self.app = app
        self.fake = fake
        self.table = boto3.resource("dynamodb").Table("items")

    def event(self, item_id):
        return {"Records": [{"messageId": "m1", "body": json.dumps({"itemId": item_id})}]}

    def queued(self):
        msgs = boto3.client("sqs").receive_message(QueueUrl=self.queue, MaxNumberOfMessages=10).get("Messages", [])
        return [json.loads(m["Body"])["itemId"] for m in msgs]

    def test_stores_embedding_and_requeues_matching(self):
        key = "uploads/u1/123e4567-e89b-12d3-a456-426614174000.jpg"
        boto3.client("s3").put_object(Bucket="bucket", Key=key, Body=b"img")
        self.table.put_item(Item={"itemId": "i1", "imageKey": key})
        self.assertEqual([], self.app.handler(self.event("i1"), None)["batchItemFailures"])
        self.assertEqual(2048, len(bytes(self.table.get_item(Key={"itemId": "i1"})["Item"]["embedding"].value)))
        self.assertEqual(["i1"], self.queued())

    def test_unreadable_image_still_gets_matched(self):
        key = "uploads/u1/123e4567-e89b-12d3-a456-426614174000.jpg"
        boto3.client("s3").put_object(Bucket="bucket", Key=key, Body=b"junk")
        self.table.put_item(Item={"itemId": "i2", "imageKey": key})

        def boom(data):
            raise Unreadable("not an image")
        self.fake.embed = boom
        self.assertEqual([], self.app.handler(self.event("i2"), None)["batchItemFailures"])
        self.assertNotIn("embedding", self.table.get_item(Key={"itemId": "i2"})["Item"])
        self.assertEqual(["i2"], self.queued())

    def test_unexpected_error_is_retried(self):
        key = "uploads/u1/123e4567-e89b-12d3-a456-426614174000.jpg"
        self.table.put_item(Item={"itemId": "i3", "imageKey": key})  # object missing in S3 -> ClientError
        result = self.app.handler(self.event("i3"), None)
        self.assertEqual([{"itemIdentifier": "m1"}], result["batchItemFailures"])
        self.assertEqual([], self.queued())

    def test_missing_item_is_acknowledged(self):
        self.assertEqual([], self.app.handler(self.event("ghost"), None)["batchItemFailures"])


if __name__ == "__main__":
    unittest.main()
