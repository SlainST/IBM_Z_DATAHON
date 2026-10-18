# Results

SafeNet measured against the targets of the team's design (`SafeNet_Model_Tasarimi.pdf`, section 9), through the
code the API runs, on the LinuxONE server (s390x, IBM z17), 18 Oct 2026, with the v4 models, the phrase rules,
the whole-message score and the yellow thresholds tuned on the validation split (`sari_esigi` 0.46, `egitim` 0.44). Nothing measured here was trained on: the test split (37,588 messages), YouTube (3,459
comment threads), the 124 innocent example sentences of `karistirilabilir_kelimeler.csv`, the 70 gray-zone
messages, the 1:1 simulation (40 conversations, 80 users) and the team's evaluation set (104 messages × 3
platforms). Every message is judged as the first message of a new sender; the simulation measures the hidden points.

| Target (PDF section 9) | Measured | Goal | Met |
|---|---|---|---|
| Harmful messages caught (test split, `demo_sosyal`) | 86.7 % | ≥ 85 % | yes |
| False alarms: harmless messages held or blocked (`demo_sosyal`) | 0.6 % | ≤ 5 % | yes |
| Per source: harmful caught / false alarms | cyberbullying 91 % / 1.8 %, Kaggle 82 % / 3.7 %, Twitter 59 % / 3.8 %, Wikipedia 83 % / 0.3 % | reported | |
| Unseen platform, YouTube: harmful caught / false alarms | 86.1 % / 17.2 % | reported | |
| Innocent sentences blocked (duck, Muslim, bullied, Scunthorpe...) | 0 of 124 on every platform | none | yes |
| Gray zone (conflicting labels) in yellow | 24 % (green 67 %, red 9 %) | most | no |
| Category accuracy, human labels (Model 2) | 96.4 % | ≥ 75 % | yes |
| Time per message, whole analysis on one core (p50 / p99) | 2.3 / 8.1 ms | < 10 ms | yes |
| 1:1 simulation: restricted, of the users who should be (`demo_sosyal`) | 89 % (24 of 27) | ≥ 90 % | no |
| 1:1 simulation: restricted, of the others | 11 %, 0 % by harmless messages alone | ≤ 5 % | see below |
| Bullying conversations where the victim stops getting the bully's messages | 6 of 6 | every one | yes |
| The team's evaluation set: expected decision given | 310 of 312 (dev part 183 of 183, test part 127 of 129) | reported | |

Per platform on the test split (harmful caught / harmless held or blocked / harmless censored):
`demo_sosyal` 86.7 % / 0.6 % / 5.6 %, `demo_okul` 87.1 % / 5.2 % / 1.3 %, `demo_oyun` 83.8 % / 0.6 % / 4.2 %.
1:1 simulation (restricted of those who should be / of the others, by harmless messages alone / bullying
conversations protected): `demo_sosyal` 89 % / 11 %, 0 % / 6 of 6, `demo_okul` 93 % / 19 %, 2 % / 6 of 6,
`demo_oyun` 74 % / 6 %, 0 % / 6 of 6.

## What changed today

Earlier today v3 caught 84.0 % on `demo_sosyal` and the gray zone was 19 % yellow. Two things moved them, measured
apart on the same test split:

| | now: v4, engine, thresholds 0.46 / 0.44 | v4 + engine | v3 + engine | v3, earlier today | fallback rules + engine |
|---|---|---|---|---|---|
| Harmful caught / false alarms (`demo_sosyal`) | 86.7 % / 0.6 % | 85.9 % / 0.6 % | 85.2 % / 0.6 % | 84.0 % / 0.6 % | 54.4 % / 0.3 % |
| `demo_okul`: harmful caught / harmless held or blocked | 87.1 % / 5.2 % | 87.8 % / 5.9 % | 87.1 % / 5.2 % | 86.3 % / 4.9 % | 54.4 % / 1.9 % |
| Gray zone in yellow | 24 % | 23 % | 21 % | 19 % | 1 % |
| Innocent sentences blocked | 0 | 0 | 0 | 0 | 2 |
| Category accuracy | 96.4 % | 96.4 % | 96.4 % | 96.4 % | 79.0 % |
| The team's evaluation set | 310 of 312 | 310 of 312 | 310 of 312 | 310 of 312 | 304 of 312 |

- **The engine** (`safenet/engine/analysis.py`, `safenet/ml/rules.py`). Model 1 learned from whole messages but the
  API scores sentences: harm spread over sentences that each look mild ("you! you blocked me worm why!!") was
  allowed. A message of several sentences, up to 300 characters, is now scored as a whole too; that score can make
  it yellow, never red, and never for a message that reports someone or has a likely typo. Threats in common
  implicit phrasings ("you'll regret coming to school tomorrow", "keep talking and see what happens"), a victim
  reporting names ("some kids keep calling me fat and ugly", scored without them) and an identity label with an
  intensifier ("u flippin homosexual") are new rules, and the models no longer read ordinary words that carry a
  slur ("snigger": "The kids began to snigger at the joke." was blocked on `demo_okul` with the v4 models).
- **The models: graded labels (v4).** About ten people labelled each Wikipedia comment; where they split (30-70 %),
  Model 1 now learns their share instead of the majority's 0 or 1 (`models/README.md`). Every source ranks a little
  better (test ROC-AUC 0.9739 → 0.9745, PR-AUC 0.9336 → 0.9347), and a comment people disagree on gets a middle
  score: the gray zone the design asks for.

