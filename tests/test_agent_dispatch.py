import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dispatch_agent_tasks import (DispatchError, dispatch, issue_marker,
                                  read_jobs, validate_job)


def job(job_id="smoke-001", approved=True, agent="copilot", repo="coolman1984/Inbox"):
    return {
        "id": job_id,
        "repo": repo,
        "agent": agent,
        "title": "Safe, documentation-only smoke test",
        "task": "Create only a draft pull request with one documentation file. Never merge.",
        "approved": approved,
    }


class FakeGithub:
    def __init__(self):
        self.issues = {}
        self.launches = []

    def find_existing(self, repo, marker):
        return self.issues.get((repo, marker))

    def launch_copilot(self, payload):
        self.launches.append(payload["id"])
        number = len(self.launches)
        issue = {"number": number}
        self.issues[(payload["repo"], issue_marker(payload["id"]))] = issue
        return issue


class AgentDispatchTests(unittest.TestCase):
    def test_valid_job(self):
        self.assertEqual(validate_job(job(), "smoke-001.json")["agent"], "copilot")

    def test_requires_owner_approval(self):
        api = FakeGithub()
        self.assertIn("awaiting owner approval", dispatch([job(approved=False)], api)[0])
        self.assertFalse(api.launches)

    def test_idempotent_even_after_first_delivery(self):
        api = FakeGithub()
        dispatch([job()], api)
        self.assertIn("already dispatched", dispatch([job()], api)[0])
        self.assertEqual(api.launches, ["smoke-001"])

    def test_caps_at_one_new_job_per_hour(self):
        api = FakeGithub()
        results = dispatch([job(), job("smoke-002")], api)
        self.assertEqual(len(api.launches), 1)
        self.assertIn("hourly budget cap", results[1])

    def test_unverified_claude_is_not_impersonated(self):
        api = FakeGithub()
        result = dispatch([job(agent="claude")], api)[0]
        self.assertIn("blocked", result)
        self.assertFalse(api.launches)

    def test_unverified_codex_is_not_impersonated(self):
        api = FakeGithub()
        result = dispatch([job(agent="codex")], api)[0]
        self.assertIn("blocked", result)
        self.assertFalse(api.launches)

    def test_disallowed_repo(self):
        with self.assertRaises(DispatchError):
            validate_job(job(repo="evil-org/other"), "smoke-001.json")

    def test_reject_non_string_repo_and_agent(self):
        payload = job()
        payload["repo"] = []
        with self.assertRaises(DispatchError):
            validate_job(payload, "smoke-001.json")
        payload = job()
        payload["agent"] = {}
        with self.assertRaises(DispatchError):
            validate_job(payload, "smoke-001.json")

    def test_reject_unapproved_string(self):
        payload = job()
        payload["approved"] = "true"
        with self.assertRaises(DispatchError):
            validate_job(payload, "smoke-001.json")

    def test_reject_mismatched_file(self):
        with self.assertRaises(DispatchError):
            validate_job(job(), "other-job.json")

    def test_reject_extra_keys(self):
        payload = job()
        payload["shell"] = "rm -rf /"
        with self.assertRaises(DispatchError):
            validate_job(payload, "smoke-001.json")

    def test_reject_possible_secret(self):
        payload = job()
        payload["task"] += " ghp_" + "A" * 20
        with self.assertRaises(DispatchError):
            validate_job(payload, "smoke-001.json")

    def test_unapproved_example_stays_idle(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "smoke-001.json"
            p.write_text(json.dumps(job(approved=False)), encoding="utf-8")
            loaded = read_jobs(Path(temp))
            self.assertEqual(len(loaded), 1)
            api = FakeGithub()
            dispatch(loaded, api)
            self.assertFalse(api.launches)


if __name__ == "__main__":
    unittest.main()
