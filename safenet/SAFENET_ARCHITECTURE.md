# SafeNet: Technical Architecture (v0.2)

> **Historical: the first plan, before the team's design (`SafeNet_Model_Tasarimi.pdf`).** The transformer
> cascade, Redis, the `/v1/moderate` endpoint and the age profiles below were not built. What SafeNet is now:
> [README.md](README.md), [docs/DECISION_ENGINE.md](docs/DECISION_ENGINE.md), [docs/API.md](docs/API.md).
> Kept as the record of the ideas the team weighed.

Real-time text moderation API on IBM LinuxONE (s390x). Target: **p99 < 30 ms** per message
on the synchronous path.

## 1. Core idea: censor the words, block the intent

Our model keeps two decisions apart:

| Question | Answered by | Action |
|---|---|---|
| *Does the message contain a bad word?* (lexical) | Filters (span level) | **MASK** only those spans: `you ####` |
| *Is the sender trying to hurt someone?* (intent) | Harm score (message + context level) | **BLOCK** + strike |

A typo that turns into a bad word ("bigger" mistyped as a slur) or friendly swearing
("lol this game is f***ing hard") gets **masked, not blocked**. Repeated, targeted abuse
("you are worthless, kys", aimed at the same player again and again) is **blocked**, even
when no listed word appears.

The **harm score** (0–100 %) is not shown to chat users. It is returned to the platform
in the API response, for its own logic and dashboards.

## 2. Pipeline

```
 message ─► L0 Normalize ─► L1 Lexical filter ─► L2 Fast ML ─┬─► Harm combiner ─► Policy ─► response
            (skeleton,       (Aho-Corasick,       (TF-IDF +   │   (calibrated       (profile:
             leet, TR fold,   allowlist, fuzzy,    LogReg)    │    logistic over     under13/teen/
             homoglyphs)      PII regex)                      │    all signals)      adult)
                                                              │
                                   uncertain band only ──► L3 Transformer (distilled, NNPA/int8)
                                                              │
                         Context store (Redis): last N msgs per sender→target, strike EWMA
```

### L0: Normalization (~20 µs)
NFKC normalization, removal of zero-width characters, Turkish folding (ı→i, ş→s, …), mapping of
Cyrillic look-alikes, leetspeak decoding (`@→a, 0→o, 3→e`), collapsing repeated letters,
and joining spaced-out letters (`s a l a k`). Each original span is mapped to its normalized
token, so masking stays exact.

### L1: Lexical filter (~50 µs)
- **Aho-Corasick** automaton over normalized tokens (`pyahocorasick`; it compiles on s390x,
  and a pure-Python trie is the fallback).
- Lexicon entries carry: `term, severity(1–3), match_mode(exact|prefix|embedded), lang`.
- **False-positive guard (Scunthorpe problem):**
  - Embedded matches happen only for terms of 5 or more letters, and never inside allowlisted words.
  - **Allowlist** = a frequency dictionary of valid TR/EN words (`wordfreq` lists, exported
    to a static file). If a token is a real word (`bigger`, `Scunthorpe`, `assassin`), the
    filter does not touch it.
- **Fuzzy matching for typos and evasion:** edit distance ≤ 1 (Damerau) against
  severity-3 terms, **only** when the token is not in the allowlist. A fuzzy hit sets
  `typo_suspect=true`, which lowers its weight in the harm combiner.
- **PII:** regex for phone (TR +90 5xx), e-mail, URLs, social handles (discord/insta/snap…).
  It is masked for under13 and teen.

### L2: Fast ML (~0.3 ms)
- `TfidfVectorizer(analyzer="char_wb", ngram_range=(2,5), sublinear_tf=True, max_features=300k)`
  + `LogisticRegression(class_weight="balanced")`, multi-label (one-vs-rest):
  `toxic, insult, threat, identity_hate, sexual, self_harm`.
- Trained on normalized text. It runs on CPU in scikit-learn (already in the server venv).
- Probabilities are calibrated with `CalibratedClassifierCV(method="isotonic")`, so the
  numbers really are probabilities and can feed the combiner.

