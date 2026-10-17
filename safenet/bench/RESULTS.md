# Load test results (LinuxONE)

Machine: s390x, IBM z17 (machine type 9175), NNPA present, 3 vCPU, 7.8 GB RAM, Ubuntu 24.04.
The load generator runs on the same box, so it takes CPU from the API; the numbers are a lower bound.
Raw JSON per run: `bench/results/`.

## 2026-10-17: current `/v1/moderate` API, lexicon only, no model, no Postgres, 2 workers

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
