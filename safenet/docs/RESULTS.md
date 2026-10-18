# Results

SafeNet measured against the targets of the team's design (`SafeNet_Model_Tasarimi.pdf`, section 9), through the
code the API runs, on the LinuxONE server (s390x, IBM z17), 18 Oct 2026, with the v3 models and the phrase rules.
Nothing measured here was trained on: the test split (37,588 messages), YouTube (3,459 comment threads), the
124 innocent example sentences of `karistirilabilir_kelimeler.csv`, the 70 gray-zone messages, the 1:1 simulation
(40 conversations, 80 users) and the team's evaluation set (104 messages × 3 platforms).
Every message is judged as the first message of a new sender; the simulation measures the hidden points.

| Target (PDF section 9) | Measured | Goal | Met |
|---|---|---|---|
| Harmful messages caught (test split, `demo_sosyal`) | 84.0 % (85.0 % with the proposed `sari_esigi` 0.45) | ≥ 85 % | no (yes with the proposal) |
| False alarms: harmless messages held or blocked (`demo_sosyal`) | 0.6 % | ≤ 5 % | yes |
| Per source: harmful caught / false alarms | cyberbullying 89 % / 1.8 %, Kaggle 78 % / 3.5 %, Twitter 52 % / 3.5 %, Wikipedia 79 % / 0.3 % | reported | |
| Unseen platform, YouTube: harmful caught / false alarms | 84.9 % / 16.9 % | reported | |
| Innocent sentences blocked (duck, Muslim, bullied, Scunthorpe...) | 0 of 124 on every platform | none | yes |
| Gray zone (conflicting labels) in yellow | 19 % (green 73 %, red 9 %) | most | no |
| Category accuracy, human labels (Model 2) | 96.4 % | ≥ 75 % | yes |
| Time per message, whole analysis on one core (p50 / p99) | 2.0 / 7.7 ms | < 10 ms | yes |
| 1:1 simulation: restricted, of the users who should be (`demo_sosyal`) | 89 % (24 of 27) | ≥ 90 % | no |
| 1:1 simulation: restricted, of the others | 11 %, 0 % by harmless messages alone | ≤ 5 % | see below |
| Bullying conversations where the victim stops getting the bully's messages | 6 of 6 | every one | yes |
| The team's evaluation set: expected decision given | 310 of 312 (99.4 %) | reported | |

Per platform on the test split (harmful caught / harmless held or blocked / harmless censored):
`demo_sosyal` 84.0 % / 0.6 % / 4.6 %, `demo_okul` 86.3 % / 4.9 % / 1.3 %, `demo_oyun` 82.1 % / 0.6 % / 4.0 %.
1:1 simulation (restricted of those who should be / of the others, by harmless messages alone / bullying
conversations protected): `demo_sosyal` 89 % / 11 %, 0 % / 6 of 6, `demo_okul` 93 % / 19 %, 2 % / 6 of 6,
`demo_oyun` 74 % / 6 %, 0 % / 6 of 6.

## Models against the fallback rules

| | v3 + rules | v2 + rules | fallback rules only |
|---|---|---|---|
| Harmful caught / false alarms (`demo_sosyal`) | 84.0 % / 0.6 % | 84.1 % / 0.6 % | 54.2 % / 0.3 % |
| Innocent sentences blocked | 0 | 1 | 2 |
| Category accuracy | 96.4 % | 96.3 % | 79.0 % |
| 1:1 simulation: restricted, of those who should be | 89 % | 89 % | 56 % |
| Bullying conversations protected | 6 of 6 | 6 of 6 | 6 of 6 |
| The team's evaluation set | 310 of 312 | 305 of 312 | 301 of 312 |

The fallback rules (a few dozen weighted phrases) block little and catch half; the models catch most harmful
messages without blocking more harmless ones.

## Where a target is not met

- **Harmful caught, 84.0 % on `demo_sosyal`.** One threshold away: `sari_esigi` 0.45 instead of 0.50 gives
  85.0 % with no more messages held or blocked (`models/README.md`, "Threshold proposals"). The school profile
  already catches 86.3 %. By source, Twitter's sexism and racism tweets are caught least (52 %), then Kaggle (78 %).
  Scoring identity mentions the way the data labels them would catch more (86.7 % with v2), but in a hand check of
  70 such messages about 4 in 5 were harmless mentions labelled harmful ("i am a christian woman, i believe in
  ..."), and the design says an identity that is only mentioned adds nothing.
- **Gray zone.** The 70 messages whose datasets disagreed are mostly scored green: the models are confident where
  people were not. The design's wish ("most of them yellow") would need a model trained on graded labels.
- **Simulation, 89 % of the users who should be restricted.** The three who are not are two friends swearing at each
  other (no banter discount: their word points add up, but not to 70 within a conversation) and one troll. Whether
  swearing alone should restrict faster is a points setting (`ayarlar.toml`).
- **Simulation, 11 % of the others restricted.** Every one of them sent a message labelled harmful first: the
  simulation gives normal users and victims 2 % harmful messages at random, some of them racist slurs, and a
  repentant user starts with two harmful messages drawn from the test split, here a threat and a homophobic slur.
  No user was restricted by harmless messages alone on `demo_sosyal` and `demo_oyun`; on `demo_okul` one was (2 %).

## Load

With the models, 3 workers on the 3 vCPUs: 887 messages a second at concurrency 4, server p50 2.2 ms
(`../bench/RESULTS.md`).

## Reproduce

On the server, in a copy of the repository with `veri/` and the models trained there:

```bash
nice -n 10 .venv/bin/python measure.py --markdown docs/RESULTS.md   # the table (this page adds the notes)
.venv/bin/python simulate.py --users                                # the simulation, one line per user
.venv/bin/python degerlendir.py --hatalar                           # the team's evaluation set
```
