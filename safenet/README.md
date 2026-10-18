# SafeNet

A message security API on IBM LinuxONE. Before a platform (a school app, a game, WhatsApp, YouTube...) delivers
a one-to-one message, it asks SafeNet what the recipient may see: **allow** it, **censor** the profanity,
**hold** it for a moderator, or **block** it, and why. SafeNet keeps hidden points per platform, group and
sender, and per sender → recipient pair, in PostgreSQL; it never stores message text. The design is the team's
`SafeNet_Model_Tasarimi.pdf` (17 Oct 2026).

```
platform adapter (client/)               LinuxONE (s390x, IBM z17)
──────────────────────────               ───────────────────────────────────────────────────────────────
POST /v1/check  ──X-API-Key────────────► uvicorn workers (stateless)
{sender, recipient, group, text}           clean → sentences → Model 1 (harm) ×2 → Model 2 (category)
                                           → phrase rules → identity → colour → decision → hidden points
◄── {"decision": "censor",                 └─► PostgreSQL: users per group, A → B relations, counters
     "recipient_sees": "f*** off", ...}
```

- Every endpoint, field and error: [docs/API.md](docs/API.md); JSON Schemas: [schemas/](schemas/)
- How a message is judged and scored, and the choices the PDF left open: [docs/DECISION_ENGINE.md](docs/DECISION_ENGINE.md)
- What is stored and how one message is written: [docs/STATE.md](docs/STATE.md)
- Measured against the PDF's targets: [docs/RESULTS.md](docs/RESULTS.md)
- The two models, their training and the phrase rules: [models/README.md](models/README.md)
- Running it on the server: [deploy/README.md](deploy/README.md); load tests: [bench/RESULTS.md](bench/RESULTS.md)

## How a message is judged

1. The key tells which platform is asking; its block in `ayarlar.toml` gives the thresholds (profiles
   `sosyal_medya`, `egitim`, `oyun`, `kurumsal`).
2. Listed profanity is found in the text as sent, disguises included (`f*ck`, `sh1t`, `f u c k`, Cyrillic
   look-alikes, `kys`), and starred: `f***`.
3. The message is split into sentences; the worst sentence decides for the whole message. The whole message is
   scored too, so harm spread over mild-looking sentences makes it yellow (never red).
4. Model 1 scores each sentence and the sentence without its listed words ("wordless"): "fuck, I missed the bus"
   is profanity, "fuck you, nobody likes you" is malice. Model 2 names the category.