### L3: Transformer, cascade only (~8–15 ms distilled, int8)
Called **only** when L2 is uncertain (`0.30 ≤ p_toxic ≤ 0.85`), or when there is a lexical hit
that is aimed at a person. That is expected to be about 5–10 % of traffic.

Candidate open-source Hugging Face models (check each model card for license and languages):

| Role | Model | Notes |
|---|---|---|
| Multilingual toxicity (incl. Turkish) | `unitary/multilingual-toxic-xlm-roberta` (Detoxify) | Apache-2.0, XLM-R base, teacher |
| Multilingual toxicity | `textdetox/xlmr-large-toxicity-classifier` | Large, teacher only |
| Turkish base for fine-tuning | `dbmdz/bert-base-turkish-cased` (BERTurk) | Fine-tune on OffensEval-2020 TR |
| English toxicity | `unitary/toxic-bert` | Jigsaw labels |
| Student (served) | `distilbert-base-multilingual-cased` or `dbmdz/distilbert-base-turkish-cased` | Distilled from the teachers |

Serving: we fine-tune and distill a student model, export it to ONNX, then use one of two paths:
- **If the machine is z16/LinuxONE 4 with NNPA:** compile with **IBM Z Deep Learning Compiler (zDLC)**
  into a `.so` that runs on the Telum on-chip AI accelerator. This is the main IBM Z showcase.
- **Otherwise:** PyTorch CPU with dynamic int8 quantization (IBM Z Accelerated for PyTorch
  container, or the s390x PyTorch wheels), `torch.set_num_threads(1)` per worker.
- Max sequence length is 64 tokens (chat messages are short), with micro-batching of up to 2 ms
  or 16 messages.

**Deadline rule (real-time guarantee):** L3 has a **15 ms budget**. If it misses the budget,
we answer with the L1/L2 decision (mask or allow), deliver the message, and queue L3
asynchronously (Redis Stream). If the late result says *block*, it sends a `retract` webhook
to the platform and records a strike. Chat never waits on the slow path.

### Harm combiner (~5 µs)
Logistic regression over a small feature vector, trained on labeled conversations:

```
harm = σ( w1·p_toxic_L2 + w2·p_toxic_L3 + w3·max_severity + w4·targeted
        + w5·p_threat + w6·context_repeat + w7·sender_strike_ewma
        − w8·typo_suspect − w9·self_directed_profanity + b )
```

- `targeted`: second-person pronouns (sen/sana/seni/you/your/ur), an @mention, or a reply-to.
- `context_repeat`: how many toxic messages the same sender sent to the same target in the
  last 10 messages or 5 minutes (Redis sorted set). Cyberbullying is a **pattern**, not one message.
- `sender_strike_ewma`: decaying reputation score.
- The output is a calibrated `harm_score` from 0 to 1, returned as `harm_confidence` (percent).

### Policy (per profile)

| Profile | Mask lexical ≥ | Block if harm ≥ | Review band | Mask PII |
|---|---|---|---|---|
| under13 | sev 1 | 0.60 | 0.40–0.60 | yes |
| teen | sev 1 | 0.75 | 0.55–0.75 | yes |
| adult | sev 2 | 0.90 | 0.70–0.90 | no |

Block thresholds are tuned on a validation set for **precision ≥ 0.95 on BLOCK**, because a
wrongful block hurts users more than a missed mask. Three blocks in 5 minutes give a 10-minute
mute (escalating).

## 3. API contract

`POST /v1/moderate`
```json
{ "text": "sen tam bir s@l@ksın", "user_id": "u1", "target_id": "u2",
  "conversation_id": "room42", "profile": "teen" }
```
```json
{ "action": "mask",
  "text": "sen tam bir ########",
  "harm_confidence": 0.41,
  "categories": ["insult"],
  "spans": [{"start": 12, "end": 20, "type": "insult", "severity": 2, "typo_suspect": false}],
  "layers": ["L0", "L1", "L2"],
  "review": false,
  "muted_until": null,
  "latency_ms": 0.62,
  "model_version": "l2-2026.10.17/l3-none" }
```
Other endpoints:
- `POST /v1/moderate/batch`: up to 500 messages.
- `WS /v1/stream`: a persistent socket for game servers.
- `POST /v1/feedback`: appeals and moderator labels, which feed retraining.
- `GET /health`, `GET /metrics` (Prometheus).

