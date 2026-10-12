I'll review the transport office app as QA only, without changing files. First I'll map the server and view code, then list concrete bugs and business-rule issues with file and line.Core trip rules are in place. Next I’ll check permissions, trip screens, and how km, times, and report totals are enforced.The permission and trip-save paths look central. I’ll read those next, plus the trip and report screens.Permissions and the trip screen show several weak spots. I’ll check how status, odometer, and money are written and reported.Status and money flow through dedicated trip routes. I’ll check the driver path, reports UI, and whether vehicle or driver double-booking is blocked.Driver events and reports are in view. I’ll look at how km and status are validated, and how lists and Excel treat the same rules.A few totals look inconsistent. I’ll confirm the overtime math, week filter, and whether inactive vehicles or expired licenses can still be assigned.Read-only QA review of the trip lifecycle, kilometres, times, report totals, permissions, and the trip screens. No files were changed.

1. **Critical** — Amend can set any status and any odometer with no checks. `server/tripsvc.py:73` and `js/views/trips.js:114`. `amend` only checks that the field exists and a reason is at least 3 characters. The dialog offers draft, sent, started, finished, closed, and cancelled, and accepts negative or zero kilometres. A reviewer can jump a trip to closed, reopen a finished trip, or enter an end reading below the start. `km_of` then reports a negative distance, and reports drop it (`km > 0`), so the trip counts with 0 km.

2. **Critical** — Excel import drops the warning flag and still closes the trip. `server/excel_io.py:440`. `importWarn` is set `False` and then removed because it is empty. Bad rows (end km not above start, back-step, huge km, missing date) are imported as locked `closed` trips. Trust never raises `Y_IMPORT_WARN` (`server/domain.py:274`), so finance treats them as clean closed trips.

3. **High** — Same-day rate change does not reprice. `server/pricing.py:65`. If history already has an `until` of today or later, `stamp` returns the old history and ignores the new rate. A correction typed the same day never applies. Reports keep using the previous rate for every later trip.

4. **High** — One vehicle or driver can be on two trips at once. `server/tripsvc.py:44` and `js/views/trips.js:30`. Create and amend never look at other open trips. Nothing blocks assigning a car or driver who is already `started` or booked the same day. A real dispatch desk double-books.

5. **High** — Cancelling does not free the vehicle. `server/tripsvc.py:97` and `server/domain.py:206`. Cancel only sets status to `cancelled`. Odometer chain skips cancelled trips, but start and end readings stay. The next trip of that car is flagged `R_BACKSTEP` or a gap even though the cancelled trip should not occupy the meter.

6. **High** — Approval is not part of the lifecycle. `server/tripsvc.py:106` and `server/gateway_client.py:236`. GA approve and decline only write `gaApproved`. A declined trip can still get a driver link, start, and finish. An unapproved draft can be sent. The approver profile cannot send or cancel (`server/auth.py:114`), so decline has no operational effect.

7. **High** — Office overtime and Excel overtime disagree. `server/domain.py:169` and `server/excel_io.py:486`. Reports use real elapsed time, including overnight trips. The “same as today” workbook uses clock times only: if end is earlier than start, overtime becomes 0. A 22:00–02:00 trip is about 4 hours in the app and 0 in the sheet the vendor sees. Export also drops the date from the end time (`server/excel_io.py:483`), so a next-day end looks like the same day.

8. **High** — Reconciliation money uses one rate for the group and another for the lines. `server/reports.py:104`. `diffMoney` is added trip by trip with each trip’s own rate, then `rate` is overwritten with the last trip’s rate. A month with a mid-month rate change shows a rate that does not explain the money total.

9. **High** — Trip list totals do not match the Reports page. `js/views/trips.js:261`. The list adds kilometres and overtime for the filtered rows, including drafts, and the trip count includes cancelled trips while km excludes them. Reports exclude cancelled trips and only count known positive km (`server/reports.py:15`). The same month shows two different totals.

10. **High** — Dispatcher can rewrite a locked trip through a plain save. `server/app.py:312` and `server/auth.py:112`. Any trip update that is not only approval or link fields requires `trips.edit`, `trips.amend`, or `trips.review`. The dispatcher profile has `trips.edit`. `commit_guard` blocks a locked trip only when `internal` is false (`server/app.py:356`). A direct `/api/commit` of start km, end km, or billable km on a locked trip succeeds with no amendment record.

11. **High** — “Week” is the browser’s week, not the office week. `js/views/trips.js:18`. The filter uses `new Date()` and Sunday-based `getDay()`. The server treats every business day as Cairo time (`server/domain.py:150`). After midnight in Egypt, a PC set to another zone shows the wrong day, and Saturday/Sunday weeks do not match an Egyptian Saturday–Thursday office week.

