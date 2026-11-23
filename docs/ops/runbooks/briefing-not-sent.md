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
5. **Did the scheduler run?** `dc logs worker | grep -E 'Monday briefing|Scheduler|catch-up'`. APScheduler keeps no
   jobs across a restart, so a tick that fell while the worker was down is never seen by it. The application
   therefore keeps a ledger (`scheduled_job_runs`: one row per job, company and period) and a catch-up job
   (30 seconds after start, then every 10 minutes) that runs what was due, is inside its window and not finished:
   the Monday briefing and the morning brief until the end of that UTC day, the nightly run until 12:00, the
   hourly KRI scan only within its own hour (older ones are skipped). Check the ledger:
   ```bash
   psql_app -c "select job, period, status, attempts, last_error from scheduled_job_runs order by claimed_at desc limit 20;"
   ```
   `failed` is retried (up to 5 attempts; the operators get a mail after `JOB_FAILURE_ALERT_AFTER`); `running`
   older than 20 minutes is a dead process and is taken over. A caught-up briefing mails the operators once.
6. `/api/v1/ready`: `checks.scheduler` `no_recent_outbox_pass` means nothing is delivering.

## Fix

- Held: the accountant releases it. Failed for mail configuration: configure mail; failed rows stay failed,
  so queue it again (below).
- The run was missed and the window has passed (or 5 attempts failed): run the dispatch once by hand; it is
  idempotent for the week (ledger row and unique outbox key). Delete nothing; a `done` row makes it a no-op:
  ```bash
  dc exec worker python -c "import asyncio; from app.scheduler import _dispatch_monday_briefings as d; asyncio.run(d())"
  ```
  Do it on Monday or Tuesday only; the briefing text is "this week's".
- Scheduler not running at all: `dc logs worker | grep -i scheduler` must show `CFO Scheduler started`;
  otherwise check `SCHEDULER_PROCESS` and `SCHEDULER_ENABLED`.

## Not verified

The manual dispatch command, the ledger and outbox queries were written from the code, not run on a host.
Catch-up, double start and a crash in the middle are tested (`tests/test_schedule_catchup.py`); a real restart at
07:00 with Redis and Postgres and two scheduler processes together were not run.
