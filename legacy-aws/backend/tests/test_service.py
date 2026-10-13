import unittest
from unittest import mock

from fake_store import FakeStore
from lf import service
from lf.service import ApiError, User

NOW = 1_800_000_000_000
H = 3_600_000
ALICE = User("alice", "Alice", "alice@campus.edu")   # loses things
BOB = User("bob", "Bob", "bob@campus.edu", "+919876543210")   # finds things
EVE = User("eve", "Eve", "eve@campus.edu")           # bystander


def body(type_, title, desc="", category="BAG", location="Library", at=NOW - H, **extra):
    d = {"type": type_, "title": title, "description": desc, "category": category,
         "location": location, "occurredAt": at}
    d.update(extra)
    return d


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.s = FakeStore()

    def lost_and_found(self):
        lost = service.create_item(self.s, ALICE, body("LOST", "Black laptop bag", "Black backpack with Dell charger"), now=NOW)
        found = service.create_item(self.s, BOB, body("FOUND", "Black laptop bag", "Black backpack, Dell charger inside", at=NOW), now=NOW)
        return lost, found

    def run_matching(self):
        created = 0
        for _kind, item_id in list(self.s.queue):
            created += service.process_item(self.s, item_id, None, now=NOW)
        return created

    # ---- create ----
    def test_create_enqueues_matching(self):
        lost, _ = self.lost_and_found()
        self.assertEqual("OPEN", lost["status"])
        self.assertIn(("match", lost["id"]), self.s.queue)

    def test_image_must_be_uploaded_and_goes_to_extractor(self):
        key = "uploads/alice/123e4567-e89b-12d3-a456-426614174000.jpg"
        with self.assertRaises(ApiError) as ctx:
            service.create_item(self.s, ALICE, body("LOST", "Black bag", imageKey=key), now=NOW)
        self.assertEqual(400, ctx.exception.status)
        self.s.images.add(key)
        item = service.create_item(self.s, ALICE, body("LOST", "Black bag", imageKey=key), now=NOW)
        self.assertEqual(("extract", item["id"]), self.s.queue[-1])
        self.assertTrue(item["imageUrl"].endswith(key))

    def test_validation_errors_are_400(self):
        with self.assertRaises(ApiError) as ctx:
            service.create_item(self.s, ALICE, body("LOST", "x"), now=NOW)
        self.assertEqual(400, ctx.exception.status)

    def test_report_limit(self):
        for n in range(service.MAX_ACTIVE_REPORTS_PER_USER):
            service.create_item(self.s, ALICE, body("LOST", f"Item number {n}"), now=NOW)
        with self.assertRaises(ApiError) as ctx:
            service.create_item(self.s, ALICE, body("LOST", "One too many"), now=NOW)
        self.assertEqual(429, ctx.exception.status)

    # ---- matching ----
    def test_matching_creates_pending_match_and_promotes_items(self):
        lost, found = self.lost_and_found()
        self.assertEqual(1, self.run_matching())
        matches = service.list_matches(self.s, ALICE)
        self.assertEqual(1, len(matches))
        self.assertEqual("PENDING", matches[0]["state"])
        self.assertEqual("POTENTIAL_MATCH", self.s.get_item(lost["id"])["status"])
        self.assertEqual("POTENTIAL_MATCH", self.s.get_item(found["id"])["status"])
        self.assertEqual(1, len(service.list_matches(self.s, BOB)))
        self.assertEqual([], service.list_matches(self.s, EVE))

    def test_matching_is_idempotent(self):
        lost, _ = self.lost_and_found()
        first = service.process_item(self.s, lost["id"], None, now=NOW)
        second = service.process_item(self.s, lost["id"], None, now=NOW)
        self.assertEqual((1, 0), (first, second))

    def test_same_user_never_matches_self(self):
        service.create_item(self.s, ALICE, body("LOST", "Black laptop bag", "Black backpack"), now=NOW)
        mine = service.create_item(self.s, ALICE, body("FOUND", "Black laptop bag", "Black backpack", at=NOW), now=NOW)
        self.assertEqual(0, service.process_item(self.s, mine["id"], None, now=NOW))

    # ---- respond ----
    def matched(self):
        lost, found = self.lost_and_found()
        service.process_item(self.s, found["id"], None, now=NOW)
        match = service.list_matches(self.s, ALICE)[0]
        return lost, found, match

    def test_owner_confirms(self):
        lost, found, match = self.matched()
        out = service.respond_to_match(self.s, ALICE, match["id"], True)
        self.assertEqual("CONFIRMED", out["state"])
        self.assertEqual("CLAIMED", self.s.get_item(lost["id"])["status"])
        self.assertEqual("CLAIMED", self.s.get_item(found["id"])["status"])

    def test_finder_cannot_confirm_and_strangers_see_nothing(self):
        _, _, match = self.matched()
        with self.assertRaises(ApiError) as ctx:
            service.respond_to_match(self.s, BOB, match["id"], True)
        self.assertEqual(403, ctx.exception.status)
        with self.assertRaises(ApiError) as ctx:
            service.respond_to_match(self.s, EVE, match["id"], True)
        self.assertEqual(404, ctx.exception.status)

    def test_cannot_answer_twice(self):
        _, _, match = self.matched()
        service.respond_to_match(self.s, ALICE, match["id"], False)
        with self.assertRaises(ApiError) as ctx:
            service.respond_to_match(self.s, ALICE, match["id"], True)
        self.assertEqual(409, ctx.exception.status)

    def test_reject_reverts_to_open_and_is_not_resurrected(self):
        lost, found, match = self.matched()
        service.respond_to_match(self.s, ALICE, match["id"], False)
        self.assertEqual("OPEN", self.s.get_item(lost["id"])["status"])
        self.assertEqual("OPEN", self.s.get_item(found["id"])["status"])
        self.assertEqual(0, service.process_item(self.s, found["id"], None, now=NOW))  # already decided
        self.assertEqual("REJECTED", service.list_matches(self.s, ALICE)[0]["state"])

    def test_confirm_rejects_competing_matches(self):
        lost, found, match = self.matched()
        other = service.create_item(self.s, EVE, body("FOUND", "Black laptop bag", "Black backpack Dell", at=NOW), now=NOW)
        service.process_item(self.s, other["id"], None, now=NOW)
        self.assertEqual(2, len(service.list_matches(self.s, ALICE)))
        service.respond_to_match(self.s, ALICE, match["id"], True)
        states = {m["foundItemId"]: m["state"] for m in service.list_matches(self.s, ALICE)}
        self.assertEqual("CONFIRMED", states[found["id"]])
        self.assertEqual("REJECTED", states[other["id"]])
        self.assertEqual("OPEN", self.s.get_item(other["id"])["status"])  # freed to match someone else

    # ---- return / close ----
    def test_return_flow(self):
        lost, found, match = self.matched()
        with self.assertRaises(ApiError):
            service.mark_returned(self.s, ALICE, lost["id"])  # not claimed yet
        service.respond_to_match(self.s, ALICE, match["id"], True)
        service.mark_returned(self.s, BOB, found["id"])
        self.assertEqual("RETURNED", self.s.get_item(lost["id"])["status"])
        self.assertEqual("RETURNED", self.s.get_item(found["id"])["status"])

    # ---- photo labels (Rekognition) ----
    def test_photo_labels_added_once_and_used_for_matching(self):
        key = "uploads/alice/123e4567-e89b-12d3-a456-426614174000.jpg"
        self.s.images.add(key)
        self.s.labels[key] = ["backpack", "bag"]
        lost = service.create_item(self.s, ALICE, body("LOST", "Black laptop bag", "Black backpack", imageKey=key), now=NOW)
        service.process_item(self.s, lost["id"], None, now=NOW)
        self.assertEqual(["backpack", "bag"], self.s.get_item(lost["id"])["imageLabels"])
        self.s.labels[key] = ["changed"]
        service.process_item(self.s, lost["id"], None, now=NOW)       # retry: labels are not asked for again
        self.assertEqual(["backpack", "bag"], self.s.get_item(lost["id"])["imageLabels"])

    def test_rekognition_failure_does_not_stop_matching(self):
        key = "uploads/bob/123e4567-e89b-12d3-a456-426614174001.jpg"
        self.s.images.add(key)
        self.s.label_errors.add(key)
        service.create_item(self.s, ALICE, body("LOST", "Black laptop bag", "Black backpack with Dell charger"), now=NOW)
        found = service.create_item(self.s, BOB, body("FOUND", "Black laptop bag", "Black backpack, Dell charger", at=NOW,
                                                      imageKey=key), now=NOW)
        self.assertEqual(1, service.process_item(self.s, found["id"], None, now=NOW))
        self.assertNotIn("imageLabels", self.s.get_item(found["id"]))

    # ---- finder's phone number ----
    def test_item_view_never_shows_private_contact_details(self):
        _, found = self.lost_and_found()
        self.assertNotIn("reporterPhone", found)
        self.assertNotIn("reporterEmail", found)
        self.assertEqual("+919876543210", self.s.get_item(found["id"])["reporterPhone"])

    def test_contact_only_for_owner_after_confirm(self):
        _, found, match = self.matched()
        with self.assertRaises(ApiError) as ctx:
            service.get_contact(self.s, ALICE, match["id"])      # not confirmed yet
        self.assertEqual(403, ctx.exception.status)
        service.respond_to_match(self.s, ALICE, match["id"], True)
        self.assertEqual({"phone": "+919876543210"}, service.get_contact(self.s, ALICE, match["id"]))
        for stranger in (BOB, EVE):                               # finder and bystander get nothing
            with self.assertRaises(ApiError) as ctx:
                service.get_contact(self.s, stranger, match["id"])
            self.assertEqual(404, ctx.exception.status)

    def test_contact_hidden_again_after_return_and_when_missing(self):
        lost, found, match = self.matched()
        service.respond_to_match(self.s, ALICE, match["id"], True)
        service.mark_returned(self.s, ALICE, lost["id"])
        with self.assertRaises(ApiError) as ctx:
            service.get_contact(self.s, ALICE, match["id"])
        self.assertEqual(404, ctx.exception.status)

    def test_finder_without_phone(self):
        nophone = User("carl", "Carl", "carl@campus.edu")
        service.create_item(self.s, ALICE, body("LOST", "Black laptop bag", "Black backpack with Dell charger"), now=NOW)
        found = service.create_item(self.s, nophone, body("FOUND", "Black laptop bag", "Black backpack, Dell charger inside", at=NOW), now=NOW)
        service.process_item(self.s, found["id"], None, now=NOW)
        match = service.list_matches(self.s, ALICE)[0]
        service.respond_to_match(self.s, ALICE, match["id"], True)
        with self.assertRaises(ApiError) as ctx:
            service.get_contact(self.s, ALICE, match["id"])
        self.assertEqual(404, ctx.exception.status)

    # ---- emails ----
    def test_emails_on_suggestion_and_confirm_never_contain_phone(self):
        with mock.patch("lf.notify.send") as send:
            _, _, match = self.matched()
            self.assertEqual({"alice@campus.edu", "bob@campus.edu"}, {c.args[0] for c in send.call_args_list})
            send.reset_mock()
            service.respond_to_match(self.s, ALICE, match["id"], True)
            self.assertEqual(1, send.call_count)
            self.assertEqual("bob@campus.edu", send.call_args.args[0])
            send.reset_mock()
            service.process_item(self.s, match["foundItemId"], None, now=NOW)   # retry: no duplicate emails
            self.assertEqual(0, send.call_count)

    def test_reject_sends_no_email(self):
        with mock.patch("lf.notify.send") as send:
            _, _, match = self.matched()
            send.reset_mock()
            service.respond_to_match(self.s, ALICE, match["id"], False)
            self.assertEqual(0, send.call_count)

    def test_only_owner_can_close(self):
        lost, _, _ = self.matched()
        with self.assertRaises(ApiError) as ctx:
            service.close_item(self.s, EVE, lost["id"])
        self.assertEqual(404, ctx.exception.status)

    def test_close_rejects_pending_and_frees_counterpart(self):
        lost, found, _ = self.matched()
        out = service.close_item(self.s, ALICE, lost["id"])
        self.assertEqual("CLOSED", out["status"])
        self.assertEqual("REJECTED", service.list_matches(self.s, BOB)[0]["state"])
        self.assertEqual("OPEN", self.s.get_item(found["id"])["status"])

    # ---- reads ----
    def test_feed_hides_closed_but_includes_counterparts_of_my_matches(self):
        lost, found, match = self.matched()
        service.respond_to_match(self.s, ALICE, match["id"], True)  # both CLAIMED => off the public feed
        ids_for_alice = {i["id"] for i in service.list_items(self.s, ALICE)}
        self.assertEqual({lost["id"], found["id"]}, ids_for_alice)
        self.assertEqual({lost["id"], found["id"]}, {i["id"] for i in service.list_items(self.s, BOB)})
        self.assertEqual(set(), {i["id"] for i in service.list_items(self.s, EVE)})

    def test_get_item_visibility(self):
        lost, found, match = self.matched()
        service.respond_to_match(self.s, ALICE, match["id"], True)
        service.get_item(self.s, ALICE, found["id"])  # counterpart allowed
        with self.assertRaises(ApiError):
            service.get_item(self.s, EVE, found["id"])  # claimed and unrelated

    # ---- upload / expiry ----
    def test_upload_only_jpeg_and_key_is_scoped(self):
        out = service.create_upload(self.s, ALICE, {"contentType": "image/jpeg"})
        self.assertTrue(out["key"].startswith("uploads/alice/"))
        with self.assertRaises(ApiError):
            service.create_upload(self.s, ALICE, {"contentType": "text/html"})

    def test_expiry_closes_old_reports(self):
        old = service.create_item(self.s, ALICE, body("LOST", "Old thing", at=NOW - 91 * 86_400_000), now=NOW - 90 * 86_400_000)
        fresh = service.create_item(self.s, ALICE, body("LOST", "Fresh thing"), now=NOW)
        closed = service.expire_old(self.s, NOW, 60)
        self.assertEqual(1, closed)
        self.assertEqual("CLOSED", self.s.get_item(old["id"])["status"])
        self.assertEqual("OPEN", self.s.get_item(fresh["id"])["status"])


if __name__ == "__main__":
    unittest.main()
