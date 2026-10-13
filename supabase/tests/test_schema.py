"""Tests for supabase/schema.sql, run on a plain Postgres with a small emulation of Supabase's auth/storage.

    LF_TEST_DSN=postgresql://postgres@127.0.0.1:5432/postgres python -m unittest discover -s supabase/tests -v

Each test acts as a signed-in app user: the connection switches to the `authenticated` role and sets the
JWT subject, exactly like Supabase's API does. So these tests exercise Row Level Security, not just the logic.
"""
import json
import os
import random
import sys
import unittest
import uuid
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "ml"))

DSN = os.environ.get("LF_TEST_DSN", "postgresql://postgres@127.0.0.1:54329/postgres")
DB_NAME = "lf_test_" + uuid.uuid4().hex[:8]

HOUR = 3_600_000
DAY = 24 * HOUR


def now_ms():
    import time
    return int(time.time() * 1000)


def _admin_dsn(db):
    base, _, _ = DSN.rpartition("/")
    return f"{base}/{db}"


_available = None


def available():
    global _available
    if _available is None:
        try:
            if psycopg is None:
                raise RuntimeError("psycopg not installed")
            psycopg.connect(DSN, connect_timeout=3).close()
            _available = True
        except Exception:
            _available = False
    return _available


def setUpModule():
    if not available():
        raise unittest.SkipTest("No Postgres reachable (set LF_TEST_DSN)")
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f'create database "{DB_NAME}"')
    with psycopg.connect(_admin_dsn(DB_NAME), autocommit=True) as conn:
        conn.execute((HERE / "fake_supabase.sql").read_text(encoding="utf-8"))
        schema = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
        conn.execute(schema)
        conn.execute(schema)  # idempotent: running it twice must not fail or lose anything


def tearDownModule():
    if not available():
        return
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f'drop database if exists "{DB_NAME}" with (force)')


