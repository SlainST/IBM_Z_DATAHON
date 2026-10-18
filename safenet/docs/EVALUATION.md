# Evaluation

`degerlendirme_seti.csv` holds 104 English messages, each with the decision a person expects on `demo_sosyal`,
`demo_okul` and `demo_oyun`: 312 checks (columns in the header of `degerlendir.py`). `python degerlendir.py`
runs them through the real engine on the memory store, so it needs no server and touches no Postgres;
`--hatalar` lists each miss and `--csv sonuc.csv` writes row-by-row results for calibration.

## Results, 18 Oct

| Decisions right, of 312 | Fallback rules | Models (local, see the end) |
|---|---|---|
| Before the rule fixes of `api-tamamlama` (`0055a8d`) | 264 | 245 |
| With them | **272** (87 %) | **253** (81 %) |

The fixes (DECISION_ENGINE choices 9 and 10) add 8 either way: threats on `demo_oyun`, where a game word now
needs game context; "kill yourself" written out; a repeated phrase as spam.

Expected (rows) and given (columns) decisions with the models:

| | allow | censor | hold | block |
|---|---|---|---|---|
| **allow** | 106 | 0 | 0 | 3 |
| **censor** | 1 | 52 | 4 | 11 |
| **hold** | 0 | 0 | 14 | 8 |
| **block** | 24 | 6 | 2 | 81 |

By message type, where the two differ or miss (all other types are right everywhere: clean, look-alike words,
typos, quoted threats, self-harm, spam, profanity ratio, game chat, listed but innocent):

| Type | Fallback | Models |
|---|---|---|
| `agir_zorbalik` (bullying without insult words) | 0/12 | 0/12 |
| `cinsel` (sexual, grooming) | 0/6 | 0/6 |
| `hakaret` (insult) | 20/24 | 8/24 |
| `nefret` (hate) | 12/21 | 12/21 |
| `tehdit` (threat) | 21/24 | 18/24 |
| `kimlik_bahsetme` (identity mentioned, no attack) | 18/18 | 15/18 |
| `kufur_saldirisiz` (profanity, no attack) | 27/27 | 24/27 |
| `karisik` (mixed) | 6/6 | 3/6 |
| `gizli_kufur` (disguised profanity) | 9/9 | 8/9 |
| `deyim` (idiom: "kill it at the exam") | 0/3 | 3/3 |
| `kurban_anlatimi` (a victim's own account) | 9/12 | 12/12 |

## What the models get wrong (for Developer 1)

1. **Insults are blocked.** Model 1 gives plain insults 0.90 to 1.00 ("you are an idiot" 1.00, "you're such a
   loser, seriously" 0.90), so their wordless score passes `cok_kotu_esigi` (0.75 to 0.90) and they are
   blocked as `very_harmful` instead of censored or held. Model 1 says how sure it is that a sentence is
   harmful; the colours read the number as how harmful it is. No threshold separates the two, because:
2. **Bullying, threats and grooming without insult words score low**: "everyone would be happier if you just
   disappeared" 0.02, "you're worthless and everyone at school knows it" 0.06, "I'm going to find you and beat
   you up" 0.10, "send me a pic of you in your underwear" 0.09, "go back to your country, you don't belong here"
   0.26. 24 of the 113 messages that should be blocked are allowed (fallback: 15). The explicit-threat patterns
   in `ml/models.py` are the remedy so far; "find you and beat you up" is not among them.
3. **Casual profanity is yellow on `egitim`**: "holy shit, that was insane" has harm 0.62 and wordless 0.06,
   so `demo_okul` holds it instead of starring it. The fallback keeps the listed words' weight small on purpose.
4. **An identity mention was blocked as hate**: "she's the first black woman to win that award" scored 0.93
   with the local models. The server's v2 measured at most 0.41 on held-out neutral identity sentences, so
   check this one there first.

## The local models

Trained on a laptop with `train.py`, from the committed `birlesik_veri.csv` (older than the server's `veri/`:
40,566 test rows against 37,588; `grup_id` rebuilt with `benzerlik.py`) and scikit-learn 1.9, where liblinear
no longer fits six classes, so Model 2 used saga. Model 1: ROC-AUC 0.974 (server v2: 0.974), F1 0.842 (0.851);
Model 2 macro F1 0.859 (0.867); held-out threats blocked 4 of 8 (same). Close, not equal: rerun
`python degerlendir.py` on the server with its models before acting on the numbers above.

## Speed

On a laptop, analysis cache off, all 936 checks: 0.23 ms per message with the fallback rules (p95 0.35 ms),
1.41 ms with the models (p95 2.0 ms). The server measured 1.35 ms (`models/README.md`).