## 4. Data

| Dataset | Lang | Use |
|---|---|---|
| OffensEval-2020 Turkish (Çöltekin, ~35k tweets) | TR | L2 + BERTurk fine-tune |
| Jigsaw Toxic Comment Classification | EN | Multi-label L2/L3 |
| Jigsaw Multilingual Toxic Comment (has TR) | multi | Validation and distillation |
| Own labeled chat conversations (targeted vs. not) | TR/EN | Harm combiner |

Training happens **on the LinuxONE server** (no x86/s390x mismatch). Artifacts are versioned
in `models/` (`l2-YYYY.MM.DD.joblib`, `l3-*.so`). A new model first runs in **shadow mode**
(it scores traffic but does not act) before it is promoted.

## 5. Deployment on LinuxONE

```
           ssh tunnel / open port
client ──► nginx (TLS, rate limit, 1 MB body cap)
              │
              ▼
        uvicorn × 2 workers (FastAPI, L0–L2 in process)  ──► Redis (context, strikes, streams, cache)
              │                                                   ▲
              └─ L3 inference worker (1 process, NNPA or int8) ───┘
```
- `docker-compose.yml`: `api`, `l3-worker`, `redis`, `nginx`. All images are built **on the server**.
- 3 vCPU budget: 2 for the API workers, 1 shared by L3 and Redis.
- Cache: hash of the normalized message → decision (TTL 60 s). Spam and copy-paste raids
  cost nothing.

## 6. Libraries (s390x notes)

| Use | Library | s390x |
|---|---|---|
| API | fastapi, pydantic v2, uvicorn (plain) | OK (pure Python / in venv) |
| ML | scikit-learn, numpy, scipy, joblib | OK (already in venv) |
| Matching | pyahocorasick, rapidfuzz | Compiles from source; fallback to pure Python |
| Context | redis-py, Redis 7 image | OK, multi-arch image |
| Transformer train | transformers, datasets, torch | Torch: IBM Z Accelerated for PyTorch container |
| Transformer serve | onnx + IBM zDLC (NNPA) / torch int8 | zDLC from icr.io/ibmz |
| Metrics | prometheus-client | OK |
| Avoid | uvloop, httptools, orjson, onnxruntime | No official s390x wheels or heavy builds |

## 7. Repository structure

```
safenet/
├─ safenet/
│  ├─ api/            app.py, schemas.py, ws.py, deps.py
│  ├─ pipeline/       normalize.py, lexicon.py, fuzzy.py, allowlist.py, pii.py
│  ├─ models/         fast_ml.py (L2), transformer.py (L3 client), combiner.py
│  ├─ context/        store.py (Redis), strikes.py
│  ├─ policy.py, moderator.py, config.py, metrics.py
├─ data/
│  ├─ lexicon/{tr,en}.tsv, allowlist/{tr,en}.txt
│  └─ datasets/       (download scripts only; no raw data in git)
├─ training/          train_l2.py, finetune_l3.py, distill.py, export_onnx.py,
│                     compile_zdlc.sh, train_combiner.py, eval.py
├─ serving/l3_worker.py
├─ deploy/            Dockerfile.api, Dockerfile.l3, docker-compose.yml, nginx.conf
├─ bench/             load_test.py (latency p50/p95/p99, msgs/s)
└─ tests/             unit (normalize, lexicon, false positives), API, policy tables
```

## 8. Open checks on the server
- `grep -m1 -o nnpa /proc/cpuinfo; grep 'Type:' /proc/sysinfo`: is this a z16 (3931/3932) with NNPA? This decides the L3 serving path.
- `free -g`: the RAM decides whether an XLM-R teacher can be trained on the box or must be trained elsewhere.
- Which inbound ports are open (otherwise demo through an SSH tunnel).