class Db:
    """One connection per test. `admin` = database owner, `as_user` = a signed-in app user."""

    def __init__(self):
        self.conn = psycopg.connect(_admin_dsn(DB_NAME), autocommit=True)

    def close(self):
        self.conn.close()

    def admin(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else None

    def make_user(self, name, email=None, phone="auto"):
        """Like signing up: the app sends the phone number as sign-up metadata."""
        uid = str(uuid.uuid4())
        meta = {"name": name}
        if phone == "auto":
            phone = "+9198" + "".join(random.choice("0123456789") for _ in range(8))
        if phone is not None:
            meta["phone"] = phone
        self.admin(
            "insert into auth.users (id, email, raw_user_meta_data) values (%s, %s, %s)",
            (uid, email or f"{name.lower()}@campus.edu", json.dumps(meta)),
        )
        return uid

    def as_user(self, uid, sql, params=None):
        """Run one statement as `authenticated` with the given user id, in its own transaction."""
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute("set local role authenticated")
                cur.execute("select set_config('request.jwt.claim.sub', %s, true)", (uid or "",))
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else None

    def as_anon(self, sql, params=None):
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute("set local role anon")
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else None

    def report(self, uid, type_, title, category, location="Library", description="", hours_ago=2, image_path=None):
        rows = self.as_user(
            uid,
            "insert into public.items (type, title, category, description, location, occurred_at, image_path) "
            "values (%s, %s, %s, %s, %s, %s, %s) returning id",
            (type_, title, category, description, location, now_ms() - int(hours_ago * HOUR), image_path),
        )
        return rows[0][0]

    def status(self, item_id):
        return self.admin("select status from public.items where id = %s", (item_id,))[0][0]

    def matches_for(self, uid):
        return self.as_user(uid, "select id, lost_item_id, found_item_id, state, score from public.matches order by created_at")


class SchemaTestCase(unittest.TestCase):
    def setUp(self):
        self.db = Db()
        self.db.admin("truncate public.items cascade")
        self.db.admin("delete from storage.objects")
        self.db.admin("delete from auth.users")
        self.db.admin("update public.match_settings set model = null")
        self.alice = self.db.make_user("Alice")
        self.bob = self.db.make_user("Bob")
        self.carol = self.db.make_user("Carol")

    def tearDown(self):
        self.db.close()

    def assertSqlState(self, state, fn, *args, **kwargs):
        with self.assertRaises(psycopg.Error) as ctx:
            fn(*args, **kwargs)
        self.assertEqual(ctx.exception.sqlstate, state, str(ctx.exception))


class MatchingFlow(SchemaTestCase):
    def lost_and_found(self):
        lost = self.db.report(self.alice, "LOST", "Black backpack", "BAG", description="Black backpack with Dell laptop charger")
        found = self.db.report(self.bob, "FOUND", "Black laptop bag", "BAG", description="bag with a charger inside", hours_ago=1)
        return lost, found

    def test_matching_pair_creates_pending_suggestion_for_both(self):
        lost, found = self.lost_and_found()
        for who in (self.alice, self.bob):
            rows = self.db.matches_for(who)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][3], "PENDING")
            self.assertGreaterEqual(float(rows[0][4]), 0.60)
        self.assertEqual(self.db.status(lost), "POTENTIAL_MATCH")
        self.assertEqual(self.db.status(found), "POTENTIAL_MATCH")
        self.assertEqual(self.db.matches_for(self.carol), [])

    def test_hard_gates_prevent_false_positives(self):
        lost = self.db.report(self.alice, "LOST", "Black backpack", "BAG", description="Black backpack with Dell laptop charger")
        other_category = self.db.report(self.bob, "FOUND", "Black backpack", "CLOTHING", description="Black backpack with Dell laptop charger")
        no_shared_word = self.db.report(self.bob, "FOUND", "Umbrella", "BAG", description="green umbrella")
        own_report = self.db.report(self.alice, "FOUND", "Black backpack", "BAG", description="Black backpack with Dell laptop charger")
        self.db.report(self.bob, "FOUND", "Black backpack", "BAG", description="Black backpack with Dell laptop charger", hours_ago=2 + 30)  # found 30h BEFORE lost
        self.assertEqual(self.db.matches_for(self.alice), [])
        self.assertEqual(self.db.status(lost), "OPEN")
        for item in (other_category, no_shared_word, own_report):
            self.assertEqual(self.db.status(item), "OPEN")

    def test_only_lost_owner_can_respond_and_confirm_claims_both(self):
        lost, found = self.lost_and_found()
        match_id = self.db.matches_for(self.alice)[0][0]
        self.assertSqlState("PT403", self.db.as_user, self.bob, "select public.respond_to_match(%s, true)", (match_id,))
        self.assertSqlState("PT404", self.db.as_user, self.carol, "select public.respond_to_match(%s, true)", (match_id,))
        self.db.as_user(self.alice, "select public.respond_to_match(%s, true)", (match_id,))
        self.assertEqual(self.db.status(lost), "CLAIMED")
        self.assertEqual(self.db.status(found), "CLAIMED")
        self.assertSqlState("PT409", self.db.as_user, self.alice, "select public.respond_to_match(%s, true)", (match_id,))

        self.assertSqlState("PT404", self.db.as_user, self.carol, "select public.mark_returned(%s)", (found,))
        self.db.as_user(self.bob, "select public.mark_returned(%s)", (found,))
        self.assertEqual(self.db.status(lost), "RETURNED")
        self.assertEqual(self.db.status(found), "RETURNED")

    def test_reject_reopens_reports_and_pair_is_never_resuggested(self):
        lost, found = self.lost_and_found()
        match_id = self.db.matches_for(self.alice)[0][0]
        self.db.as_user(self.alice, "select public.respond_to_match(%s, false)", (match_id,))
        self.assertEqual(self.db.status(lost), "OPEN")
        self.assertEqual(self.db.status(found), "OPEN")
        # new activity must not resurrect the rejected pair
        self.db.report(self.carol, "FOUND", "Black bag", "BAG", description="a charger", hours_ago=1)
        rows = self.db.matches_for(self.alice)
        states = {(r[1], r[2]): r[3] for r in rows}
        self.assertEqual(states[(lost, found)], "REJECTED")

    def test_confirming_one_match_rejects_the_competing_suggestions(self):
        lost = self.db.report(self.alice, "LOST", "Black backpack", "BAG", description="charger inside")
        f1 = self.db.report(self.bob, "FOUND", "Black bag", "BAG", description="charger", hours_ago=1)
        f2 = self.db.report(self.carol, "FOUND", "Black backpack", "BAG", description="charger", hours_ago=1)
        rows = {r[2]: r[0] for r in self.db.matches_for(self.alice)}
        self.assertEqual(set(rows), {f1, f2})
        self.db.as_user(self.alice, "select public.respond_to_match(%s, true)", (rows[f1],))
        states = {r[2]: r[3] for r in self.db.matches_for(self.alice)}
        self.assertEqual(states, {f1: "CONFIRMED", f2: "REJECTED"})
        self.assertEqual(self.db.status(f2), "OPEN")  # goes back to waiting
        self.assertEqual(self.db.status(lost), "CLAIMED")

    def test_closing_a_report_rejects_pending_and_frees_the_other_side(self):
        lost, found = self.lost_and_found()
        self.assertSqlState("PT404", self.db.as_user, self.bob, "select public.close_item(%s)", (lost,))
        self.db.as_user(self.alice, "select public.close_item(%s)", (lost,))
        self.assertEqual(self.db.status(lost), "CLOSED")
        self.assertEqual(self.db.status(found), "OPEN")
        self.assertEqual(self.db.matches_for(self.bob)[0][3], "REJECTED")
        self.assertSqlState("PT409", self.db.as_user, self.alice, "select public.close_item(%s)", (lost,))

    def test_expiry_closes_old_reports(self):
        lost = self.db.report(self.alice, "LOST", "Red umbrella", "BAG")
        self.db.admin("update public.items set created_at = created_at - %s where id = %s", (90 * DAY, lost))
        self.assertEqual(self.db.admin("select public.lf_expire_old(60)")[0][0], 1)
        self.assertEqual(self.db.status(lost), "CLOSED")


