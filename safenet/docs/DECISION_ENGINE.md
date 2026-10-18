# Decision engine

How `POST /v1/check` judges a message and scores its sender: sections 3 and 6-8 of the team's
`SafeNet_Model_Tasarimi.pdf`, as the code implements them, and the choices the code made where the PDF
says nothing (last section). Every number is in `ayarlar.toml`; `python -m safenet.settings`
prints what each platform ends up with. The design before the PDF is `SAFENET_ARCHITECTURE.md`.

## The 9 steps

| Step (PDF section 3) | Code |
|---|---|
| 1. The platform sends the message | `api/app.py`; the key picks the platform (`api/auth.py`) |
| 2. Cleaning, hidden profanity | `pipeline/profanity.py` finds the words of `kufur_listesi.csv` in the text as sent, decoding `f*ck`, `sh1t`, `f u c k`, look-alike letters and invisible characters with the team's `temizlik.py`; `temizlik.temizle()` removes @names, links and emoji for the models, exactly as in training |
| 3. Sentences | `pipeline/text.py`, `sentences()` |
| 4. Model 1: harm per sentence | `ml/models.py`, one batch call per message; `ml/rules.py` adjusts the scores (below) |
| 5. Wordless harm | Model 1 again on each sentence with its listed words removed |
| 6. Model 2: category | insult, gender, religion, race, sexual, threat |
| 7. Identity | the team's `kimlik.py`: mention, generalization or targeted (the identity terms are in `kimlik.py`) |
| 8. Decision, censoring, points | `engine/decision.py`, `engine/points.py` |
| 9. The answer | `engine/moderator.py` → the answer in `docs/API.md` |

Until the models are trained, the fallback rules in `ml/models.py` (a few dozen weighted phrases) give both scores.

## Scores: the models and the phrase rules

Model 1 gives a probability, and a probability is not a severity: "you are an idiot" is harmful almost surely,
yet the team's evaluation set expects an insult to be yellow, not blocked. `ml/rules.py` turns the two models'
output into the `harm`, `wordless_harm` and `category` the colours above are computed from:

| What | Effect | Why |
|---|---|---|
| Threat, explicit or in a common implicit phrasing, self-harm encouragement, blackmail ("i'll break your legs", "you'll regret coming to school tomorrow", "kys", "or i'll post your pics") | harm ≥ 0.95, category threat | ~480 threats in the data: phrasings it never saw scored low |
| Severe bullying, sexual request, xenophobia, a group called vermin or criminals | harm ≥ 0.92, that rule's category | red on every profile: "nobody likes you", "send me a pic of you in your underwear", "go back to your country" |
| A plain insult (Model 2: insult, no rule, no identity attacked) | harm ≤ 0.72 | yellow on every profile, never red by itself |
| An identity only mentioned (no slur, no "you muslim", no claim about the whole group, no hostile word) | scored again without the identity words; the lower score is kept | "i'm gay i love men" scored 0.68, "she's the first black woman to win that award" 0.93 |
| Objecting to a harm ("stop making gay jokes", "how is making fun of trans people funny?"), no slur, no label for the reader | scored again without the identity and the harm objected to; the lower score is kept | someone speaking up isn't punished for the words they object to |
| Not addressed to the reader: a harm named ("racism has no place in sports", "i was bullied") or names reported ("some kids keep calling me fat and ugly") | scored again without those words; the lower score is kept | a victim asking for help isn't held |
| What the sender reports ("she told me ...") | only threats keep their floor (and are held as quoted threats) | a victim quoting a bully isn't blocked |
| Harm spread over sentences ("you! you blocked me worm why!!": each sentence alone looks mild) | a message of up to 300 characters is scored as a whole too (identity mentions as above); its harm can make the message yellow, never red | Model 1 learned from whole messages; not for a message that reports someone or has a likely typo |

Each pattern was checked on the training split (precision of the matched messages, how often it fires on
harmless ones); the numbers are in `models/README.md`. Tests: `tests/test_rules.py`, `tests/test_check.py`.

## Colour and decision

Each sentence is judged; the worst one decides for the whole message, even if the others are harmless.

| Colour | When (any sentence) | Decision |
|---|---|---|
| RED | threat and harm ≥ `tehdit_esigi`; or race / religion / gender and wordless ≥ `nefret_esigi`; or wordless ≥ `cok_kotu_esigi`; or more than `spam_kufur_orani` of the message's words are listed profanity; or spam | `block` |
| YELLOW | harm ≥ `sari_esigi`, or the whole message's harm ≥ `sari_esigi` | `censor`, or `hold` when the profile says `sari_davranis = "beklet"` |
| GREEN | everything else | `allow`, or `censor` when it contains profanity |

Quote protection: a threat inside quotes or passed on ("he told me ...", "she keeps saying ...") is held for
a moderator (`reason: quoted_threat`) instead of blocked, so a bullied child isn't silenced.

Two rules come before the colour:

