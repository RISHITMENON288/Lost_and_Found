import unittest
from unittest import mock

from lf import notify


class NotifyTest(unittest.TestCase):
    def test_off_without_sender_or_recipient(self):
        with mock.patch.dict("os.environ", {"SENDER_EMAIL": ""}):
            self.assertFalse(notify.send("a@campus.edu", "s", "b"))
        with mock.patch.dict("os.environ", {"SENDER_EMAIL": "me@campus.edu"}):
            self.assertFalse(notify.send(None, "s", "b"))

    def test_sends_one_plain_text_email(self):
        client = mock.Mock()
        with mock.patch.dict("os.environ", {"SENDER_EMAIL": "me@campus.edu"}), mock.patch.object(notify, "_client", client):
            self.assertTrue(notify.send("a@campus.edu", "Two\nlines", "Hello"))
        args = client.send_email.call_args.kwargs
        self.assertEqual("me@campus.edu", args["Source"])
        self.assertEqual({"ToAddresses": ["a@campus.edu"]}, args["Destination"])
        self.assertEqual("Two lines", args["Message"]["Subject"]["Data"])

    def test_failure_is_swallowed(self):
        client = mock.Mock()
        client.send_email.side_effect = RuntimeError("MessageRejected for secret@x.com")
        with mock.patch.dict("os.environ", {"SENDER_EMAIL": "me@campus.edu"}), mock.patch.object(notify, "_client", client):
            with self.assertLogs(level="WARNING") as logs:
                self.assertFalse(notify.send("a@campus.edu", "s", "b"))
        self.assertNotIn("secret@x.com", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
