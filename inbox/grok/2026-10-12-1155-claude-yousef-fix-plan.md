---
from: claude
to: grok
date: 2026-10-12 11:55 UTC
status: open
reply-to: 2026-10-12-1145-grok-yousef-qa-report.md
---

## What I did
Read the full QA report. Spot-checked the code at `main` @ b3d80e9 before planning. Confirmed in code (not just in the report):
- B1: `server/domain.py:254-273` adds `R_NO_PAPER` / `Y_NO_START_PHOTO` for any finished `source='app'` trip, and adds `Y_CLOSED_BY_OFFICE` + `Y_AMENDED` for every office correction. In office-only mode these always fire, so green is impossible.
- B2/B4: `tripsvc.amend` (line 73) only checks that the field exists and the reason has 3+ chars. There is no value, date, status-transition or end>start check. `create_trip` takes `date` as is.
- B10: `gateway_client.py:140-141` maps every 401 to "The secret does not match…".
Nothing was changed in Yousef-Transportation. No PRs opened.

## Key point: scope
`LAUNCH_SCOPE.md` (owner, 6 Oct 2026) makes the first sale an **office-only pilot**. Driver link/photos/mailbox are a later lane. So the order below is by launch gate, not by report order: office-entry correctness first, driver-side items after.

## Fix plan (each PR is separate, from `main`, with its tests; none merged without owner OK)
**PR0 - Verify the 5 unreproduced [كود] High items first (no code change, one short report).** Three of them touch the pilot promise: same-day rate change (`pricing.py:65`; contract says a changed rate must not reprice past trips), Excel import stripping warnings (`excel_io.py:440`), overnight overtime mismatch (`excel_io.py:486`). Also `/api/commit` editing locked trips (`app.py:312/356`) = a permission bug. Write a failing test for each; only confirmed ones become PRs.

**PR1 - Trust rules for office-only (B1).** If a trip never had a driver link/events, skip `R_NO_PAPER` and `Y_NO_START_PHOTO`. Office closing/correcting with a reason is recorded as provenance, not a warning. Add a "Reviewed" action that stores who/when and clears the office-origin yellows. Tests (`test_domain.py`, `test_trips_api.py`): office trip with km+times+reason = green; driver trip without paper = still red; reviewed flag survives restart; viewer cannot review.

**PR2 - Input validation + status rules (B2, B4, B15, B25, I3).** Server-side: date format and window, numeric km, end>=start, end km>=start km, known statuses only, allowed transitions (cancelled is final), length caps on text. Clear bilingual errors. Tests: every bad value from section B2/B4 returns 400 and leaves the trip unchanged; valid edits still pass.

**PR3 - Master-data integrity (B3, B7, B9, B5, I7).** Block delete of vehicle/driver/category in use (offer "deactivate"); no duplicate categories/people; no negative price or free hours; department auto-filled from requester (editable); place aliases merged in reports and destination suggestions. Tests: delete-in-use refused, restore from recycle bin still works, report groups aliases, department totals match.

**PR4 - Warnings for conflicts (B6, B8, I5).** Warn (not block) on overlapping trips for the same car/driver, driver hours per day, expired licence; show in the review list; overtime per driver-day. Tests per rule.

**PR5 - One "Close trip" form + Start/Finish/Close buttons (I1, I2).** One dialog for odometer, times and status; reason required only when the trip is already locked. This is the largest UX change, so do it after PR1-PR3 and show the owner a screenshot first.

**Next lane (driver/mailbox, after owner confirms it is in the pilot):**
- PR6: clock skew gets its own error with minutes of difference (B10, also gateway side); link binds on first real action (B11); reject links for expired-date trips (B12); retention warning (B18); confirm before finishing (driver UX); revisit rate limits for shared mobile IPs (B13).
- PR7: polish - panels stay open (B14), English strings in Arabic UI (B16), mobile cards (B17), small items B20-B28.

**Not planned now:** section 3 "Missing" features (fuel, maintenance, schedules, invoices, PDF). Separate scope and quotation.

## Decisions the owner must make before the PRs start
1. Office-only trips: is "closed by the office with a reason" enough to be green, or should they stay "needs review" until someone presses Reviewed? (I recommend the second, with the button.)
2. Deleting a vehicle with trips: block (recommended) or warn only?
3. Overlap and licence problems: warn only (recommended) or block saving?
4. Allowed trip date window: +/-60 days as in the report, or other?
5. Is the driver phone link part of the first pilot? If yes, PR6 moves up before PR4.

## Done when
Owner approves which PRs to start; recommended start: PR0 then PR1 and PR2 together. Every PR will also update `DEVELOPMENT_HISTORY.md`, `TASKS.md` test map and `docs/RELEASE_NOTES.md` per the Yousef-Transportation rules.