- A **restricted sender**'s messages are all blocked (`sender_restricted`) until the restriction ends.
- When the **A → B relation** has reached `iliski.engel_esigi`, A's messages to B are blocked
  (`relation_blocked`). A's messages to anyone else are not affected.

| Profile | sari | kelimesiz | tehdit | nefret | yellow | game words free | warn | restrict | relation | recovery |
|---|---|---|---|---|---|---|---|---|---|---|
| `sosyal_medya` | 0.50 | 0.85 | 0.60 | 0.75 | censor + warn | no | 40 | 70 | 40 | 7 of 10, −10 % |
| `egitim` | 0.40 | 0.75 | 0.50 | 0.65 | hold | no | 30 | 50 | 30 | 8 of 10, −5 % |
| `oyun` | 0.60 | 0.90 | 0.70 | 0.75 | censor | yes | 50 | 90 | 50 | 7 of 10, −15 % |
| `kurumsal` | 0.45 | 0.80 | 0.55 | 0.75 | hold | no | 35 | 60 | 40 | 7 of 10, −10 % |

`spam_kufur_orani` is 0.30 everywhere. Platforms: `demo_okul` (egitim), `demo_oyun` (oyun, restriction at 80),
`demo_sosyal` (sosyal_medya). A new platform is a new `[platform.<id>]` block, no code.

## Sender points

Hidden points per **platform / group / user**: a user who moves to another group starts at 0 there.

| Event | Points |
|---|---|
| Each listed word | its points (1-10) × `kelime_carpani`, at most 15 per message |
| Each disguised word (`f*ck`, `sh1t`, `f u c k`) | +3 |
| Yellow message | +10 |
| Blocked message / blocked threat / blocked spam | +25 / +40 / +20 |
| Identity in a harmful sentence: mention / generalization / targeted | +10 / profile (20 or 30) / profile (30 or 40), ×1.5 in 1:1 |

At `uyari_esigi` the answer suggests `warn_sender`. At `susturma_esigi` the sender is restricted for 5, then
60, then 1440 minutes (and 1440 for every later one), and the points drop to 35. Points never fall with
time; a **clean** message (green, no profanity) lowers them by the profile's rate when at least
`iyilesme_esigi` of the previous 10 messages were clean.

The PDF example, on `demo_sosyal`: "... I'll f*cking break your legs." is a threat (harm 0.96, wordless 0.95 with the fallback rules)
→ block, +40 threat + 5 fucking + 3 disguised = **+48**, past 40 → warned. `tests/test_check.py` checks
this and the recovery rule.

**A → B relation** (platform-wide): the same events, counted only for A's messages to B, with the same
recovery. At `iliski.engel_esigi` A's messages stop reaching B in every group. A relation is never
restricted, and its row exists only while its points are above 0.

## Choices the PDF left open

What the code does today. Each is a line in `ayarlar.toml` or a few lines of code. Developer 2 marks each
one after the team review: **kalsın** (keep), **değişsin** (change, then it goes into `ayarlar.toml` or the
code with a test), or **bekliyor** (not reviewed yet). "Checked" means the text below was compared with the
code on 18 Oct. The evaluation set shows what each choice does to real messages: rows of
`degerlendirme_seti.csv` carry the choice's number in `ilgili_karar`, and `python degerlendir.py` runs them.

1. **Short messages and the profanity ratio.** The rule counts words literally, so "fuck you" (1 of 2) and
   "this is shit" (1 of 3) are red and blocked, while "f*ck, I missed the bus" (1 of 5) is censored. A
   minimum message length for this rule would soften it.
   **Status: kalsın** (18 Oct): the rule stays as in the PDF. It also blocks "damn", "hell yeah", "oh shit"
   and "wtf" (+26 to +31 points on `demo_sosyal`). On the test split of this repo's `birlesik_veri.csv`
   (40,566 messages) it blocks 16 of 32,094 harmless and 273 harmful messages by itself.
2. **One targeted hate message can restrict at once.** "you dirty muslim" in 1:1 on `sosyal_medya` is
   blocked +25 and targeted 30 × 1.5 = +45, so 70: restricted by its first message. On `egitim` it is 85.
   **Status: kalsın** (18 Oct): the points are not lowered. On `demo_oyun` the same message gives +70, which
   is a warning there (restriction at 80).
3. **Targeted** means the identity sentence also has a second-person word (you, your, u, ur...);
   **generalization** means a plural term or "all / every / those / typical" before it; otherwise a
   mention. The PDF also says "in 1:1 every message counts as written to the recipient (hedefli)"; the code
   takes that to mean the ×1.5 factor, not that every 1:1 identity sentence is targeted.
   **Status: kalsın** (18 Oct): the code and `ayarlar.toml` stay as they are.
4. **Identity points need harm.** They are added only when that sentence's score reaches the profile's
   yellow threshold ("only if the model found the message harmful"). "I'm a proud Muslim" adds nothing.
   **Status: bekliyor.** Checked: matches the code.