class Visibility(SchemaTestCase):
    def test_closed_reports_are_private_but_matched_counterparts_stay_visible(self):
        lost = self.db.report(self.alice, "LOST", "Black backpack", "BAG", description="charger")
        found = self.db.report(self.bob, "FOUND", "Black bag", "BAG", description="charger", hours_ago=1)
        mid = self.db.matches_for(self.alice)[0][0]
        self.db.as_user(self.alice, "select public.respond_to_match(%s, true)", (mid,))
        # CLAIMED is not "open", but each side must still see the other's report through the match
        alice_sees = {r[0] for r in self.db.as_user(self.alice, "select id from public.items")}
        bob_sees = {r[0] for r in self.db.as_user(self.bob, "select id from public.items")}
        carol_sees = {r[0] for r in self.db.as_user(self.carol, "select id from public.items")}
        self.assertEqual(alice_sees, {lost, found})
        self.assertEqual(bob_sees, {lost, found})
        self.assertEqual(carol_sees, set())  # claimed reports are no longer public

    def test_anonymous_users_see_nothing_and_cannot_write(self):
        self.db.report(self.alice, "LOST", "Black backpack", "BAG")
        self.assertSqlState("42501", self.db.as_anon, "select * from public.items")
        self.assertSqlState("42501", self.db.as_anon, "select * from public.matches")


class Tampering(SchemaTestCase):
    def test_clients_cannot_forge_or_edit_anything_directly(self):
        lost = self.db.report(self.alice, "LOST", "Black backpack", "BAG")
        found = self.db.report(self.bob, "FOUND", "Umbrella", "BAG", description="green umbrella")
        deny = "42501"
        self.assertSqlState(deny, self.db.as_user, self.bob, "update public.items set status = 'CLAIMED' where id = %s", (found,))
        self.assertSqlState(deny, self.db.as_user, self.bob, "delete from public.items where id = %s", (lost,))
        self.assertSqlState(
            deny, self.db.as_user, self.bob,
            "insert into public.matches (lost_item_id, found_item_id, lost_reporter_id, found_reporter_id, score) "
            "values (%s, %s, %s, %s, 0.99)", (lost, found, self.alice, self.bob))
        self.assertSqlState(deny, self.db.as_user, self.bob, "select * from public.match_settings")
        self.assertSqlState(deny, self.db.as_user, self.bob, "update public.match_settings set model = '{}'")
        self.assertSqlState(deny, self.db.as_user, self.bob, "select public.lf_run_matching(%s)", (lost,))
        self.assertSqlState(deny, self.db.as_user, self.bob, "select public.lf_expire_old(0)")

    def test_client_cannot_choose_reporter_status_or_created_at(self):
        self.assertSqlState(
            "42501", self.db.as_user, self.bob,
            "insert into public.items (type, title, category, location, occurred_at, reporter_id) "
            "values ('LOST', 'Black backpack', 'BAG', 'Library', %s, %s)", (now_ms() - HOUR, self.alice))
        self.assertSqlState(
            "42501", self.db.as_user, self.bob,
            "insert into public.items (type, title, category, location, occurred_at, status) "
            "values ('LOST', 'Black backpack', 'BAG', 'Library', %s, 'CLAIMED')", (now_ms() - HOUR,))

    def test_reporter_identity_comes_from_the_session(self):
        item = self.db.report(self.bob, "LOST", "Black backpack", "BAG")
        row = self.db.admin("select reporter_id, reporter_name, status from public.items where id = %s", (item,))[0]
        self.assertEqual((str(row[0]), row[1], row[2]), (self.bob, "Bob", "OPEN"))

    def test_signed_out_insert_is_rejected(self):
        self.assertSqlState(
            "PT401", self.db.as_user, None,
            "insert into public.items (type, title, category, location, occurred_at) "
            "values ('LOST', 'Black backpack', 'BAG', 'Library', %s)", (now_ms() - HOUR,))


