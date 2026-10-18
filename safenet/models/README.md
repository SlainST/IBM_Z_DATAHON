# Models

The API loads two scikit-learn pipelines from this folder, trained on the LinuxONE server by `train.py`, and puts
the phrase rules of `safenet/ml/rules.py` on top of their scores. The `.joblib` files are not in git; without them
the API answers with the fallback rules in `safenet/ml/models.py` and `/health` says `"model1": "fallback"`.

| File | Answers | Input | Output |
|---|---|---|---|
| `model1.joblib` | Is this sentence harmful? | one sentence, as `temizlik.temizle()` returns it | `predict_proba(texts)[:, 1]`, `classes_ == [0, 1]` |
| `model2.joblib` | Which category? | the same | `predict(texts)`: `insult`, `gender`, `religion`, `race`, `sexual`, `threat` |
| `model_info.json` | When, where and with what they were trained | | `byteorder`, `machine`, `sklearn`, `trained`, C values, synthetic rows |

Both are plain `Pipeline`s saved with `joblib.dump(pipeline)`. The API calls Model 1 once per message, on every
sentence and its wordless version (listed profanity removed), and Model 2 only for sentences with harm or
wordless harm of at least 0.25.

**Byte order.** The features are hashed with MurmurHash3, which reads its input in the machine's byte order: the
same word lands in another column on big-endian s390x than on a little-endian laptop (checked: "idiot" is column
245,042 on the server, 350,128 on x86). A pair trained on the server scores nonsense on a laptop and the other way
round, silently. `train.py` writes the byte order into `model_info.json` and the API refuses a pair from the other
byte order (the fallback rules answer and the log says why). Train, test and measure on the server.

## Train

On the server, in your own folder with a copy of the repository and `veri/` (made by `veri_hazirla.py`, not in git):

```bash
nice -n 10 .venv/bin/python train.py               # ~20 min on one CPU: models/ + veri/training_report.json
.venv/bin/python -m pytest tests/test_models.py    # the new pair passes its checks
nice -n 10 .venv/bin/python measure.py             # the PDF's targets, through the API's own code
.venv/bin/python train.py --evaluate               # measure models/ again without training
```

A file saved with another scikit-learn / numpy than the API's (1.4.1.post1 / 1.26.4) may not load. Packages:
`requirements/train.txt`. Deploying a new pair: `../deploy/README.md`.

## How

- **Features**: `HashingVectorizer`, words (1-2) and characters within words (2-5), binary, l2-normalized;
  2^20 buckets per branch for Model 1, 2^19 for Model 2. No vocabulary and no TF-IDF: the idf step took ~40 ms
  per call for the same PR-AUC; one call takes ~0.5 ms.
- **Classifier**: `LogisticRegression` (liblinear). C chosen on validation: Model 1 by PR-AUC, Model 2 by macro
  F1 (one-vs-rest).
- **No leakage**: validation is 20 % of the training split by `grup_id`, so near-duplicate messages stay on one
  side; the test split is used once, at the end; YouTube comments, the team's evaluation set and the 124 example
  sentences of `karistirilabilir_kelimeler.csv` are never trained on.
- **Model 2 weights**: rows whose category came from a keyword rule or a template count half; every category
  gets the same total weight (threat has 481 rows, insult 13 thousand).
- **Synthetic sentences** (`augment.py`, training rows only, 12,462 in v3, 2,364 of them harmful): neutral
  sentences with identity words the data made look harmful (91 % of the messages with "gay" are harmful there),
  threats and as many harmless sentences in the same frames, swearing at things versus the same words aimed at
  the reader, victims' accounts versus insults aimed at the reader, compound identities in everyday contexts,
  and look-alike words ("snigger", "tennis balls", "our school started an anti bullying club"). Each family has
  held-out sentences with other templates and words.

## The phrase rules (`safenet/ml/rules.py`)

A probability is not a severity, and some kinds of harm are too rare in the data for the models. On top of the
scores:

| Rule | Effect | Training split: precision of matches | Harmless messages it fires on |
|---|---|---|---|
| Explicit threats ("i'll break your legs", "you're dead meat", "i hope you die") | harm ≥ 0.95, threat | 93.6 % (233 messages) | 1.3 in 10,000 |
| Self-harm encouragement ("kys", "you should just die") | harm ≥ 0.95, threat | 96.2 % (80) | 0.3 in 10,000 |
| Blackmail ("... or i'll post your pics", "... or i'll tell everyone") | harm ≥ 0.95, threat | none in the data | |
| Severe bullying ("nobody likes you", "you're worthless", "everyone would be happier if you disappeared") | harm ≥ 0.92, insult | 81.6 % (38; most of the rest are mislabelled bullying) | 0.6 in 10,000 |
| Sexual requests ("send nudes", "send me a pic of you in your underwear") | harm ≥ 0.92, sexual | none in the training split | |
| Xenophobia ("go back to your country") and dehumanizing claims ("all immigrants are criminals") | harm ≥ 0.92, race / religion / gender | 100 % (2) and 89.3 % (28) | 0.3 in 10,000 |
| A plain insult: Model 2 says insult, no rule, no identity attacked | harm ≤ 0.72 | | |
| An identity only mentioned (no slur, label, claim about the group or hostile word) | scored again without the identity words; the lower score stays | | |

