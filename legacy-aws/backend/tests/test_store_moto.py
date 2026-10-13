"""Runs the real Store (boto3) against moto's AWS emulator. Tables are created from template.yaml
so the code and the CloudFormation indexes cannot drift apart. Skipped if moto is not installed."""
import json
import os
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import boto3
    import yaml
    from moto import mock_aws
except ImportError:  # pragma: no cover
    mock_aws = None

from lf import matcher, service
from lf.service import ApiError, User

TEMPLATE = Path(__file__).resolve().parents[1] / "template.yaml"
ALICE = User("alice", "Alice", "a@campus.edu")
BOB = User("bob", "Bob", "b@campus.edu")


def load_template():
    class Loader(yaml.SafeLoader):
        pass

    def any_tag(loader, suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        return loader.construct_mapping(node)

    Loader.add_multi_constructor("!", any_tag)
    return yaml.load(TEMPLATE.read_text(), Loader=Loader)  # noqa: S506 - trusted local file, SafeLoader subclass


def table_args(resource, name):
    p = resource["Properties"]
    args = {
        "TableName": name,
        "AttributeDefinitions": p["AttributeDefinitions"],
        "KeySchema": p["KeySchema"],
        "BillingMode": p["BillingMode"],
        "GlobalSecondaryIndexes": p["GlobalSecondaryIndexes"],
    }
    return args


@unittest.skipIf(mock_aws is None, "moto not installed")
class StoreIntegrationTest(unittest.TestCase):
    def setUp(self):
        for k, v in {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1"}.items():
            os.environ[k] = v
        self.mock = mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)

        t = load_template()["Resources"]
        ddb = boto3.client("dynamodb")
        ddb.create_table(**table_args(t["ItemsTable"], "items"))
        ddb.create_table(**table_args(t["MatchesTable"], "matches"))
        boto3.client("s3").create_bucket(Bucket="bucket")
        sqs = boto3.client("sqs")
        self.match_q = sqs.create_queue(QueueName="match")["QueueUrl"]
        self.extract_q = sqs.create_queue(QueueName="extract")["QueueUrl"]

        os.environ.update(ITEMS_TABLE="items", MATCHES_TABLE="matches", BUCKET="bucket",
                          MATCH_QUEUE_URL=self.match_q, EXTRACT_QUEUE_URL="")
        from lf.store import Store
        self.store = Store()
        self.now = int(time.time() * 1000)

    def body(self, type_, title, desc, **extra):
        d = {"type": type_, "title": title, "description": desc, "category": "BAG",
             "location": "Library", "occurredAt": self.now - 1000}
        d.update(extra)
        return d

    def messages(self, url):
        return boto3.client("sqs").receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])

    def test_full_lifecycle(self):
        s = self.store
        lost = service.create_item(s, ALICE, self.body("LOST", "Black laptop bag", "Black backpack with Dell charger"))
        found = service.create_item(s, BOB, self.body("FOUND", "Black laptop bag", "Black backpack, Dell charger inside"))
        queued = [json.loads(m["Body"])["itemId"] for m in self.messages(self.match_q)]
        self.assertEqual({lost["id"], found["id"]}, set(queued))

        # worker: both messages processed, still only one match (idempotent)
        total = sum(service.process_item(s, i, s.load_model()) for i in queued)
        self.assertEqual(1, total)
        self.assertEqual(0, service.process_item(s, lost["id"], None))

        matches = service.list_matches(s, ALICE)
        self.assertEqual(["PENDING"], [m["state"] for m in matches])
        self.assertEqual(1, len(service.list_matches(s, BOB)))
        self.assertEqual("POTENTIAL_MATCH", s.get_item(lost["id"])["status"])

        feed_ids = {i["id"] for i in service.list_items(s, BOB)}
        self.assertEqual({lost["id"], found["id"]}, feed_ids)

        with self.assertRaises(ApiError) as ctx:
            service.respond_to_match(s, BOB, matches[0]["id"], True)
        self.assertEqual(403, ctx.exception.status)

        out = service.respond_to_match(s, ALICE, matches[0]["id"], True)
        self.assertEqual("CONFIRMED", out["state"])
        self.assertEqual("CLAIMED", s.get_item(found["id"])["status"])

        # claimed items leave the public feed but stay visible to both parties
        self.assertEqual({lost["id"], found["id"]}, {i["id"] for i in service.list_items(s, ALICE)})
        self.assertEqual([], service.list_items(s, User("eve", "Eve", "e@campus.edu")))

        service.mark_returned(s, BOB, found["id"])
        self.assertEqual("RETURNED", s.get_item(lost["id"])["status"])

    def test_reject_and_close_paths(self):
        s = self.store
        lost = service.create_item(s, ALICE, self.body("LOST", "Black laptop bag", "Black backpack"))
        found = service.create_item(s, BOB, self.body("FOUND", "Black laptop bag", "Black backpack"))
        service.process_item(s, found["id"], None)
        match = service.list_matches(s, ALICE)[0]
        service.respond_to_match(s, ALICE, match["id"], False)
        self.assertEqual("OPEN", s.get_item(lost["id"])["status"])
        self.assertEqual(0, service.process_item(s, lost["id"], None))  # rejected pairs are never resurrected
        closed = service.close_item(s, ALICE, lost["id"])
        self.assertEqual("CLOSED", closed["status"])
        self.assertEqual("CLOSED", s.get_item(lost["id"])["status"])

    def test_conditional_status_update(self):
        s = self.store
        item = service.create_item(s, ALICE, self.body("LOST", "Black bag", "Shoulder bag"))
        self.assertFalse(s.update_status(item["id"], "CLAIMED", expected=("POTENTIAL_MATCH",)))
        self.assertTrue(s.update_status(item["id"], "CLOSED", expected=("OPEN", "POTENTIAL_MATCH")))
        self.assertFalse(s.update_status("missing", "CLOSED"))

    def test_embedding_roundtrip_and_image_scoring(self):
        s = self.store
        vec = matcher.encode_embedding([1.0] + [0.0] * 511)
        lost = service.create_item(s, ALICE, self.body("LOST", "Black bag", "Shoulder bag"))
        s.set_embedding(lost["id"], vec)
        stored = s.get_item(lost["id"])
        self.assertIsInstance(stored["embedding"], bytes)
        self.assertEqual(matcher.decode_embedding(vec), matcher.decode_embedding(stored["embedding"]))

    def test_photo_labels_are_filtered_and_stored(self):
        s = self.store
        fake = {"Labels": [{"Name": "Backpack"}, {"Name": "Indoors"}, {"Name": "Bag"}, {"Name": "Person"}]}
        with mock.patch.object(s._rekognition, "detect_labels", return_value=fake) as call:
            labels = s.detect_labels("uploads/alice/x.jpg")
        self.assertEqual(["backpack", "bag"], labels)
        self.assertEqual({"S3Object": {"Bucket": "bucket", "Name": "uploads/alice/x.jpg"}}, call.call_args.kwargs["Image"])
        lost = service.create_item(s, ALICE, self.body("LOST", "Black bag", "Shoulder bag"))
        s.set_labels(lost["id"], labels)
        self.assertEqual(["backpack", "bag"], s.get_item(lost["id"])["imageLabels"])

    def test_upload_presign_and_image_exists(self):
        s = self.store
        up = service.create_upload(s, ALICE, {"contentType": "image/jpeg"})
        self.assertIn("key", up["fields"])
        self.assertEqual("image/jpeg", up["fields"]["Content-Type"])
        self.assertFalse(s.image_exists(up["key"]))
        boto3.client("s3").put_object(Bucket="bucket", Key=up["key"], Body=b"\xff\xd8\xff")
        self.assertTrue(s.image_exists(up["key"]))
        item = service.create_item(s, ALICE, self.body("LOST", "Black bag", "Shoulder bag", imageKey=up["key"]))
        self.assertIn(up["key"], item["imageUrl"])

    def test_extract_queue_routing(self):
        os.environ["EXTRACT_QUEUE_URL"] = self.extract_q
        self.store.enqueue("abc", has_image=True)
        self.store.enqueue("def", has_image=False)
        self.assertEqual(["abc"], [json.loads(m["Body"])["itemId"] for m in self.messages(self.extract_q)])
        self.assertEqual(["def"], [json.loads(m["Body"])["itemId"] for m in self.messages(self.match_q)])

    def test_model_loading(self):
        s = self.store
        self.assertIsNone(s.load_model())
        model = {"type": "logistic", "bias": 0.0, "threshold": 0.7,
                 "weights": {"text": 1, "location": 1, "time": 1, "image": 1, "has_image": 0}}
        boto3.client("s3").put_object(Bucket="bucket", Key="models/weights.json", Body=json.dumps(model).encode())
        s._model_loaded_at = 0  # expire the cache
        self.assertEqual(model, s.load_model())

    def test_query_older_uses_created_at_range(self):
        s = self.store
        old = service.create_item(s, ALICE, {**self.body("LOST", "Old bag", "Shoulder bag"),
                                              "occurredAt": self.now - 91 * 86_400_000}, now=self.now - 90 * 86_400_000)
        service.create_item(s, ALICE, self.body("LOST", "New bag", "Shoulder bag"))
        closed = service.expire_old(s, self.now, 60)
        self.assertEqual(1, closed)
        self.assertEqual("CLOSED", s.get_item(old["id"])["status"])


if __name__ == "__main__":
    unittest.main()