class Validation(SchemaTestCase):
    def insert(self, **overrides):
        values = dict(type="LOST", title="Black backpack", category="BAG", description="", location="Library",
                      occurred_at=now_ms() - HOUR, image_path=None)
        values.update(overrides)
        return self.db.as_user(
            self.alice,
            "insert into public.items (type, title, category, description, location, occurred_at, image_path) "
            "values (%(type)s, %(title)s, %(category)s, %(description)s, %(location)s, %(occurred_at)s, %(image_path)s)",
            values)

    def test_rejects_bad_input(self):
        self.assertSqlState("PT400", self.insert, title="ab")
        self.assertSqlState("PT400", self.insert, title="x" * 61)
        self.assertSqlState("PT400", self.insert, title="   ab   ")
        self.assertSqlState("PT400", self.insert, description="x" * 301)
        self.assertSqlState("PT400", self.insert, location="Moon base")
        self.assertSqlState("PT400", self.insert, occurred_at=now_ms() + DAY)
        self.assertSqlState("PT400", self.insert, occurred_at=now_ms() - 400 * DAY)
        self.assertSqlState("23514", self.insert, category="WEAPONS")
        self.assertSqlState("23514", self.insert, type="SELL")

    def test_control_characters_are_stripped_and_text_trimmed(self):
        self.insert(title="  Black\x07 backpack  ", description=" x\x01y ")
        row = self.db.admin("select title, description from public.items")[0]
        self.assertEqual(row, ("Black backpack", "xy"))

    def test_limit_of_twenty_open_reports(self):
        for i in range(20):
            self.insert(title=f"Item number {i}")
        self.assertSqlState("PT429", self.insert, title="One too many")

    def test_photo_must_exist_and_live_in_the_users_own_folder(self):
        good = f"{self.alice}/{uuid.uuid4()}.jpg"
        self.assertSqlState("PT400", self.insert, image_path=good)  # never uploaded
        self.db.as_user(self.alice, "insert into storage.objects (bucket_id, name, owner) values ('item-photos', %s, %s)", (good, self.alice))
        self.insert(image_path=good)
        stolen = f"{self.bob}/{uuid.uuid4()}.jpg"
        self.db.admin("insert into storage.objects (bucket_id, name, owner) values ('item-photos', %s, %s)", (stolen, self.bob))
        self.assertSqlState("PT400", self.insert, image_path=stolen)
        self.assertSqlState("PT400", self.insert, image_path=f"{self.alice}/../x.jpg")


class Photos(SchemaTestCase):
    def test_bucket_is_private_with_limits(self):
        row = self.db.admin("select public, file_size_limit, allowed_mime_types from storage.buckets where id = 'item-photos'")[0]
        self.assertEqual(row, (False, 5242880, ["image/jpeg"]))

    def test_upload_only_into_own_folder_and_no_overwrite_or_delete(self):
        mine = f"{self.alice}/{uuid.uuid4()}.jpg"
        self.db.as_user(self.alice, "insert into storage.objects (bucket_id, name, owner) values ('item-photos', %s, %s)", (mine, self.alice))
        self.assertSqlState("42501", self.db.as_user, self.alice,
                            "insert into storage.objects (bucket_id, name, owner) values ('item-photos', %s, %s)",
                            (f"{self.bob}/{uuid.uuid4()}.jpg", self.alice))
        # no update/delete policy: RLS hides the row from those statements, so nothing changes
        self.db.as_user(self.alice, "update storage.objects set name = name || 'x' where name = %s", (mine,))
        self.db.as_user(self.alice, "delete from storage.objects where name = %s", (mine,))
        self.assertEqual(self.db.admin("select count(*) from storage.objects where name = %s", (mine,))[0][0], 1)

    def test_photos_are_readable_only_with_access_to_the_report(self):
        path = f"{self.alice}/{uuid.uuid4()}.jpg"
        self.db.as_user(self.alice, "insert into storage.objects (bucket_id, name, owner) values ('item-photos', %s, %s)", (path, self.alice))

        def count(uid):
            return self.db.as_user(uid, "select count(*) from storage.objects where name = %s", (path,))[0][0]

        self.assertEqual(count(self.alice), 1)
        self.assertEqual(count(self.bob), 0)  # uploaded but not attached to any report yet
        item = self.db.report(self.alice, "LOST", "Black backpack", "BAG", image_path=path)
        self.assertEqual(count(self.bob), 1)  # open report: public to signed-in users
        self.db.as_user(self.alice, "select public.close_item(%s)", (item,))
        self.assertEqual(count(self.bob), 0)  # closed: private again


