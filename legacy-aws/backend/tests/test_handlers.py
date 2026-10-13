import json
import time
import unittest
from unittest import mock

from fake_store import FakeStore
from lf import api, pre_signup
import lf.match_worker as worker


def event(route, sub="alice", body=None, params=None):
    return {
        "routeKey": route,
        "pathParameters": params or {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": sub, "name": sub.title(), "email": sub + "@campus.edu", "phone_number": "+919876543210"}}}},
    }


class HandlerTest(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        patcher = mock.patch.object(api, "get_store", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, *a, **kw):
        res = api.lambda_handler(event(*a, **kw), None)
        return res["statusCode"], json.loads(res["body"])

    def test_create_and_list(self):
        now = int(time.time() * 1000)
        status, item = self.call("POST /items", body={
            "type": "LOST", "title": "Black bag", "category": "BAG", "description": "",
            "location": "Library", "occurredAt": now - 1000})
        self.assertEqual(201, status)
        status, data = self.call("GET /items")
        self.assertEqual(200, status)
        self.assertEqual([item["id"]], [i["id"] for i in data["items"]])

    def test_bad_json_and_unknown_route(self):
        res = api.lambda_handler({**event("POST /items"), "body": "{not json"}, None)
        self.assertEqual(400, res["statusCode"])
        self.assertEqual(404, self.call("GET /nope")[0])

    def test_oversized_body_rejected(self):
        res = api.lambda_handler({**event("POST /items"), "body": "x" * 20_000}, None)
        self.assertEqual(413, res["statusCode"])

    def test_missing_claims_is_401(self):
        res = api.lambda_handler({"routeKey": "GET /items", "requestContext": {"authorizer": {"jwt": {"claims": {}}}}}, None)
        self.assertEqual(401, res["statusCode"])

    def test_internal_errors_do_not_leak(self):
        with mock.patch.object(self.store, "query_feed", side_effect=RuntimeError("secret table name")):
            status, data = self.call("GET /items")
        self.assertEqual(500, status)
        self.assertNotIn("secret", json.dumps(data))

    def test_respond_requires_boolean(self):
        self.assertEqual(400, self.call("POST /matches/{id}/respond", params={"id": "x"}, body={"confirm": "yes"})[0])

    def test_contact_route_and_phone_claim(self):
        now = int(time.time() * 1000)
        base = {"category": "BAG", "description": "Black backpack Dell charger", "location": "Library",
                "title": "Black laptop bag", "occurredAt": now - 1000}
        self.call("POST /items", sub="alice", body={**base, "type": "LOST"})
        _, found = self.call("POST /items", sub="bob", body={**base, "type": "FOUND"})
        self.assertNotIn("reporterPhone", found)
        self.assertEqual("+919876543210", self.store.get_item(found["id"])["reporterPhone"])
        with mock.patch.object(worker, "get_store", return_value=self.store):
            worker.lambda_handler({"Records": [{"messageId": "1", "body": json.dumps({"itemId": found["id"]})}]}, None)
        match_id = self.call("GET /matches", sub="alice")[1]["matches"][0]["id"]
        self.assertEqual(403, self.call("GET /matches/{id}/contact", sub="alice", params={"id": match_id})[0])
        self.call("POST /matches/{id}/respond", sub="alice", params={"id": match_id}, body={"confirm": True})
        status, data = self.call("GET /matches/{id}/contact", sub="alice", params={"id": match_id})
        self.assertEqual((200, {"phone": "+919876543210"}), (status, data))
        self.assertEqual(404, self.call("GET /matches/{id}/contact", sub="bob", params={"id": match_id})[0])

    def test_worker_reports_partial_failures(self):
        with mock.patch.object(worker, "get_store", return_value=self.store):
            result = worker.lambda_handler({"Records": [
                {"messageId": "ok", "body": json.dumps({"itemId": "missing"})},
                {"messageId": "bad", "body": "not json"},
            ]}, None)
        self.assertEqual([{"itemIdentifier": "bad"}], result["batchItemFailures"])

    def test_pre_signup_domain_restriction(self):
        ev = {"request": {"userAttributes": {"email": "x@gmail.com"}}}
        with mock.patch.dict("os.environ", {"ALLOWED_EMAIL_DOMAIN": "campus.edu"}):
            with self.assertRaises(Exception):
                pre_signup.lambda_handler(ev, None)
            ok = {"request": {"userAttributes": {"email": "Me@Campus.edu"}}}
            self.assertEqual(ok, pre_signup.lambda_handler(ok, None))
        with mock.patch.dict("os.environ", {"ALLOWED_EMAIL_DOMAIN": ""}):
            self.assertEqual(ev, pre_signup.lambda_handler(ev, None))


if __name__ == "__main__":
    unittest.main()
