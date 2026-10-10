#!/usr/bin/env python3
"""Track AI Inbox messages in GitHub Issues. No AI service is invoked."""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

AGENTS = ("claude", "codex", "grok", "owner")
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
MESSAGE_MARKER = re.compile(r"<!-- inbox-message:([\w.-]+\.md) -->")
DASHBOARD_MARKER = "<!-- ai-inbox-dashboard:v1 -->"
DATE_FMT = "%Y-%m-%d %H:%M UTC"

@dataclass(frozen=True)
class Message:
    path: str
    sender: str
    recipient: str
    date: datetime
    status: str

    @property
    def message_id(self) -> str:
        return Path(self.path).name

    @property
    def subject(self) -> str:
        parts = self.message_id.removesuffix(".md").split("-", 4)
        return parts[4].replace("-", " ") if len(parts) == 5 else self.message_id

def parse_message(path: Path, root: Path) -> Message:
    match = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"{path}: missing frontmatter")
    fields = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    sender, recipient, status = fields.get("from"), fields.get("to"), fields.get("status")
    if sender not in AGENTS or recipient not in AGENTS:
        raise ValueError(f"{path}: invalid from/to")
    if status not in ("open", "done"):
        raise ValueError(f"{path}: invalid status")
    try:
        date = datetime.strptime(fields["date"], DATE_FMT).replace(tzinfo=timezone.utc)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{path}: invalid UTC date") from exc
    relative = path.relative_to(root).as_posix()
    if relative.startswith("inbox/") and relative.split("/")[1] != recipient:
        raise ValueError(f"{path}: wrong recipient folder")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.md", path.name):
        raise ValueError(f"{path}: unsafe file name")
    return Message(relative, sender, recipient, date, status)

def scan(root: Path):
    messages, errors = [], []
    for agent in AGENTS:
        for path in sorted((root / "inbox" / agent).glob("*.md")):
            try:
                messages.append(parse_message(path, root))
            except (ValueError, OSError) as exc:
                errors.append(str(exc))
    if len({m.message_id for m in messages}) != len(messages):
        errors.append("Duplicate message file names")
    archived = {p.name for p in (root / "archive").rglob("*.md")}
    return messages, archived, errors

def link(repo: str, path: str) -> str:
    return f"https://github.com/{repo}/blob/main/{quote(path, safe='/')}"

def issue_contents(msg: Message, repo: str):
    title = f"📨 {msg.recipient} ← {msg.sender}: {msg.subject}"[:250]
    body = (
        f"<!-- inbox-message:{msg.message_id} -->\n"
        f"**To:** {msg.recipient} | **From:** {msg.sender} | **UTC:** {msg.date.strftime(DATE_FMT)}\n\n"
        f"**Message:** [{msg.message_id}]({link(repo, msg.path)})\n\n"
        "**Status:** Waiting for the recipient assistant to read and answer the file. "
        "This tracking issue is NOT evidence that any AI assistant has executed.\n\n"
        "**Owner visibility:** @coolman1984\n\n"
        "Mark the source message done or move it to archive/ to close this tracker.\n"
    )
    return title, body

def dashboard(messages, existing, repo, now, overdue_hours):
    active = sorted((m for m in messages if m.status == "open"), key=lambda m: (m.recipient, m.date))
    overdue = {m.message_id for m in active if now - m.date > timedelta(hours=overdue_hours)}
    lines = [DASHBOARD_MARKER, "# 📬 AI Inbox status", "",
             "**Tracking only:** sending a file does not start Claude, Codex or Grok.", "",
             f"**Open:** {len(active)} | **Overdue (>{overdue_hours}h):** {len(overdue)}", ""]
    for agent in AGENTS:
        items = [m for m in active if m.recipient == agent]
        lines.extend([f"## {agent} · {len(items)}", ""])
        if not items:
            lines.extend(["Nothing waiting.", ""])
        for msg in items:
            issue = existing.get(msg.message_id)
            tracker = f"[#{issue['number']}]({issue['html_url']})" if issue else "(tracker pending)"
            flag = " 🔴 OVERDUE" if msg.message_id in overdue else ""
            lines.append(f"- [{msg.subject}]({link(repo, msg.path)}) · from {msg.sender} · {tracker}{flag}")
        lines.append("")
    lines.append("Issue closes after status: done or archive/.")
    return "\n".join(lines) + "\n"