class ScoreParityWithPython(SchemaTestCase):
    """The SQL matcher must give the same answer as the Python reference the ML training uses."""

    WORDS = ["black", "Blue", "RED", "bag", "backpack", "laptop", "charger", "the", "with", "found", "near", "key",
             "keys", "id", "card", "wallet", "steel", "bottle", "cat", "dell", "hp", "and", "inside", "side", "x9", "42"]
    LOCATIONS = ["Library", "library", "Main Gate", "Academic Block", "Cafeteria", "Other"]

    def random_item(self, rng, type_, category, base):
        title = " ".join(rng.choice(self.WORDS) + rng.choice(["", "", ",", "!"]) for _ in range(rng.randint(1, 4)))
        description = " ".join(rng.choice(self.WORDS) for _ in range(rng.randint(0, 8)))
        return {"type": type_, "category": category, "title": title, "description": description,
                "location": rng.choice(self.LOCATIONS), "occurredAt": base + rng.randint(-10 * DAY, 10 * DAY)}

    def sql_score(self, lost, found, model):
        def rec(item):
            return json.dumps({"type": item["type"], "category": item["category"], "title": item["title"],
                               "description": item["description"], "location": item["location"],
                               "occurred_at": item["occurredAt"]})
        return self.db.admin(
            "select public.lf_score(jsonb_populate_record(null::public.items, %s::jsonb), "
            "jsonb_populate_record(null::public.items, %s::jsonb), %s::jsonb)",
            (rec(lost), rec(found), json.dumps(model) if model else None))[0][0]

    def compare(self, model):
        import lf_matcher
        rng = random.Random(7)
        base = now_ms()
        nonzero = 0
        for _ in range(400):
            category = rng.choice(["BAG", "BAG", "KEYS"])
            lost = self.random_item(rng, "LOST", category, base)
            found = self.random_item(rng, "FOUND", category if rng.random() < 0.9 else "KEYS", base)
            expected = lf_matcher.score(lost, found, model)
            actual = self.sql_score(lost, found, model)
            self.assertAlmostEqual(actual, expected, places=9, msg=f"{lost} vs {found}")
            nonzero += expected > 0
        self.assertGreater(nonzero, 60, "the random pairs should include plenty of non-gated cases")

    def test_default_weights(self):
        self.compare(None)

    def test_trained_logistic_model(self):
        model = {"type": "logistic", "bias": -2.1,
                 "weights": {"text": 3.2, "location": 1.1, "time": 0.7, "image": 2.0, "has_image": -0.3}, "threshold": 0.55}
        self.compare(model)

    def test_stored_model_is_used_only_when_valid(self):
        good = {"type": "logistic", "bias": -2.0, "threshold": 0.9,
                "weights": {"text": 3.0, "location": 1.0, "time": 0.5, "image": 1.0, "has_image": 0.0}}
        self.db.admin("update public.match_settings set model = %s::jsonb", (json.dumps(good),))
        self.assertEqual(self.db.admin("select public.lf_threshold(public.lf_model())")[0][0], 0.9)
        broken = dict(good, weights={"text": 3.0})
        self.db.admin("update public.match_settings set model = %s::jsonb", (json.dumps(broken),))
        self.assertIsNone(self.db.admin("select public.lf_model()")[0][0])
        self.assertEqual(self.db.admin("select public.lf_threshold(public.lf_model())")[0][0], 0.6)
        self.db.admin("update public.match_settings set model = '\"junk\"'::jsonb")
        self.assertIsNone(self.db.admin("select public.lf_model()")[0][0])


