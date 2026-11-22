# The Monday briefing did not arrive

Code: `scheduler.py` (`weekly_summary`, Monday 07:00 UTC = 10:00 Turkey time; `_dispatch_monday_briefings`),
`services/briefing_delivery.py`, `services/outbox.py`, `api/monday_briefing.py`.

How it works: at 07:00 UTC the scheduler assembles each organisation's briefing, caches it in Redis
(`monday_briefing:<org id>`, 7 days), writes an in-app notification and queues one outbox e-mail per
recipient with a key that includes the week, so a second run cannot send it twice. The outbox sender runs
every five minutes. With an accountant (`smmm`) on the company, the e-mail is **held** until the accountant
releases it (`POST /briefing/monday/release`).

## Check

1. **In the app:** `GET /briefing/monday` shows the briefing even if no mail went; `GET /briefing/monday/deliveries`
   shows each e-mail's state for the company (the user or an owner can read it).
2. **Held?** status `held` = waiting for the accountant. Ask them to release it.
3. **Recipients:** `GET /org/me/briefing-recipients`. No recipient, no mail.
4. **Outbox:**
   ```bash
   psql_app -c "select created_at, status, attempts, last_error from outbox_messages
                where org_id = '<org id>' and source = 'monday_briefing' order by created_at desc limit 5;"
   ```
   `failed: smtp_not_configured`: see [login-and-email.md](login-and-email.md) item 1.
   No row at all for this week: the dispatch did not run or found nothing to send.
5. **Did the scheduler run?** `dc logs worker | grep -E 'Monday briefing|Scheduler'`. APScheduler skips a run
   whose start time passed while the process was down: **a worker restarting at 07:00 UTC loses that week's
   run** (no `misfire_grace_time`, audit item 6.3). `dc logs worker | grep -i 'missed'` shows it.
6. `/api/v1/ready`: `checks.scheduler` `no_recent_outbox_pass` means nothing is delivering.

## Fix

- Held: the accountant releases it. Failed for mail configuration: configure mail; failed rows stay failed,
  so queue it again (below).
- The run was missed: run the dispatch once by hand; it is idempotent for the week (unique outbox key):
  ```bash
  dc exec worker python -c "import asyncio; from app.scheduler import _dispatch_monday_briefings as d; asyncio.run(d())"
  ```
  Do it on Monday or Tuesday only; the briefing text is "this week's".
- Scheduler not running at all: `dc logs worker | grep -i scheduler` must show `CFO Scheduler started`;
  otherwise check `SCHEDULER_PROCESS` and `SCHEDULER_ENABLED`.

## Not verified

The manual dispatch command and the outbox queries were written from the code, not run. Whether a run
after a missed one duplicates the in-app notification was not tested.
