# Owner-controlled agent dispatch (pilot)

## Current state

This is a **gated bridge**, not a claim that all assistants are already connected.

- The existing Inbox monitor continues tracking messages as before.
- A new independent queue reads `jobs/*.json`.
- Dry runs and all local unit tests require **no model API** and **no secret**.
- The dispatcher supports **Copilot cloud agent only**, because its REST issue-assignment contract is documented. Requests for Claude and Codex remain explicitly blocked until independently verified. Grok is not supported by GitHub coding-agent assignment.
- At most **one new agent task per workflow execution**, with a whole-repo allowlist and duplicate markers.
- No automatic merging, deleting, shell-command execution from task text, or payments.
- Nothing executes when the user token is missing or a task has `"approved": false`.

## Activation prerequisites

1. GitHub Copilot coding agent must be available and enabled for the target repository, by the owner. A plan or feature toggle may be required.
2. GitHub must accept assignments to `copilot-swe-agent[bot]` from a **user-authorized token**, rather than the restricted GitHub Actions token. This is a GitHub token, **not a paid AI model API key**. The documented fine-grained token permissions for agent assignment include repository Actions, Contents, Issues and Pull requests; restrict the token to allowlisted repositories and the shortest permitted lifetime.
3. In the Inbox GitHub repository settings, store that token as the Actions secret named `AGENT_DISPATCH_USER_TOKEN`. Never paste it in issues, JSON job files, chat, code or logs.
4. On a dedicated branch, create a file `jobs/<id>.json` using `jobs/_sample.json` as the starting point. Change `approved` to `true` only after reviewing task scope, billing and public disclosure risks, then merge the job through ordinary checks. Owner approval is required for paid or risky actions.

The account connection currently used by ChatGPT rejected an attempt to assign Copilot (HTTP 422: agent cannot be assigned). **Until the required entitlement/permissions are enabled, the bridge cannot honestly be described as end-to-end autonomous.**

## Validation

```sh
python -m unittest discover -s tests -v
python scripts/dispatch_agent_tasks.py
```

When enabled, the GitHub Action runs at minute 23 every hour and on new jobs merged into main. It starts **at most one** new approved Copilot issue assignment per run. Only a genuine agent-authored draft PR or session log proves the worker executed. Re-running the queue finds the existing marker and will not duplicate the assignment.

## Queue file fields

All are required: `id` (matches filename), `repo` (from the allowlist), `agent` (currently only `copilot` dispatches), `title`, `task`, and boolean `approved`.

`_sample.json` is intentionally ignored and cannot launch an agent.

## Security and cost limits

- Inbox is currently **public**, so job content must not contain personal data, secrets or private client code.
- Only the owner's repository write permission should permit merging approved job files into main. Use branch protection or review rules to maintain that boundary.
- If an assignment is rejected, the workflow stops and reports a blocked state. No fake success, no silent fallback to charging a different AI provider.
- The workflow does not create its own AI subscription. Coding-agent usage may consume GitHub Copilot premium requests according to the owner's plan.
- The job cap is per dispatch run, **not a true monthly spending cap**. Monitor GitHub's agent usage separately.
- Do not enable the secret if GitHub cannot authorize the agent. The earlier account-level assignment probe was rejected.

## Acceptance stages

1. Offline tests validate queue rules and idempotency.
2. Pull request checks pass for the dispatch bridge.
3. A user-authorized test assignment succeeds to an allowlisted repository.
4. The real GitHub agent creates a draft PR with test evidence.
5. Owner reviews; no automatic merge.

Stages 3–5 cannot be inferred from stages 1–2.
