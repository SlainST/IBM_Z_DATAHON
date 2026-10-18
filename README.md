# IBM_Z_DATAHON

SafeNet: a real-time API that decides, per message, what the recipient may see (allow, censor, hold or
block) and keeps hidden points per sender. It runs on IBM LinuxONE (s390x, z17) with Postgres.

Everything is in [`safenet/`](safenet):

| Read | For |
|---|---|
| [`docs/API.md`](safenet/docs/API.md), [`schemas/`](safenet/schemas) | What a platform sends and gets back (the API contract) |
| [`docs/DECISION_ENGINE.md`](safenet/docs/DECISION_ENGINE.md) | How a message is judged and a sender scored, and the open choices |
| [`docs/STATE.md`](safenet/docs/STATE.md) | What Postgres keeps (never the text) |
| [`models/README.md`](safenet/models/README.md) | Training and measuring the two models |
| [`ayarlar.toml`](safenet/ayarlar.toml) | Every threshold and point, per profile and platform |
| [`LINUXONE_SERVER_GUIDE.md`](safenet/LINUXONE_SERVER_GUIDE.md), [`deploy/linuxone/`](safenet/deploy/linuxone) | Connecting to and running on the server |
| [`bench/RESULTS.md`](safenet/bench/RESULTS.md) | Load test results on LinuxONE |

## Run it locally

```bash
cd safenet
python3 -m venv .venv && .venv/bin/pip install -r requirements/dev.txt numpy scipy scikit-learn joblib
.venv/bin/python -m pytest                       # engine, API and models (model tests skip without models/)
.venv/bin/python degerlendir.py                  # the evaluation set: expected vs. given decisions
SAFENET_DEV_KEYS=1 .venv/bin/python -m uvicorn safenet.api:app --port 8000
curl -s localhost:8000/v1/check -H 'X-API-Key: dev-demo_sosyal' -H 'content-type: application/json' \
     -d '{"sender_id": "u1", "recipient_id": "u2", "text": "see you tomorrow"}'
```

Without `SAFENET_DATABASE_URL` the points live in memory; without `models/*.joblib` the fallback rules stand
in for the models. On the server numpy, scipy and scikit-learn come from the OS (`deploy/linuxone/setup_server.sh`).

Never commit `deploy/linuxone/safenet.env`, `config/api_keys.toml`, `deploy/docker/.env`, `*.pem` or an API key.