class Github:
    def __init__(self, repo, token):
        self.repo, self.token = repo, token
        self.base = f"https://api.github.com/repos/{repo}"

    def call(self, method, endpoint, payload=None):
        req = Request(self.base + endpoint,
                      data=json.dumps(payload).encode("utf-8") if payload is not None else None,
                      headers={"Authorization": f"Bearer {self.token}",
                               "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28",
                               "User-Agent": "ai-inbox-tracker"}, method=method)
        try:
            with urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"GitHub HTTP {exc.code}: {method} {endpoint}: {detail}") from exc

    def list_issues(self):
        results = []
        for page in range(1, 21):
            items = self.call("GET", f"/issues?state=all&per_page=100&page={page}")
            results.extend(item for item in items if "pull_request" not in item)
            if len(items) < 100:
                return results
        raise RuntimeError("Too many issues: please review pagination limits.")

    def create(self, title, body):
        return self.call("POST", "/issues", {"title": title, "body": body})

    def update(self, number, fields):
        return self.call("PATCH", f"/issues/{number}", fields)

def synchronize(root, api, now, overdue_hours=24):
    messages, archived, errors = scan(root)
    if errors:
        raise ValueError("\n".join(errors))
    existing, board = {}, None
    for issue in api.list_issues():
        body = issue.get("body") or ""
        marker = MESSAGE_MARKER.search(body)
        if marker:
            key = marker.group(1)
            if key in existing:
                raise ValueError(f"Duplicate tracker for {key}")
            existing[key] = issue
        if DASHBOARD_MARKER in body:
            if board is not None:
                raise ValueError("Duplicate dashboards")
            board = issue
    active = {m.message_id: m for m in messages if m.status == "open"}
    completed = archived | {m.message_id for m in messages if m.status == "done"}
    created = changed = closed = 0
    for key, msg in active.items():
        title, body = issue_contents(msg, api.repo)
        old = existing.get(key)
        if old is None:
            existing[key] = api.create(title, body)
            created += 1
        else:
            patch = {}
            if old["state"] != "open":
                patch["state"] = "open"
            if old.get("title") != title:
                patch["title"] = title
            if old.get("body") != body:
                patch["body"] = body
            if patch:
                existing[key] = api.update(old["number"], patch)
                changed += 1
    for key, issue in existing.items():
        if key in completed and key not in active and issue["state"] == "open":
            api.update(issue["number"], {"state": "closed", "state_reason": "completed"})
            closed += 1
    title = "📬 AI Inbox · Live dashboard"
    body = dashboard(messages, existing, api.repo, now, overdue_hours)
    if board is None:
        api.create(title, body)
    else:
        patch = {}
        if board["state"] != "open":
            patch["state"] = "open"
        if board.get("title") != title:
            patch["title"] = title
        if board.get("body") != body:
            patch["body"] = body
        if patch:
            api.update(board["number"], patch)
    return f"Open {len(active)}; trackers created {created}, updated {changed}, closed {closed}"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sync", action="store_true")
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--overdue-hours", type=int, default=24)
    args = p.parse_args()
    if args.overdue_hours < 1:
        p.error("overdue-hours must be at least 1")
    messages, _, errors = scan(args.root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Validated {len(messages)} messages")
    if args.sync:
        token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if not token or not repo or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            print("GITHUB_TOKEN and GITHUB_REPOSITORY required", file=sys.stderr)
            return 2
        print(synchronize(args.root, Github(repo, token), datetime.now(timezone.utc), args.overdue_hours))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