Negations ("not all muslims are terrorists", "i will never hurt you") don't match, and a sentence the sender only
reports ("she told me ...") keeps only the threat floors. The hostile words that keep an identity's part in the
score were picked by hand from the words that most separate harmful from harmless identity messages in the
training split (log-odds); the datasets' topic words ("sexist", "jokes", "trump") were left out.

## Results (v3, trained and measured on the LinuxONE server, 18 Oct 2026)

| | v3 (this) | v2 |
|---|---|---|
| Test, Model 1: ROC-AUC / PR-AUC / F1 at 0.5 | 0.974 / 0.934 / 0.851 | 0.974 / 0.934 / 0.851 |
| Test, Model 1 ROC-AUC by source: cyberbullying, wikipedia, kaggle, twitter | 0.97, 0.97, 0.86, 0.83 | the same |
| Model 2 macro F1 (insult .92, gender .94, religion .97, race .98, sexual .71, threat .69) | 0.867 | 0.867 |
| Held-out neutral identity sentences: mean harm (max of 15 identities) | 0.13 (0.40) | 0.14 (0.41) |
| Held-out threats blocked / look-alikes blocked | 4 of 8 / 0 of 7 | 4 of 8 / 0 of 7 |
| Held-out swearing at things, victims, identities in context: yellow or red | 0 of 9 | |
| Held-out insults aimed at the reader: yellow or red | 5 of 5 | |

Test = 37,588 messages, never trained on. The synthetic families leave the test metrics unchanged and move the
held-out sentences and the team's evaluation set (99.4 % of its decisions with the rules, 97.8 % with v2). Every
target of the design, through the API's own code, with v2, v3 and the fallback rules side by side:
[`../docs/RESULTS.md`](../docs/RESULTS.md). Speed on the server: ~2 ms per message for the whole analysis
(p99 7.7 ms), ~0.5 ms per model call.

The ROC-AUC of the API's harm score (0.959 on the test split, through the API's path) is below Model 1's own
(0.974) by design: the insult cap puts every plain insult at 0.72, which costs ranking resolution and buys the
severity the decisions need.

## Threshold proposals (for `ayarlar.toml`, Developer 2)

Measured on the test split through the API's path, `demo_sosyal`, v3 with the rules:

| `sari_esigi` | harmful caught | harmless held or blocked | harmless censored | harmless yellow or red |
|---|---|---|---|---|
| 0.50 (now) | 84.0 % | 0.61 % | 4.7 % | 3.7 % |
| **0.45** | **85.0 %** | 0.61 % | 5.1 % | 4.3 % |
| 0.42 (best F1 on validation) | 85.8 % | 0.61 % | 5.4 % | 4.6 % |
| 0.40 (`egitim` now) | 86.3 % | 0.61 % | 5.6 % | 4.9 % |

Proposal: `[varsayilan.mesaj] sari_esigi = 0.45`. It meets the design's 85 % with no more messages held or
blocked; yellow on `sosyal_medya` is a censored delivery plus a warning suggestion. The other thresholds stay:
with the rules the scores have bands by design (threats ≥ 0.95, severe ≥ 0.92, plain insults ≤ 0.72), so
`cok_kotu_esigi` 0.85, `nefret_esigi` 0.75 and `tehdit_esigi` 0.60 sit where they should; the validation
"proposals" `train.py` prints (0.73, 0.55, 0.96) only mirror those bands.

## Known limits

- **Implicit threats** ("you are going to regret coming to school tomorrow", "keep talking and see what
  happens") are missed: a word-based model knows the phrasings it has seen, the rules the explicit ones.
- **Long texts**: YouTube rows are whole comment threads (median 10 sentences) and the worst sentence decides, so
  ~17 % of the harmless ones are blocked on `demo_sosyal`.
- **The school profile** (`sari_esigi` 0.40, yellow is held) holds some innocent double meanings ("The vacuum will
  suck up the dust.", "The monkey climbed the tree.") and swearing at nothing ("holy shit, that was insane").
- **Subtle prejudice** without hostile words ("call me racist but i don't want them here") can score low.
- **English only**, like the training data.

## Deploy

```bash
cp models/model1.joblib models/model2.joblib models/model_info.json ~/IBM_Z_DATAHON/safenet/models/
systemctl --user restart safenet-api
curl -s localhost:8000/health        # "model1": "loaded", "model_version": {"trained": ...}
```