Both were chosen on a validation split carved out of the training split (ten Model 1 variants, `models/README.md`);
the test split was used once per measurement, as before.

## Where a target is not met

- **Gray zone, 24 % yellow.** Up from 19 %, not most. Of the 70 messages, 55 are tweets that two datasets
  labelled differently, many about a TV cooking show's contestants ("kat needs serious medication", "so
  delusional"); graded labels exist only for Wikipedia, so the tweets are still scored with the confidence of
  their hard labels.
- **School profile, 5.2 % of harmless messages held** (4.9 % with v3), with 87.1 % of the harmful ones caught (86.3 %
  with v3). On `egitim` yellow is held for a moderator, so catching more also holds more; `sari_esigi` 0.44 (tuned on
  the validation split) brought it down from 5.9 % at 0.40. The PDF's 5 % target is for the default profile.
- **Simulation, 89 % of the users who should be restricted.** Unchanged by the models. The three who are not: two
  friends swearing at each other (no banter discount: their word points add up, but not to 70 within a
  conversation) and one troll: of the troll's five messages labelled harmful, most are indirect jabs ("you love
  getting smacked around, huh?") and one condemns prejudice ("it is 2019, we shouldn't be using the word gay as an
  insult"). Whether swearing alone should restrict faster is a points setting (`ayarlar.toml`).
- **Simulation, 11 % of the others restricted** (the same six users with v3 and v4). Every one of them sent a
  message labelled harmful first: the simulation gives normal users and victims 2 % harmful messages drawn at random
  from the test split, and a repentant user starts with two. In a 1:1 chat a red message with an identity in it
  scores at least 25 (red) + 30 × 1.5 (targeted identity attack, 1:1) = 70, `susturma_esigi` itself: three of
  the six were restricted by one such message, the other three by two or three harmful messages. At least two of the
  messages that restricted them object to prejudice but are labelled harmful in the data ("how is consistently
  making offensive comments that target women, gay or trans people funny?"). No user was restricted by harmless
  messages alone on `demo_sosyal` and `demo_oyun`; on `demo_okul` one was (2 %).

## Load

With the v4 models and this engine, 3 workers on the 3 vCPUs, real messages of the test split: 870 messages a
second at concurrency 4, server p50 2.5 ms (`../bench/RESULTS.md`; v3 earlier today: 887).

## Reproduce

On the server, in a copy of the repository with `veri/` and the models trained there:

```bash
nice -n 10 .venv/bin/python measure.py --markdown docs/RESULTS.md   # the table (this page adds the notes)
.venv/bin/python simulate.py --users                                # the simulation, one line per user
.venv/bin/python degerlendir.py --hatalar                           # the team's evaluation set
SAFENET_MODELS_DIR=/an/empty/folder .venv/bin/python measure.py     # the fallback rules
```

## Branch claude/full-integration-v3: tuned on dev, measured once on held-out data

Measured on a laptop (x86, Windows), 18 Oct 2026, with a pair trained there by `train.py --hard-labels` (v3
labels: the raw Wikipedia file is not on the laptop) from `yerel_veri.py`'s data. These numbers compare the
branch with the code it started from (`6f9896a`), same models, same data; the numbers above stay the server's.

How it was tuned without looking at the test data: the evaluation set is split into a dev part (61 messages) and a
test part (43) with a fixed seed (`degerlendir.py --bolum`); `train.py` also saves `models_dev/`, the same models fit
without the validation split; every change was chosen with `SAFENET_MODELS_DIR=models_dev measure.py --dev` (the
validation split and the dev part only). The test split, YouTube, the simulation and the test part were measured
once, at the end.

| Held out, measured once | 6f9896a | v3 |
|---|---|---|
| Harmful caught / false alarms, `demo_sosyal` (test split) | 85.3 % / 0.7 % | 86.0 % / 0.7 % |
| `demo_okul`: harmful caught / harmless held or blocked | 87.1 % / 5.7 % | 86.4 % / 5.1 % |
| `demo_oyun`: harmful caught / false alarms | 83.2 % / 0.7 % | 83.2 % / 0.7 % |
| YouTube, `demo_sosyal`: harmful caught / false alarms | 84.9 % / 15.3 % | 85.4 % / 15.5 % |
| Innocent sentences blocked | 0 of 124 | 0 of 124 |
| 1:1 simulation, `demo_sosyal` / `demo_okul`: restricted of the others | 11 % / 23 % | 11 % / 21 % |
| The team's evaluation set, test part | 127 of 129 | 127 of 129 |

What changed: the yellow thresholds (`sari_esigi` 0.50 → 0.46 by default, the value `train.py` proposes; `egitim`
0.40 → 0.44), spaced-out letters ("h e l l o" was read as "hell" and blocked), 🖕 as a listed word, and children's
self-harm slang ("unalive yourself", "neck yourself", "go drink bleach"). The two evaluation-set misses are the
same before and after (D039, D098, both `demo_okul`). The p99 time per message on the laptop (~28 ms) is Windows
scheduling; on the server it was 8.1 ms.

`temizlik.py` changed (spaced letters, 🖕), so retrain the server's models before deploying this branch.