if __name__ == "__main__":
    unittest.main()


class PhoneContact(SchemaTestCase):
    def confirmed_match(self):
        self.db.report(self.alice, "LOST", "Black backpack", "BAG", description="Black backpack with Dell laptop charger")
        self.db.report(self.bob, "FOUND", "Black laptop bag", "BAG", description="bag with a charger inside", hours_ago=1)
        match_id = self.db.matches_for(self.alice)[0][0]
        return match_id

    def finder_phone(self):
        return self.db.admin("select phone from public.profiles where user_id = %s", (self.bob,))[0][0]

    def test_nobody_can_read_profiles_directly(self):
        self.assertSqlState("42501", self.db.as_user, self.alice, "select * from public.profiles")
        self.assertSqlState("42501", self.db.as_user, self.bob, "select phone from public.profiles where user_id = %s", (self.bob,))
        self.assertSqlState("42501", self.db.as_user, self.alice, "update public.profiles set phone = '+911111111111'")
        self.assertSqlState("42501", self.db.as_anon, "select * from public.profiles")

    def test_phone_from_signup_is_saved_cleaned_and_validated(self):
        spaced = self.db.make_user("Dave", phone="+91 98765-43210")
        self.assertEqual(self.db.admin("select phone from public.profiles where user_id = %s", (spaced,))[0][0], "+919876543210")
        for bad in (None, "12345", "abc1234567890", "+91 (98) 7; drop table items"):
            uid = self.db.make_user("Eve", phone=bad)  # signing up must still work
            self.assertEqual(self.db.admin("select count(*) from public.profiles where user_id = %s", (uid,))[0][0], 0)

    def test_owner_sees_finder_number_only_after_confirming(self):
        match_id = self.confirmed_match()
        # suggestion still pending: nobody gets a number
        self.assertSqlState("PT409", self.db.as_user, self.alice, "select public.get_match_contact(%s)", (match_id,))
        self.db.as_user(self.alice, "select public.respond_to_match(%s, true)", (match_id,))
        number = self.db.as_user(self.alice, "select public.get_match_contact(%s)", (match_id,))[0][0]
        self.assertEqual(number, self.finder_phone())

    def test_finder_and_strangers_never_get_a_number(self):
        match_id = self.confirmed_match()
        self.db.as_user(self.alice, "select public.respond_to_match(%s, true)", (match_id,))
        self.assertSqlState("PT403", self.db.as_user, self.bob, "select public.get_match_contact(%s)", (match_id,))
        self.assertSqlState("PT404", self.db.as_user, self.carol, "select public.get_match_contact(%s)", (match_id,))
        self.assertSqlState("PT401", self.db.as_user, None, "select public.get_match_contact(%s)", (match_id,))
        self.assertSqlState("42501", self.db.as_anon, "select public.get_match_contact(%s)", (match_id,))

    def test_no_number_after_reject_or_return(self):
        match_id = self.confirmed_match()
        self.db.as_user(self.alice, "select public.respond_to_match(%s, false)", (match_id,))
        self.assertSqlState("PT409", self.db.as_user, self.alice, "select public.get_match_contact(%s)", (match_id,))

        self.db.admin("truncate public.items cascade")
        match_id = self.confirmed_match()
        self.db.as_user(self.alice, "select public.respond_to_match(%s, true)", (match_id,))
        found = self.db.admin("select found_item_id from public.matches where id = %s", (match_id,))[0][0]
        self.db.as_user(self.bob, "select public.mark_returned(%s)", (found,))
        self.assertSqlState("PT409", self.db.as_user, self.alice, "select public.get_match_contact(%s)", (match_id,))

    def test_found_report_needs_a_phone_but_lost_does_not(self):
        nophone = self.db.make_user("Frank", phone=None)
        self.db.report(nophone, "LOST", "Blue bottle", "CONTAINER")
        self.assertSqlState("PT400", self.db.report, nophone, "FOUND", "Blue bottle", "CONTAINER")

    def test_finder_without_number_gives_a_clear_error(self):
        match_id = self.confirmed_match()
        self.db.as_user(self.alice, "select public.respond_to_match(%s, true)", (match_id,))
        self.db.admin("delete from public.profiles where user_id = %s", (self.bob,))
        self.assertSqlState("PT404", self.db.as_user, self.alice, "select public.get_match_contact(%s)", (match_id,))
