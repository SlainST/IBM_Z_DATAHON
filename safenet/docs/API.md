# API

What a platform adapter (the team's `config.py` for WhatsApp, YouTube, the notebook test...) sends and
gets back. The design is section 2 of `SafeNet_Model_Tasarimi.pdf`; its field names were a draft, so the
API uses the English names in the table at the end. JSON Schema of every body: `schemas/*.schema.json`.
Every worker also serves the OpenAPI page at `/docs`.

Any worker on any server gives the same answer: points live in Postgres (`docs/STATE.md`).

| Method and path | Answers |
|---|---|
| `POST /v1/check` | What may the recipient see? One message. |
| `POST /v1/check/batch` | The same for up to `SAFENET_MAX_BATCH` (100) messages, in order. |
| `GET /v1/groups/{group}/users/{user}` | A user's hidden points and level in one group. |
| `GET /v1/relations/{sender}/{recipient}` | The A → B relation points and whether A is blocked from B. |
| `GET /v1/stats` | Platform counters: messages, harmful rate, decisions, categories, restricted users. |
| `GET /v1/groups/{group}/stats` | The same for one group ("topluluk sağlığı"). |
| `GET /v1/groups?limit=50` | Groups with the most harmful messages first. |
| `GET /v1/settings` | The thresholds and points this platform is judged by. |
| `GET /health` | No key. Hardware (s390x, machine type, NNPA), models in use, store reachable. 503 while points can't be written. |
| `GET /metrics`, `/metrics/prometheus` | No key. Counts per platform and decision, latency buckets. nginx serves these only to private addresses. |

## Authentication

Every `/v1` call carries the platform's key in the `X-API-Key` header. The key decides the platform, and
the platform's block in `config/ayarlar.toml` decides the rules: a request never carries settings, a
profile or a platform id (PDF decision 21).

- New key: `python scripts/new_api_key.py demo_okul`. It prints the key once and stores only its SHA-256
  in `config/api_keys.toml`. Run it on the server: the file is gitignored and `push_to_server.sh` never
  copies it.
- Laptops and tests: start the API with `SAFENET_DEV_KEYS=1` and use `dev-<platform>`, e.g.
  `dev-demo_sosyal`. Never set it on a server others can reach.

## `POST /v1/check`

```json
{
  "sender_id": "u_4821",
  "recipient_id": "u_1093",
  "group_id": "t_77",
  "message_id": "m_000123",
  "text": "Great match yesterday Mark. But if you show up on Friday I'll f*cking break your legs."
}
```

| Field | Required | Notes |
|---|---|---|
| `sender_id` | yes | |
| `text` | yes | 1 to `SAFENET_MAX_TEXT_LEN` (2,000) characters. Never stored. |
| `recipient_id` | for 1:1 | Turns on recipient protection (A → B) and the ×1.5 identity points. Without it only the sender is scored. |
| `group_id` | no | Class, server, clan... Default `"general"`. A user's points are kept per group. |
| `message_id` | strongly advised | Unique per platform. A retry with the same id gets the same decision and adds no points twice. |

Ids are 1 to 128 characters, any UTF-8 except `/` and control characters. Unknown fields are refused (422).

The answer, on `demo_sosyal` with the fallback rules standing in for the models:

```json
{
  "key": "demo_sosyal/t_77/u_4821",
  "platform": "demo_sosyal", "group": "t_77", "sender": "u_4821", "recipient": "u_1093",
  "message_id": "m_000123",
  "decision": "block",
  "recipient_sees": null,
  "reason": "threat",
  "worst_sentence": "But if you show up on Friday I'll f****** break your legs.",
  "harm": 0.9588,
  "wordless_harm": 0.9314,
  "category": "threat",
  "key_words": ["break your legs", "fucking"],
  "censored": [{"start": 62, "end": 69}],
  "hidden_profanity": [{"written": "f*cking", "word": "fucking"}],
  "possible_typos": [],
  "sender_standing": {"level": "warned", "change": 48.0, "restrictions": 0, "restricted_until": null},
  "relation": {"blocked": true, "change": 48.0},
  "suggested_action": "warn_sender",
  "replayed": false,
  "latency_ms": 1.505
}
```

What the platform does with it:

| `decision` | Show the recipient | When |
|---|---|---|
| `allow` | `recipient_sees` (the text as sent) | Green, no profanity. |
| `censor` | `recipient_sees` (profanity starred, first letter kept: `f***`) | Green with profanity, or yellow on a profile that censors yellow. |
| `hold` | nothing yet; the platform keeps the message for a moderator | Yellow on a profile that holds (egitim, kurumsal), or a quoted threat. |
| `block` | nothing; "a message was blocked" if the platform likes | Red, the sender is restricted, or the recipient no longer receives from this sender. |

The API itself never bans or warns anyone. `suggested_action` is `warn_sender` (the sender just reached the
warning threshold, or sent a yellow message on a profile that warns), `restrict_sender` (the sender is now
restricted: every message is blocked until `sender_standing.restricted_until`), or null.

Other fields:

- `key`: `"platform/group/sender"`, the row whose points changed.
- `reason`: `threat`, `hate`, `very_harmful`, `profanity_ratio` (more than 30 % of the words), `spam`,
  `quoted_threat`, `harmful` (yellow), `profanity`, `sender_restricted`, `relation_blocked`, or null.
- `worst_sentence`: the sentence that decided, starred; null when allowed. The worst sentence decides for
  the whole message.
- `harm`: Model 1's score of that sentence; `wordless_harm`: the same sentence without its profanity.
  "fuck, I missed the bus" has a high `harm` and a low `wordless_harm`.
- `category`: `insult`, `gender`, `religion`, `race`, `sexual` or `threat`, only for yellow and red.
- `key_words`: the words and phrases that pushed the score up, only for yellow and red.
- `censored`: character offsets in `text` of the starred words (Python string indices).
- `hidden_profanity`: words that were disguised (`f*cking`, `sh1t`, `f u c k`); each adds hiding points.
- `possible_typos`: a listed word that is probably an innocent one ("I fed the fuck at the lake" →
  `{"word": "fuck", "suggestion": "duck"}`). It is still starred but adds no points (PDF decision 20).
- `sender_standing.level`: `normal`, `warned` or `restricted`. `change` is what this message did to the
  points; negative when a clean message lowered them. The points themselves stay hidden
  (`GET /v1/groups/{group}/users/{user}` shows them to the platform's moderators).
- `relation`: null without `recipient_id`. `blocked: true` means this sender's messages stop reaching this
  recipient, in every group of the platform, until the sender's clean messages to them bring it down.
- `replayed`: true when this `message_id` was answered before: the stored decision is returned and nothing
  is counted again.

## `POST /v1/check/batch`

`{"messages": [<CheckRequest>, ...]}` → `{"results": [<CheckResponse>, ...]}`, same order. Each message is
its own transaction, as if sent one by one, so a later message sees the points of an earlier one.

## Errors

| Status | Why | What to do |
|---|---|---|
| 401 | No `X-API-Key`, or an unknown key | Fix the key. |
| 403 | The key's platform has no `[platformlar.<id>]` block in `ayarlar.toml` | Add the block and restart. |
| 422 | Body doesn't match: missing field, unknown field, text too long, bad id | `detail` names each field. |
| 413, 429 | From nginx: body over 2 MB, or the rate limit | Slow down. |
| 503 + `Retry-After: 1` | Postgres unreachable, too slow or read-only (failover) | Retry with the same `message_id`. |

A batch that hits a 503 midway answers 503 as a whole, but the messages before the failure were counted:
send every one with a `message_id` and resend the whole batch. A message without `message_id` retried after
a 503 may be counted twice.

What the recipient sees while SafeNet can't answer is the platform's choice; for children (`egitim`),
holding the message is the safe one.

## From a platform adapter (`config.py`)

```python
import time, uuid
import requests

SAFENET = "http://127.0.0.1:8000"    # deploy/linuxone/tunnel.sh forwards this to the server
KEY = "..."                          # from scripts/new_api_key.py; keep it out of git

def check(sender, recipient, group, text, message_id=None):
    body = {"sender_id": sender, "recipient_id": recipient, "group_id": group, "text": text,
            "message_id": message_id or str(uuid.uuid4())}   # same id on every retry
    for attempt in range(3):
        r = requests.post(f"{SAFENET}/v1/check", json=body, headers={"X-API-Key": KEY}, timeout=2)
        if r.status_code != 503:
            r.raise_for_status()
            return r.json()
        time.sleep(float(r.headers.get("Retry-After", 1)))
    return {"decision": "hold", "recipient_sees": None, "reason": "safenet_unavailable"}

answer = check("u_4821", "u_1093", "t_77", "see you tomorrow")
if answer["decision"] in ("allow", "censor"):
    deliver(answer["recipient_sees"])
elif answer["decision"] == "hold":
    queue_for_moderator(answer)
if answer.get("suggested_action") == "restrict_sender":
    show_sender_notice(answer["sender_standing"]["restricted_until"])
```

## Moderators and dashboards

```
GET /v1/groups/7b/users/u_4821   {"key": "demo_okul/7b/u_4821", "points": 48.0, "level": "warned",
                                  "recent_clean": 0, "recent_messages": 1, "restrictions": 0,
                                  "restricted_until": null, "messages": 1, ...}
GET /v1/relations/u_4821/u_1093  {"points": 48.0, "blocked": true, "recent_clean": 0, ...}
GET /v1/stats                    {"messages": 3, "harmful": 2, "harmful_rate": 0.6667,
                                  "decisions": {"block": 1, "censor": 1, "hold": 1},
                                  "categories": {"insult": 1, "threat": 1}, "restricted_now": 0, ...}
```

A user nobody has scored yet answers with zero points rather than 404. Counters reach Postgres about once
a second from each worker, so `/v1/stats` can lag that much behind `/v1/check`.

## PDF draft names

| PDF (section 2) | API |
|---|---|
| `POST /kontrol`, `API-Anahtari` | `POST /v1/check`, `X-API-Key` |
| `gonderen_id`, `alici_id`, `topluluk_id` (`genel`), `metin` | `sender_id`, `recipient_id`, `group_id` (`general`), `text` |
| `karar`: `teslim_et`, `sansurlu_teslim_et`, `beklet`, `engelle` | `decision`: `allow`, `censor`, `hold`, `block` |
| `alicinin_gorecegi`, `neden`, `en_kotu_cumle` | `recipient_sees`, `reason`, `worst_sentence` |
| `zararlilik`, `kelimesiz_puan` | `harm`, `wordless_harm` |
| `kategori`: hakaret, cinsiyet, din, ırk, cinsel, tehdit | `category`: insult, gender, religion, race, sexual, threat |
| `etkili_kelimeler`, `gizli_kufurler` (`"f*cking -> fucking"`) | `key_words`, `hidden_profanity` (`{"written", "word"}`) |
| `gonderen.seviye` (`uyarilmis`), `gonderen.puan_degisimi` | `sender_standing.level` (`warned`), `sender_standing.change` |
| `onerilen_eylem` (`gonderene_uyari`) | `suggested_action` (`warn_sender`, `restrict_sender`) |
| "olası düzeltme: duck" | `possible_typos` |
| (none) | `message_id`, `key`, `censored`, `relation`, `replayed`, `latency_ms` |
