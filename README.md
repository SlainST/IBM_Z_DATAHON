# IBM_Z_DATAHON: SafeNet

Real-time blocking of bad messages: an API on IBM LinuxONE that a school app, a game chat or a social
network asks before delivering each message. In about a millisecond it answers what the recipient may see
(`allow`, `censor` with the profanity starred, `hold` for a moderator, `block`), and it keeps hidden points
per sender, so a repeat offender is warned and then restricted while a one-off swear word is only starred.
English messages only. The code is in `safenet/`.

## How it decides

Each sentence is scored by Model 1 (harm, with and without its listed words) and, when harmful, Model 2
(insult, gender, religion, race, sexual, threat); identity attacks, threats in quotes, disguised profanity
(`f*ck`, `sh1t`, `f u c k`), likely typos, game language and spam have their own rules. The worst sentence
decides. Every threshold and point is per platform profile in `safenet/ayarlar.toml` (school, game, social,
corporate), so a new platform is a new block, not new code.

| Document | What |
|---|---|
| [`docs/API.md`](safenet/docs/API.md) | Endpoints, fields, errors, a platform adapter |
| [`docs/DECISION_ENGINE.md`](safenet/docs/DECISION_ENGINE.md) | The rules, step by step, and the 16 choices the design PDF left open |
| [`docs/STATE.md`](safenet/docs/STATE.md) | What Postgres keeps (never message text) and what happens when it is down |
| [`models/README.md`](safenet/models/README.md) | Training the two models, results, threshold proposals |
| [`docs/EVALUATION.md`](safenet/docs/EVALUATION.md) | 312 expected decisions: results with the rules and the models, what the models miss |
| [`schemas/`](safenet/schemas) | JSON Schema of every request and answer |

## Run it on a laptop

```bash
cd safenet
python -m venv .venv
.venv/bin/python -m pip install -r requirements/dev.txt     # Windows: .venv\Scripts\python ...
SAFENET_DEV_KEYS=1 .venv/bin/python -m uvicorn safenet.api:app --port 8000
```

On Windows PowerShell: `$env:SAFENET_DEV_KEYS="1"; .venv\Scripts\python -m uvicorn safenet.api:app --port 8000`.
Then open <http://127.0.0.1:8000/docs> (its "Try it out" holds the design PDF's example), or:

```bash
curl -s localhost:8000/v1/check -H "X-API-Key: dev-demo_okul" -H "Content-Type: application/json" \
     -d '{"sender_id": "u1", "recipient_id": "u2", "text": "you are an idiot"}'
```

`dev-<platform>` keys work only with `SAFENET_DEV_KEYS=1`. Without `SAFENET_DATABASE_URL` the points live in
memory; without `models/*.joblib` the fallback rules stand in for the models (`/health` says which).

## Check it

```bash
cd safenet
python -m pytest            # engine, rules, HTTP layer and answer schemas; tests/test_models.py with models
python degerlendir.py       # 104 English messages x 3 demo platforms against the expected decisions
```

## Deploy

On the LinuxONE server: `safenet/deploy/linuxone/` (server and Postgres setup, `run_api.sh`, the systemd
unit) and the "Deploy" section of `models/README.md`. The models are trained there with `train.py`.
