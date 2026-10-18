# SafeNet: a message security API on IBM LinuxONE

**Sysplex Squad, IBM Z Datathon 2026.** SafeNet sits between a platform and its users. Before a school app, a
game or a messenger delivers a one-to-one message, it asks SafeNet what the recipient may see:

| Decision | The recipient sees | For example |
|---|---|---|
| `allow` | the message | "see you tomorrow at practice" |
| `censor` | the message with its profanity starred | "f***, I missed the bus again" |
| `hold` | nothing until a moderator looks | an insult on a children's platform; a reported threat |
| `block` | nothing | "But if you show up on Friday I'll f*cking break your legs." |

Each answer comes in a few milliseconds from an IBM z17 (s390x), with the reason, the category (insult, gender,
religion, race, sexual, threat) and the words that decided. SafeNet also keeps hidden points per platform, group
and sender: a sender who keeps attacking is warned and then restricted, and once A's messages towards B have
added up, they stop reaching B, while A can still write to everyone else. Message text is never stored.

## What is where

| Path | What |
|---|---|
| [`safenet/`](safenet/README.md) | the API, the models' training, the measurements, the demo and the adapters: start here |
| [`safenet/docs/`](safenet/docs/) | API reference, decision engine, state, measured results |
| [`safenet/SafeNet_Model_Tasarimi.pdf`](safenet/SafeNet_Model_Tasarimi.pdf) | the team's design (in Turkish) |
| `birlesik_veri.csv`, `youtube_test.csv`, `karistirilabilir_kelimeler.csv` | the prepared data: ~188k labelled messages (train/test split), the YouTube set kept for testing, 124 look-alike words |

## How it works, in short

- **Two small models**, trained on the LinuxONE server with scikit-learn: Model 1 scores how harmful each
  sentence is (hashed word and character n-grams, logistic regression, ~0.5 ms per call), Model 2 names the
  category. No GPU, no torch: they run where the data is.
- **Rules the team wrote around them:** disguised profanity (`f*ck`, `sh1t`, `f u c k`) is decoded and starred,
  the worst sentence decides, a sentence is scored again without its profanity to tell swearing from malice,
  explicit threats and severe bullying are lifted, an identity only mentioned ("I'm a proud Muslim") adds nothing,
  and a threat someone reports ("he told me ...") goes to a moderator instead of silencing the victim.
- **Every number is a setting:** each platform picks a profile (social media, education, game, workplace) in
  `ayarlar.toml`; a new platform is a new block, no code.

## Run it

```bash
cd safenet
pip install -r requirements/dev.txt
python -m pytest
SAFENET_DEV_KEYS=1 uvicorn safenet.api:app --port 8000
```

On the server: [`safenet/deploy/README.md`](safenet/deploy/README.md). Results against the design's targets:
[`safenet/docs/RESULTS.md`](safenet/docs/RESULTS.md).

## Team

| Role | Owns |
|---|---|
| Developer 1: models | training, synthetic data, phrase rules, measurements |
| Developer 2: rules | settings, word lists, identity analysis, evaluation set, tests |
| Developer 3: LinuxONE | server, deploy, load tests, adapters, demo |

License: MIT ([LICENSE](LICENSE)).