12. **Medium** — Finished trip with no kilometres still looks billable. `server/reports.py:32` and `server/domain.py:248`. Missing readings become `kmDone = 0` and still add a trip to department cost. `NO_KM` is only a warning (`server/reports.py:146`). A closed trip with blank odometer is included in vendor kilometres as zero.

13. **Medium** — Billable km of 0 is hidden and skipped. `js/views/trips.js:196` and `server/reports.py:100`. The panel uses `t.billableKm` as a condition, so 0 is not shown. Reconciliation keeps only rows where `billableKm is not None`, but a stored `0` is falsy in the UI. A vendor line of 0 km disappears from the trip card while reports still count it.

14. **Medium** — Passengers cannot be changed after create. `js/views/trips.js:96` and `server/tripsvc.py:64`. Amend has no passenger field. Create allows 12 names; later edits need a raw `tripPassengers` save, which a reviewer does not have (`trips.edit` only). The printed form and driver card keep the original names.

15. **Medium** — Inactive vehicles and expired licences can still be assigned. `js/ui.js:64` hides inactive records in the dropdown, but `server/tripsvc.py:51` only checks that the id exists. Amend and Excel import do not check `active` or `licenseExpiry`. A deleted-from-the-list driver or an expired licence still runs trips.

16. **Medium** — Standard routes are advertised and never editable. `js/i18n/en.js:68` and `js/views/lists.js:255`. Places page text says routes carry expected km. The page only loads `places`. The `routes` entity (`server/store.py:55`, `standardKm`, `billableKm`) has no form. Unusual-km uses past trips only (`server/domain.py:222`), not the standard route.

17. **Medium** — No fuel, maintenance, invoices, or trip allowance. `server/store.py:38` and `server/reports.py:121`. Vehicles have a baseline odometer and notes. Drivers have a licence. Cost is only km × rate + overtime × rate. A transport office cannot record fuel, service, accidents, vendor invoices, or a per-diem. Those amounts never appear in allocation.

18. **Medium** — Print and Word forms leave the operational fields blank. `js/views/print.js:15` and `server/app.py:760`. The paper form has start km, end km, start time, and end time, but `values()` only fills passenger, department, driver, plate, date, and route. The Word form does the same and labels the category as `carType`. The driver receives a form he must fill again by hand.

19. **Medium** — Review queue never clears. `js/views/board.js:54` and `server/domain.py:270`. Any amendment adds `Y_AMENDED`, and closing from the office adds `Y_CLOSED_BY_OFFICE`. There is no “clear review” action even though `trips.review` is described as closing trips and clearing flags (`server/auth.py:65`). A corrected trip stays yellow forever.

20. **Medium** — WhatsApp opens with an empty number. `js/views/trips.js:224`. Send always calls `wa.me/` plus the driver’s mobile. If mobile is missing, the URL is `https://wa.me/?text=...`, which does not open the driver’s chat. The link is still marked sent (`server/tripsvc.py:140`).

21. **Medium** — First rate typed later reprices the whole past. `server/pricing.py:60`. A category created with an empty rate, then given a rate months later, writes that rate into every history slot that was empty. Last year’s closed trips change cost on the day someone finally types the rate.

22. **Low** — Board “done” and “needs attention” double-count. `js/views/board.js:20`. A finished trip that is yellow or red matches both the done column (only if green) and the attention column, but a green finished trip is only in done. A yellow finished trip is only in attention, so the column totals do not add up to the day’s trips. The same trip can also sit in “on the road” and “attention” when it has been open too long.

23. **Low** — Grey trips are invisible in the trust chips. `js/views/trips.js:262`. Summary counts green, yellow, and red only. Drafts and sent trips are grey (`server/domain.py:283`) and do not appear in any chip, so the badges do not add up to the trip count shown beside them.

24. **Low** — Link expiry ignores the real end of the trip. `server/domain.py:155`. Expiry is seven days from now, or three days after the planned date, whichever is later. A trip dated next month gets a link that dies three days after that date even if the driver has not finished. A trip that runs long after its planned date keeps a link for only three days past the plan.

25. **Low** — Destination is free text, so the same place splits in reports. `js/views/trips.js:40` and `server/reports.py:76`. The field suggests old spellings but does not require a place record. `topRoutes` groups by normalised text. “القاهرة” and “القاهره” merge, but “Cairo” and “القاهرة” stay two routes, and unusual-km history splits with them.