5. The phrase rules adjust the scores: threats (explicit, and common implicit phrasings like "you'll regret
   coming to school tomorrow"), severe bullying, sexual requests and xenophobia are lifted, a plain insult is capped at yellow, an identity only mentioned ("I'm a proud Muslim") adds nothing.
6. Colour: red (threat, hate, very harmful, profanity in more than 30 % of the words, spam) → block; yellow →
   censor, or hold on the school profile; green → allow, or censor when it has profanity. A quoted threat
   ("he told me ...") is held, so a victim reporting it isn't silenced.
7. Hidden points: listed words, disguises, yellow and red messages and identity attacks add points; a sender is
   warned at 40 and restricted at 70 (social profile); points never fall with time, only with clean messages.
   When A's points towards B reach 40, A's messages stop reaching B, and only B.

## Quick start (any machine)

```bash
pip install -r requirements/dev.txt     # Python 3.12; plus scikit-learn 1.4, numpy, scipy, joblib, pandas
python -m pytest                        # the engine on its fallback rules (model files are not in git)
SAFENET_DEV_KEYS=1 uvicorn safenet.api:app --port 8000
curl -s localhost:8000/v1/check -H 'X-API-Key: dev-demo_sosyal' -H 'content-type: application/json' \
     -d '{"sender_id": "u1", "recipient_id": "u2", "group_id": "7b", "text": "f*ck, I missed the bus"}'
python demo.py --url http://localhost:8000          # with SAFENET_KEY_DEMO_SOSYAL=dev-demo_sosyal set
python -m safenet.settings                          # what each platform is judged by
```

`dev-<platform>` keys work only with `SAFENET_DEV_KEYS=1`, never on the server. Without a database URL the API
keeps points in memory (one worker). The trained models only work on the byte order they were trained on: the
server's (s390x) pair is refused on a laptop and the fallback rules answer, which `/health` shows.

## Layout

```
safenet/
├─ safenet/                  the API
│  ├─ api/                   FastAPI app, X-API-Key → platform, request and response models
│  ├─ engine/                analysis (steps 2-5), decision (colour), points, moderator (one message in, the answer out)
│  ├─ ml/                    models.py (Model 1, Model 2, fallback rules), rules.py (phrase rules, insult cap, identity)
│  ├─ pipeline/              profanity in the original text, sentences, typos, game words, quotes, spam
│  ├─ state/                 MemoryStore and PostgresStore, schema.sql
│  ├─ settings.py            ayarlar.toml through the team's ayarlar.py
│  └─ config.py, ibmz.py     SAFENET_* settings; s390x / machine type / NNPA for /health
├─ temizlik.py, kimlik.py    the team's cleaning (also used in training) and identity analysis
├─ ayarlar.toml, ayarlar.py  profiles, platforms, every threshold and point
├─ kufur_listesi.csv         125 listed words with 1-10 points;  karistirilabilir_kelimeler.csv: 124 look-alikes
├─ veri_hazirla.py ...       the data: merging, labels, near-duplicates, the chat simulation (veri/ is not in git)
├─ train.py, augment.py      training on the server; synthetic sentences for the gaps of the data
├─ measure.py, simulate.py   the PDF's targets; the 1:1 chat simulation (hidden points, recipient protection)
├─ degerlendir.py            the team's evaluation set (degerlendirme_seti.csv): expected decision per platform
├─ demo.py, client/          the demo; the Python client and the WhatsApp and YouTube adapters
├─ models/                   model1.joblib, model2.joblib, model_info.json (trained on the server, not in git)
├─ config/                   api_keys.toml: key hashes (secret, not in git)
├─ deploy/, bench/           LinuxONE scripts and systemd unit; load test
├─ schemas/, scripts/        JSON Schemas; new_api_key.py, export_schemas.py
├─ docs/                     API, decision engine, state, results
└─ tests/                    pytest: engine, API, rules, text, client; model checks on the server
```

## Tools

| Command | Does | Where |
|---|---|---|
| `python -m pytest` | 120+ tests; `tests/test_models.py` also checks the trained pair where it exists | anywhere |
| `python train.py` | trains Model 1 and Model 2 and measures them (~20 min, one CPU) | server |
| `python measure.py` | every target of the PDF's section 9 → `veri/measure_report.json`, `--markdown docs/RESULTS.md` | server |
| `python simulate.py` | the 1:1 chat simulation: who is restricted, does a bullied recipient stop getting the bully's messages | anywhere |
| `python degerlendir.py --hatalar` | the team's evaluation set: expected vs given decision, per platform | anywhere |
| `python demo.py` | the five-part demo through the real API | your PC + tunnel |
| `python client/whatsapp_chat.py chat.txt` | replays an exported WhatsApp chat | your PC + tunnel |
| `python client/youtube_comments.py comments.json` | runs a video's comments | your PC + tunnel |
| `python scripts/new_api_key.py demo_okul` | a platform's key, printed once; only its hash is stored | server |

`measure.py` and `train.py` need `veri/` (made by `veri_hazirla.py` from the datasets) and, for the real numbers,
the models trained on that machine.

## Who owns what

| | Files | Owner |
|---|---|---|
| Models and cleaning | `train.py`, `augment.py`, `models/`, `safenet/ml/`, `temizlik.py`, `measure.py` | Developer 1 |
| Rules, lists, identity, tests | `ayarlar.toml`, `*.csv` lists, `kimlik.py`, `degerlendirme_seti.csv`, `tests/`, `docs/DECISION_ENGINE.md` | Developer 2 |
| LinuxONE, adapters, demo | `deploy/`, `requirements/`, `bench/`, `client/`, `demo.py` | Developer 3 |

`ayarlar.toml` has one owner (Developer 2) and the API contract (`docs/API.md`, `schemas/`) changes only when all
three agree. Every change goes in with the tests green.

## Known limits

- English only, like the training data.
- Implicit threats beyond the common phrasings the rules know ("i know your address and i am coming over
  tonight") are missed: a word-based model knows the phrasings it has seen.
- Long texts: the worst sentence decides, so a long thread with one bad sentence is blocked.
- Only one-to-one messages are in scope (PDF section 1); without `recipient_id` only the sender is scored.
  Group and live-stream settings (`[kanal.*]`) are in `ayarlar.toml` for the next stage.
