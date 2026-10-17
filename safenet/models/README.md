# Models

The API loads two scikit-learn pipelines from this folder. They are trained on the LinuxONE server with
`train.py` and are not in git (`*.joblib`). Without them the API answers with the fallback rules in
`safenet/ml/models.py`, and `/health` says `"model1": "fallback"`.

| File | Answers | Input | Output |
|---|---|---|---|
| `model1.joblib` | Is this sentence harmful? | one sentence, as `temizlik.temizle()` returns it | `predict_proba(texts)[:, 1]`, `classes_ == [0, 1]` |
| `model2.joblib` | Which category? | the same | `predict(texts)`: `insult`, `gender`, `religion`, `race`, `sexual`, `threat` |

Both are plain `Pipeline`s saved with `joblib.dump(pipeline)`. The API calls Model 1 once per message, on every
sentence and its wordless version (listed profanity removed), and Model 2 only for sentences with harm or
wordless harm of at least 0.25.

**Explicit threats** (`EXPLICIT_THREATS` in `safenet/ml/models.py`): a sentence matching one of these patterns
("i'll break your legs", "you're dead meat", "i hope you die", "kys"...) is a threat with harm of at least 0.95,
whatever the models say. The models saw only ~480 real threats and miss phrasings they never saw. On the training
split, 91 % of the messages the patterns match are labelled harmful, and they match 2 in 10,000 harmless ones.

## Train

On the server, in your own folder with a copy of the repo and `veri/` (made by `veri_hazirla.py`, not in git):

```bash
nice -n 10 .venv/bin/python train.py               # ~15 min on one CPU: models/ + veri/training_report.json
.venv/bin/python -m pytest tests/test_models.py    # the new pair passes its checks
.venv/bin/python train.py --evaluate               # measure models/ again without training (after a rule change)
```

Train on the server only: a file saved with another scikit-learn / numpy than the API's (1.4.1.post1 / 1.26.4)
may not load. Packages: `requirements/train.txt`.

## How

- **Features**: `HashingVectorizer`, words (1-2) and characters within words (2-5), binary, l2-normalized;
  2^20 buckets per branch for Model 1, 2^19 for Model 2. No vocabulary and no TF-IDF: the idf step took ~40 ms
  per call for the same PR-AUC; now one call takes ~0.5 ms.
- **Classifier**: `LogisticRegression` (liblinear). C chosen on validation: Model 1 C=8 (PR-AUC), Model 2 C=128
  (macro F1, one-vs-rest).
- **No leakage**: validation is 20 % of the training split by `grup_id`, so near-duplicate messages stay on one
  side; the test split is used once, at the end; YouTube comments are never trained on.
- **Model 2 weights**: rows whose category came from a keyword rule or a template count half; every category
  gets the same total weight (threat has 481 rows, insult 13 thousand).
- **Synthetic sentences** (`augment.py`, training rows only):
  - 5,448 neutral sentences with identity words. In the data 91 % of the messages with "gay" are harmful
    (88 % "muslims", 78 % "woman"; 22 % overall), so the first model flagged "my best friend is gay".
  - 900 threats ("if you tell anyone i'll snap your wrist") and 900 harmless sentences in the same frames
    ("after school i'll help you with your homework"); without the second set a trial model blocked
    "see you tomorrow".
  - Checked on held-out sentences with other templates and words (`augment.HELDOUT_*`, the PDF example).

## Results (v2, trained and measured on the LinuxONE server, 18 Oct 2026)

| | v2 (this) | v1 (no synthetic) | Fallback rules |
|---|---|---|---|
| Test: Model 1 ROC-AUC / F1 at 0.5 | 0.974 / 0.851 | 0.974 / 0.851 | |
| Test, API path: worst-sentence ROC-AUC | 0.967 | 0.967 | 0.752 |
| Test, `demo_sosyal`: harmful not allowed | 87.1 % | 87.0 % | 54.0 % |
| Test, `demo_sosyal`: harmless blocked | 1.2 % | 1.3 % | 0.3 % |
| Model 2 macro F1 (insult .92, gender .94, religion .97, race .98, sexual .71, threat .69) | 0.867 | 0.862 | |
| Held-out neutral identity sentences: mean harm (max of 15 identities) | 0.14 (0.41) | 0.18 (0.54) | |
| PDF example ("I'll f*cking break your legs") | block, threat | censor | block, threat |
| Held-out threats blocked / look-alikes blocked | 4 of 8 / 0 of 7 | | |
| YouTube (external): harmless blocked | 24.8 % | 24.6 % | 7.1 % |

Test = 37,588 messages (API path: 12,000 of them). Speed on the server: 0.5 ms per model call, 1.35 ms per
message for the whole analysis. ROC-AUC by source: cyberbullying 0.97, wikipedia 0.97, kaggle 0.85, twitter 0.83.

## Threshold proposals (for `ayarlar.toml`)

Measured on validation through the API's path; block thresholds aim at 95 % precision.

| Setting (`sosyal_medya`) | Now | Measured | Proposal |
|---|---|---|---|
| `sari_esigi` | 0.50 | 0.41 (best F1) | keep 0.50; `egitim` already uses 0.40 |
| `cok_kotu_esigi` | 0.85 | 0.81 | keep 0.85 (95.8 % precision) |
| `nefret_esigi` | 0.75 | 0.66 | keep 0.75 (YouTube blocks too much already) |
| `tehdit_esigi` | 0.60 | 0.45 (few messages) | keep 0.60; explicit threats get 0.95 anyway |

## Known limits

- **Implicit threats** ("you are going to regret coming to school tomorrow", "keep talking and see what
  happens") are missed: a word-based model only knows phrasings it has seen.
- **Long texts**: YouTube rows are whole comment threads (median 10 sentences); the worst sentence decides, so
  24.8 % of the harmless ones are blocked (9.5 % of the ones with 1-3 sentences, 38.9 % with 11 or more).
- **Borderline hate without slurs**: "go back to your country" scores 0.47 (yellow on `egitim`, allowed on
  `sosyal_medya`).
- **English only**, like the training data.

## Deploy

```bash
cp models/model1.joblib models/model2.joblib ~/IBM_Z_DATAHON/safenet/models/
systemctl --user restart safenet-api
curl -s localhost:8000/health        # "model1": "loaded", "model2": "loaded"
```
