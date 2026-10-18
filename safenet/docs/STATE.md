# State

What SafeNet keeps between messages, and where. The tables are `safenet/state/schema.sql`; the API creates
them on its first start (`setup_postgres.sh` only makes the database and the user). The code is
`safenet/state/store.py`.

**Message text is never stored.** Postgres keeps points, counters, the last 10 clean / not-clean bits and,
per `message_id`, the decision. (Each worker also caches the analysis of up to `SAFENET_ANALYSIS_CACHE`
recent texts in memory, starred text included; it is lost on restart.)

## Tables

| Table | One row per | Holds |
|---|---|---|
| `users` | platform, group, user | `points`, `recent` (`1` clean / `0` not, newest last, the profile's window: 10), `restrictions` so far, `restricted_until`, `messages` |
| `relations` | platform, sender → recipient | The same for A's messages to B only. The row exists only while `points` > 0. |
| `replies` | platform, `message_id` | The stored decision (JSON, no text), so a retry gets the same answer. Kept 7 days. |
| `counters` | platform, group, name | `messages`, `harmful`, `decision:<d>`, `reason:<r>`, `category:<c>`, `warnings`, `restrictions`, `replayed`. Group `''` is the whole platform. |

## One message, one transaction

1. Lock the sender's `users` row (`SELECT ... FOR UPDATE`, created if missing).
2. If the `message_id` is in `replies`, return that decision and change nothing (`"replayed": true`).
3. With `recipient_id`, lock the `relations` row too.
4. Decide (`engine/moderator.py`), write the new points, delete the relation row if it fell to 0, store the
   decision under its `message_id`.

So two workers (or two servers) answering the same sender wait for each other, and any worker gives the same
answer. Platform and group **counters** are summed in each worker and written about once a second, so
`/v1/stats` can lag that much and no message waits on a shared counter row.

## When Postgres is away

Any connection error, timeout, lock timeout or read-only database (a failover) answers **503** with
`Retry-After: 1`; `/health` says `"writable": false`. Nothing is half-written: the transaction is rolled back,
and a retry with the same `message_id` is counted once. Counters that could not be written are retried the
next second.

Without `SAFENET_DATABASE_URL` the API uses `MemoryStore`: the same rules in one process, lost on restart (tests,
laptops).
