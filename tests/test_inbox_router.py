import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from inbox_router import dashboard, parse_message, scan, synchronize

SAMPLE = """---
from: grok
to: claude
date: 2026-10-10 20:29 UTC
status: open
reply-to:
---

## What I did
Delivered sound kit.
"""
NAME = "2026-10-10-2029-grok-sound-kit.md"

class FakeGithub:
    repo = "coolman1984/Inbox"

    def __init__(self):
        self.items = []
        self.calls = []

    def list_issues(self):
        return [dict(x) for x in self.items]

    def create(self, title, body):
        n = len(self.items) + 1
        item = {"number": n, "state": "open", "title": title, "body": body,
                "html_url": f"https://github.com/coolman1984/Inbox/issues/{n}"}
        self.items.append(item)
        self.calls.append(("create", n))
        return dict(item)

    def update(self, number, fields):
        for item in self.items:
            if item["number"] == number:
                item.update(fields)
                self.calls.append(("update", number))
                return dict(item)
        raise KeyError(number)

class Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for directory in ("inbox/claude", "inbox/codex", "inbox/grok", "inbox/owner", "archive"):
            (self.root / directory).mkdir(parents=True)
        self.path = self.root / "inbox/claude" / NAME
        self.path.write_text(SAMPLE, encoding="utf-8")
        self.now = datetime(2026, 10, 10, 22, tzinfo=timezone.utc)

    def test_valid_message(self):
        m = parse_message(self.path, self.root)
        self.assertEqual((m.sender, m.recipient, m.status), ("grok", "claude", "open"))

    def test_wrong_folder_rejected(self):
        self.path.write_text(SAMPLE.replace("to: claude", "to: owner"), encoding="utf-8")
        self.assertEqual(len(scan(self.root)[2]), 1)

    def test_idempotent(self):
        api = FakeGithub()
        self.assertIn("trackers created 1", synchronize(self.root, api, self.now))
        self.assertEqual(len(api.items), 2)
        self.assertIn("Tracking only", api.items[1]["body"])
        synchronize(self.root, api, self.now)
        self.assertEqual(len(api.calls), 2)

    def test_archive_closes(self):
        api = FakeGithub()
        synchronize(self.root, api, self.now)
        self.path.rename(self.root / "archive" / NAME)
        synchronize(self.root, api, self.now)
        self.assertEqual(api.items[0]["state"], "closed")
        self.assertIn("**Open:** 0", api.items[1]["body"])

    def test_done_status_closes(self):
        api = FakeGithub()
        synchronize(self.root, api, self.now)
        self.path.write_text(SAMPLE.replace("status: open", "status: done"), encoding="utf-8")
        synchronize(self.root, api, self.now)
        self.assertEqual(api.items[0]["state"], "closed")

    def test_deleted_message_not_closed(self):
        api = FakeGithub()
        synchronize(self.root, api, self.now)
        self.path.unlink()
        synchronize(self.root, api, self.now)
        self.assertEqual(api.items[0]["state"], "open")

    def test_overdue(self):
        messages, _, errors = scan(self.root)
        self.assertFalse(errors)
        board = dashboard(messages, {}, api_repo(), self.now + timedelta(days=2), 24)
        self.assertIn("🔴 OVERDUE", board)

    def test_bad_status_rejected(self):
        self.path.write_text(SAMPLE.replace("status: open", "status: busy"), encoding="utf-8")
        self.assertEqual(len(scan(self.root)[2]), 1)

def api_repo():
    return "coolman1984/Inbox"

if __name__ == "__main__":
    unittest.main()
