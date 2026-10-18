# State

Where the API keeps what it remembers between messages, so any worker on any server gives the same answer.
The code is `safenet/state/store.py`; the tables are `safenet/state/schema.sql`, created on the API's first start.
**Message text is never stored**, not in Postgres and not in memory (DECISION_ENGINE choice 16).

## Tables

| Table | Key | Holds |
|---|---|---|
| `users` | platform, group, user | hidden points, the last messages as clean `1` / not clean `0` (newest last), restrictions so far, `restricted_until`, message count |
| `relations` | platform, sender, recipient | A → B points, the same clean / not-clean bits, message count. Deleted when the points reach 0 |
| `replies` | platform, `message_id` | the decision as JSON, without text, so a retry gets the same answer. Kept 7 days (`REPLY_DAYS`) |
| `counters` | platform, group (`''` = the whole platform), name | `messages`, `harmful`, `decision:*`, `category:*`, `reason:*`, `warnings`, `restrictions`, `replayed` |

## One message, one transaction

1. Lock the sender's `users` row (`SELECT ... FOR UPDATE`, created at 0 the first time).
2. If the request has a `message_id` already in `replies`, answer with the stored decision and change nothing.
3. With `recipient_id`, lock the A → B `relations` row the same way.
4. Decide (`engine/`), then write both rows and the reply, and commit.

Two workers with messages from the same sender wait for each other on step 1, so a retry that arrives while
the first try is still running sees its reply and counts nothing twice. Points, restrictions and relations are
therefore always exact; only the counters are allowed to lag.

**Counters** are added up in each worker's memory and written once a second
(`INSERT ... ON CONFLICT DO UPDATE SET n = counters.n + EXCLUDED.n`), so `/v1/stats` can be about a second
behind `/v1/check`. A failed write is retried the next second. Old replies are deleted every 10 minutes.

## When Postgres is slow or gone

`deploy/linuxone/setup_postgres.sh` gives the API's role `statement_timeout = 2s`, `lock_timeout = 1s` and
`idle_in_transaction_session_timeout = 10s`; the connection pool waits `SAFENET_DB_TIMEOUT_S` (2 s). Any of
these, a lost connection or a read-only server (a replica after failover) ends the transaction without a
change and the API answers **503 + `Retry-After: 1`**: the platform retries with the same `message_id`.
`/health` answers 503 while `pg_is_in_recovery()` is true or the tables can't be read.

## Without Postgres

With no `SAFENET_DATABASE_URL`, `MemoryStore` keeps the same tables in the worker's memory: one process, lost
on restart. It is for laptops, tests and `degerlendir.py`, never for a server with several workers.

## The analysis cache

Not state, but the other thing a worker remembers: the analysis of up to `SAFENET_ANALYSIS_CACHE` (4,096)
recent texts (`engine/analysis.py`), keyed by a hash of the text, so a repeated message skips the models. It
holds offsets, scores and the listed words found; the starred text is made again from each request.
