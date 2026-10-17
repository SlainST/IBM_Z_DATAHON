# Load test results (LinuxONE)

Machine: s390x, IBM z17 (machine type 9175), NNPA present, 3 vCPU, 7.8 GB RAM, Ubuntu 24.04.
The load generator runs on the same box, so it takes CPU from the API; the numbers are a lower bound.
Raw JSON per run: `bench/results/`.

## 2026-10-17: `/v1/check` with Postgres 16, fallback rules (no models yet)

Every message is one Postgres transaction (sender row and A -> B row locked, decision stored for retries).
5,000 senders, 50 groups, 12 sample texts (half harmful). Settings: `SAFENET_WORKERS=3`, `SAFENET_DB_POOL_SIZE=5`.

| concurrency | msg/s | p50 ms | p95 ms | p99 ms | server p50 ms |
|---:|---:|---:|---:|---:|---:|
| 1 | 323 | 2.99 | 4.10 | 5.09 | 2.51 |
| 4 | 1,072 | 2.96 | 8.75 | 11.93 | 2.00 |
| 8 | 1,144 | 4.09 | 19.79 | 30.16 | 2.72 |

Tuning (10 s runs, concurrency 4 / 8 / 16, msg/s):

| workers | pool 2 | pool 5 | pool 10 |
|---:|---|---|---|
| 2 | 1,161 / 998 / 990 | 1,131 / 779 / 641 | 1,098 / 817 / 619 |
| 3 | 1,092 / 1,474 / 1,197 | 1,608 / 1,202 / 950 | 1,370 / 1,171 / 877 |

3 workers beat 2 (Postgres needs little CPU); a bigger pool doesn't help on 3 vCPU. With 3 workers x 5
connections = 15, far under Postgres' 100. While Developer 1 trains a model, use `SAFENET_WORKERS=2`.
After a run, `psql "$SAFENET_DATABASE_URL" -f bench/cleanup.sql` removes the bench rows from the stats.

## 2026-10-17: old `/v1/moderate` API, lexicon only, no model, no Postgres, 2 workers

| concurrency | msg/s | p50 ms | p95 ms | p99 ms |
|---:|---:|---:|---:|---:|
| 1 | 2,639 | 0.35 | 0.44 | 0.59 |
| 4 | 5,130 | 0.74 | 1.40 | 1.75 |
| 8 | 5,437 | 1.38 | 2.28 | 2.88 |
| 16 | 5,214 | 2.91 | 4.85 | 6.22 |

Server-side time per message (`latency_ms` in the answer): p50 0.06 ms, p99 0.13 ms.

Before installing `httptools`, uvicorn used h11 and every keep-alive request took ~50 ms
(155 msg/s at concurrency 8) from Nagle + delayed ACK. `requirements/server.txt` now includes it.

To redo once models and Postgres are in (latency will change):

    .venv/bin/python bench/load_test.py --key "$KEY" --seconds 30 --concurrency 8 --label "workers=2 pool=5 model1"

Check `cat /proc/loadavg` first: never while a model is training.
