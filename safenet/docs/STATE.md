# State

What SafeNet keeps between messages, where, and how one message is written. The code is
`safenet/state/store.py`; the tables are `safenet/state/schema.sql`, created on the API's first start.

**Message text is never stored.** Only points, counters, the last clean / not-clean bits and, per `message_id`,
the decision. A user costs about 200 bytes, however many messages they send.

## Tables (PostgreSQL)

| Table | Key | Holds |
|---|---|---|
| `users` | platform, group, user | hidden points, the last 10 messages as clean (`1`) / not (`0`), restriction count and end, message count |
| `relations` | platform, sender, recipient | the A → B points and history; the row exists only while its points are above 0 |
| `replies` | platform, message_id | the stored answer (JSON, no text), so a retry gets the same decision; kept 7 days |
| `counters` | platform, group (`''` = whole platform), name | messages, harmful, `decision:block`, `category:threat`, `reason:...`, warnings, restrictions, replayed |

A user's points are per group ("7b", a game server, a clan): moving to another group starts at 0 there.
A relation is platform-wide: once A's messages stop reaching B, they stop in every group.

## One message, one transaction

1. Insert the sender's `users` row if new, then lock it (`SELECT ... FOR UPDATE`).
2. With a `message_id`: if `replies` already has it, return that answer, count `replayed`, change nothing.
3. With a `recipient_id`: insert and lock the A → B `relations` row.
4. The engine decides (`engine/moderator.py`), then the new points, the relation (deleted when back to 0) and
   the reply are written, and the transaction commits.

Two messages from the same sender wait for each other on step 1, so parallel requests never lose points
(`tests/test_check.py::test_parallel_messages_from_one_sender_all_count`). Workers keep nothing between
requests: any worker on any server gives the same answer.

Counters are summed in each worker and written about once a second (`ON CONFLICT ... n = n + EXCLUDED.n`), so
busy groups never make every message wait on one row; `/v1/stats` can lag by that second. Every ten minutes a
worker deletes replies older than 7 days.

## When Postgres is not there

Unreachable, too slow (`statement_timeout` 2 s, `lock_timeout` 1 s) or read-only (a replica during failover):
`/v1/check` answers **503 with `Retry-After: 1`** and `/health` says `"status": "degraded"`. The platform
retries with the same `message_id` (`client/safenet_client.py` does), so nothing is counted twice; what the
recipient sees meanwhile is the platform's choice (holding it is the safe one for children). Counters that could
not be written are kept and retried the next second.

Without `SAFENET_DATABASE_URL` the API uses `MemoryStore`: the same logic in one process's memory, for tests,
laptops and `measure.py` / `simulate.py`. It is lost on restart and is not shared between workers, so it is for
one worker only.

## Sizes

| Row | Bytes (with Postgres' row overhead) | |
|---|---|---|
| user | ~200 (the state itself is ~90 bytes of JSON) | 1 million users ≈ 200 MB |
| relation, only while above 0 | ~150 | |
| reply, kept 7 days | ~400 (the answer is ~300 bytes of JSON) | per message with a `message_id` |

The PDF's estimate for storing text instead: 1 million users × 50 messages a day × ~100 bytes = ~5 GB a day.
