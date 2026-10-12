#!/usr/bin/env python3
"""Safe, opt-in GitHub coding-agent dispatch from reviewed JSON jobs.

Uses GitHub issues + a user-authorized GitHub token, not a paid model API.
A job can only start the Copilot cloud agent after the owner's GitHub account
has that agent enabled for the target repository.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ALLOWED_REPOS = frozenset({
    "coolman1984/Inbox",
    "coolman1984/Apps-Factory",
    "coolman1984/Store",
    "coolman1984/Teachers",
    "coolman1984/Yousef-Transportation",
    "coolman1984/3D-Modeling",
})
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,62}\Z")
AGENTS = frozenset({"copilot", "claude", "codex"})
MARKER_PREFIX = "<!-- ai-dispatch:"
MAX_NEW_PER_RUN = 1


class DispatchError(Exception):
    """Non-secret, actionable validation or dispatch error."""


def validate_job(data: object, filename: str) -> dict:
    if not isinstance(data, dict):
        raise DispatchError(f"{filename}: expected JSON object")
    required = {"id", "repo", "agent", "title", "task", "approved"}
    if set(data) != required:
        raise DispatchError(f"{filename}: unexpected or missing JSON keys")
    job_id = data["id"]
    if not isinstance(job_id, str) or not ID_PATTERN.fullmatch(job_id):
        raise DispatchError(f"{filename}: invalid job id")
    if filename != job_id + ".json":
        raise DispatchError(f"{filename}: file name must match job id")
    if not isinstance(data["repo"], str) or data["repo"] not in ALLOWED_REPOS:
        raise DispatchError(f"{filename}: target repository is not allowlisted")
    if not isinstance(data["agent"], str) or data["agent"] not in AGENTS:
        raise DispatchError(f"{filename}: unknown agent")
    if type(data["approved"]) is not bool:
        raise DispatchError(f"{filename}: approved must be a boolean")
    for key, maximum in (("title", 140), ("task", 6000)):
        value = data[key]
        if not isinstance(value, str) or not 5 <= len(value.strip()) <= maximum:
            raise DispatchError(f"{filename}: invalid {key} length")
    if re.search(r"(gh[pousr]_[A-Za-z0-9_]{15,}|sk-[A-Za-z0-9_-]{18,})", data["task"]):
        raise DispatchError(f"{filename}: possible credential in task")
    return data


def read_jobs(folder: Path) -> list[dict]:
    if not folder.exists():
        return []
    jobs = []
    for path in sorted(folder.glob("*.json")):
        if path.name.startswith("_"):
            continue
        jobs.append(validate_job(json.loads(path.read_text(encoding="utf-8")), path.name))
    return jobs


def issue_marker(job_id: str) -> str:
    return f"{MARKER_PREFIX}{job_id} -->"


class Github:
    """GitHub REST wrapper. Never logs the bearer token."""

    def __init__(self, token: str):
        self.token = token

    def call(self, repo: str, method: str, endpoint: str, payload=None):
        url = f"https://api.github.com/repos/{repo}{endpoint}"
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "owner-approved-agent-dispatch",
            },
            method=method,
        )
        try:
            with urlopen(req, timeout=25) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # Do not echo response bodies (they can contain sensitive fields).
            raise DispatchError(
                f"GitHub returned HTTP {exc.code} when {method} {repo}{endpoint}. "
                "Check Copilot eligibility, agent enablement and user-token permissions."
            ) from exc

    def find_existing(self, repo: str, marker: str):
        for page in range(1, 11):
            issues = self.call(repo, "GET", f"/issues?state=all&per_page=100&page={page}")
            for issue in issues:
                if "pull_request" not in issue and marker in (issue.get("body") or ""):
                    return issue
            if len(issues) < 100:
                return None
        raise DispatchError(f"{repo}: issue pagination limit reached; stopped safely")

    def launch_copilot(self, job: dict):
        repo = job["repo"]
        body = (
            f"{issue_marker(job['id'])}\n"
            "Owner-approved coding-agent task. Source: coolman1984/Inbox.\n\n"
            "DO NOT merge, publish, delete data, change credentials, or make purchases. "
            "Create a draft PR, run available tests, and report verified results.\n\n"
            f"## Task\n{job['task']}\n\n"
            "## Completion criteria\nDraft pull request + test evidence + owner review.\n"
        )
        return self.call(
            repo, "POST", "/issues",
            {
                "title": f"[Agent queue] {job['title']}",
                "body": body,
                "assignees": ["copilot-swe-agent[bot]"],
                "agent_assignment": {
                    "target_repo": repo,
                    "base_branch": "main",
                    "custom_instructions": "Create a draft PR. Do not merge.",
                },
            },
        )


def dispatch(jobs: list[dict], api: Github, max_new: int = MAX_NEW_PER_RUN) -> list[str]:
    results = []
    launched = 0
    for job in jobs:
        if not job["approved"]:
            results.append(f"{job['id']}: awaiting owner approval")
            continue
        if job["agent"] != "copilot":
            results.append(
                f"{job['id']}: blocked; verified automatic assignment is only "
                "implemented for Copilot, not Claude/Codex"
            )
            continue
        existing = api.find_existing(job["repo"], issue_marker(job["id"]))
        if existing:
            results.append(f"{job['id']}: already dispatched (issue #{existing['number']})")
            continue
        if launched >= max_new:
            results.append(f"{job['id']}: queued; hourly budget cap reached")
            continue
        issue = api.launch_copilot(job)
        launched += 1
        results.append(f"{job['id']}: assigned, issue #{issue['number']} (not yet completed)")
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Dispatch with user token")
    parser.add_argument("--jobs", type=Path, default=Path(__file__).resolve().parents[1] / "jobs")
    args = parser.parse_args()
    try:
        jobs = read_jobs(args.jobs)
        print(f"Validated {len(jobs)} job(s); approved: {sum(j['approved'] for j in jobs)}")
        if not args.execute:
            print("Dry run: no external tasks started")
            return 0
        token = os.environ.get("AGENT_DISPATCH_USER_TOKEN", "")
        if not token:
            print("BLOCKED: GitHub user-authorized agent token is not configured")
            return 0
        for result in dispatch(jobs, Github(token)):
            print(result)
        return 0
    except (DispatchError, ValueError, OSError) as exc:
        print(f"Dispatch blocked: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