5. **Quoted threats** are held and add no blocked or yellow points; their profanity still counts.
   **Status: bekliyor.** Checked: matches the code.
6. **A restricted sender is frozen**: blocked messages add no points and don't count towards recovery.
   **Status: bekliyor.** Checked: matches the code.
7. **A relation-blocked message is still scored**, so A can bring A → B back down with clean messages to B.
   **Status: bekliyor.** Checked: matches the code.
8. **Possible typos.** A sentence whose only profanity looks like a typo ("I fed the fuck at the lake")
   is judged by its wordless score; the word is still starred and adds no points. Clues are looked for
   within 6 words (`karistirilabilir_kelimeler.csv`).
   **Status: bekliyor.** Checked: matches the code. A clue can also fit a real swear word: in
   "holy shit, that goal was insane" "goal" is a clue for "shot", so "shit" is starred but adds no points.
9. **Game language** (`oyun_dili_serbest`): the words with `kategori = oyun_dili` in
   `karistirilabilir_kelimeler.csv` are taken out before the models score the sentence, so "I will kill you
   noob" is allowed on `demo_oyun`. Listed phrases such as "kys" and "kill yourself" are still starred,
   scored and can still be red.
   **Status: bekliyor.** Checked: two differences from the text above.
   (a) The words are taken out whatever the context, while `ayarlar.toml` says they are free only "oyun
   bağlamındaysa (match, round, gg...)" and `karistirilabilir_kelimeler.csv` gives context clues for each.
   So on `demo_oyun` "I hope you die in a fire", "you are dead after school" and "I will kill you and your
   whole family" are allowed.
   (b) "kill yourself" written out is not found in the text, only `kys` is: list entries of two words are
   not matched. It is not starred on any platform, and on `demo_oyun` it is allowed.
   **On `fevzi/integration`, for the team review:** (a) a game word is taken out only when the message has one
   of that word's context clues from `karistirilabilir_kelimeler.csv` ("gg, I will kill you next round" is
   allowed on `demo_oyun`, "I will kill you and your whole family" is blocked there too; `pipeline/text.py`,
   `without_game_words`), and never inside a listed phrase ("gg noob, go kill yourself" keeps its "kill", so
   it is blocked as self-harm encouragement); (b) a listed phrase none of whose words is listed ("kill
   yourself", "kill urself", "kill your self") is found written out, starred and scored 10 like `kys`
   (`pipeline/profanity.py`, `phrases`). The team test that expected "I will kill you" to be allowed on
   `demo_oyun` now uses "gg, I will kill you next round".
10. **Spam** has points in the PDF but no rule: 3 or more links, or one word repeated at least 8 times and
    making up more than 60 % of the message.
    **Status: bekliyor.** Checked: the rule is in the code (`pipeline/text.py`, `spam()`), not in
    `ayarlar.toml`. A repeated phrase is not spam: in "follow me" × 8 each word is 50 % of the message.
    **On `fevzi/integration`:** a phrase of up to 4 words counts like a word: "follow me" × 8 is spam (8
    repeats, 100 % of the words). The numbers are settings now, as developer 2's branch proposed:
    `spam_link_sayisi`, `spam_tekrar_sayisi`, `spam_tekrar_orani` in `ayarlar.toml` (`decision.is_spam`).
11. **Model 2 runs only for sentences with harm or wordless harm ≥ 0.25**, and `category` is reported only
    for yellow and red, to keep the latency down.
    **Status: bekliyor.** Checked: matches the code.
12. **Which red reason wins** when several apply: threat, then hate, then very harmful, then spam, then the
    profanity ratio.
    **Status: bekliyor.** Checked: matches the code.
13. **`change` is what the message added**, before a new restriction resets the points to 35: going from 50
    to 75 reports +25 and leaves 35.
    **Status: bekliyor.** Checked: matches the code.
14. **Points below 1 become 0** once recovery brings them that low, so a relation row is deleted instead of
    shrinking forever.
    **Status: bekliyor.** Checked: the limit is `ZERO_BELOW = 1.0` in `engine/points.py`, not a setting.
15. **Without `recipient_id`** a message is scored for the sender only, with no ×1.5. The PDF covers 1:1
    only; groups and live streams come later.
    **Status: bekliyor.** Checked: matches the code.
16. **Text is never stored.** Each worker caches its analysis (spans and scores, keyed by a hash of the
    text) for repeated messages; Postgres keeps only points, counters and the last 10 clean / not-clean
    bits.
    **Status: bekliyor.** Checked: Postgres keeps no text, but the worker's cache also holds the starred text
    of up to `SAFENET_ANALYSIS_CACHE` (4,096) recent messages in memory (`censored_text` in
    `engine/analysis.py`). **On `fevzi/integration`** (as developer 2's branch proposed): the cache keeps
    offsets, scores, the listed words found and the spam counts, never the message; the starred text is made
    again from the request for each answer (`engine/moderator.py`).
