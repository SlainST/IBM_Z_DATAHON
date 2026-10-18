"""SafeNet against the targets of SafeNet_Model_Tasarimi.pdf, section 9 ("Ölçüm planı"), measured through the code
the API runs (safenet.engine.moderator) with the models in models/ (the fallback rules without them).

    python measure.py                              # everything; on the server ~5 min on one CPU (use nice)
    python measure.py --quick                      # 3,000 test messages instead of all 37,588
    python measure.py --markdown docs/RESULTS.md   # also the table as Markdown
    SAFENET_MODELS_DIR=models_dev python measure.py --dev   # while tuning: no held-out data is read (below)

--dev is for changing rules, thresholds and settings: the validation split of the training split instead of the
test split, the dev part of the evaluation set, the innocent sentences; no YouTube, gray zone or simulation. Use it
with models_dev/ (train.py writes it: the same models fit without the validation split), so the models never saw
what is measured. Measure without --dev once, when the tuning is done: that is the number to report.

Writes veri/measure_report.json. Every message is judged as the first message of a new sender, so these numbers
are about messages, not about a sender's history; the hidden points are measured by the 1:1 simulation
(simulate.py). Nothing here was trained on: the test split, YouTube, the sets below and the simulation are all
held out. The model files only work on the byte order they were trained on (safenet/ml/models.py): measure the
server's models on the server.

| Target (PDF section 9)                    | Data                                          | Goal                     |
|-------------------------------------------|-----------------------------------------------|--------------------------|
| Harmful messages caught                   | test split of veri/birlesik_veri.csv          | >= 85 % not allowed      |
| False alarms on harmless messages         | test split                                    | <= 5 % held or blocked   |
| Per source, unseen platform               | test split by source; YouTube comments        | reported                 |
| Innocent sentences (duck, Muslim...)      | karistirilabilir_kelimeler.csv                | none blocked             |
| Gray zone                                 | veri/belirsiz_test.csv                        | most of it yellow        |
| Category accuracy                         | harmful test messages with a human label      | >= 75 %                  |
| Speed                                     | in process, on the machine it runs on         | < 10 ms per message      |
| Hidden points                             | 1:1 simulation                                | >= 90 % / <= 5 %         |
| Recipient protection                      | bullying conversations of the simulation      | every one                |
| The team's evaluation set                 | degerlendirme_seti.csv                        | reported                 |
"""
import argparse
import json
import platform as machine
import statistics
import time
from collections import Counter
from pathlib import Path

import pandas as pd

import degerlendir
import simulate
from safenet import ibmz
from safenet.engine.moderator import Moderator
from safenet.ml.models import CATEGORY, Models, fallback_category
from safenet.state.store import MemoryStore

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "veri"
PLATFORMS = ("demo_sosyal", "demo_okul", "demo_oyun")
HEADLINE = "demo_sosyal"                      # the default profile: the number the PDF's single targets refer to
RED = {"threat", "hate", "very_harmful", "profanity_ratio", "spam", "quoted_threat"}
GOALS = {"harmful_caught": 0.85, "harmless_false_alarm": 0.05, "category_accuracy": 0.75, "ms_per_message": 10.0}


def colour(reason: str | None) -> str:
    return "red" if reason in RED else "yellow" if reason == "harmful" else "green"


class Judge:
    """Every message as the first message of a new sender, on each platform. One Moderator: its analysis cache
    lets demo_okul reuse demo_sosyal's analysis (same text rules), so most messages are analysed twice, not three
    times (demo_oyun frees game words)."""

    def __init__(self, models: Models):
        store = MemoryStore()
        store.open()
        self.mod = Moderator(store, models=models)
        self.n = 0

    def __call__(self, text: str, platforms=PLATFORMS) -> dict:
        self.n += 1
        out = {}
        for p in platforms:
            start = time.perf_counter()
            r = self.mod.check(p, {"sender_id": f"m{self.n}", "recipient_id": f"r{self.n}", "group_id": "measure",
                                   "text": text})
            out[p] = {"decision": r["decision"], "reason": r["reason"], "category": r["category"],
                      "ms": (time.perf_counter() - start) * 1000}
        return out


def decisions(judged: list[dict], y, platforms=PLATFORMS) -> dict:
    """Per platform: harmful caught (not allowed), harmless held or blocked, and every decision's share."""
    y = list(y)
    out = {}
    for p in platforms:
        d = [j[p]["decision"] for j in judged]
        harmful = [x for x, t in zip(d, y) if t == 1]
        harmless = [x for x, t in zip(d, y) if t == 0]
        share = lambda xs, ok: round(sum(x in ok for x in xs) / len(xs), 4) if xs else None  # noqa: E731
        out[p] = {"harmful_caught": share(harmful, ("censor", "hold", "block")),
                  "harmful_blocked": share(harmful, ("block",)),
                  "harmless_false_alarm": share(harmless, ("hold", "block")),
                  "harmless_censored": share(harmless, ("censor",)),
                  "harmful": len(harmful), "harmless": len(harmless)}
    return out


def test_split(judge: Judge, quick: bool, dev: bool = False) -> tuple[dict, list]:
    data = pd.read_csv(DATA / "birlesik_veri.csv")
    if dev:
        from train import split_validation          # the validation split train.py chose C and thresholds on
        test = split_validation(data[data["bolum"] == "egitim"])[1]
    else:
        test = data[data["bolum"] == "test"]
    if quick:
        test = test.sample(n=3000, random_state=42)
    judged = [judge(t) for t in test["metin"]]
    report = {"messages": len(test), "platforms": decisions(judged, test["zararli"]),
              "by_source": {src: decisions([judged[i] for i in idx], g["zararli"], [HEADLINE])[HEADLINE]
                            for src, g in test.reset_index(drop=True).groupby("kaynak") for idx in [g.index]}}
    ms = [j[HEADLINE]["ms"] for j in judged]
    report["ms_per_message"] = {"p50": round(statistics.median(ms), 3), "p95": round(_pct(ms, 0.95), 3),
                                "p99": round(_pct(ms, 0.99), 3), "mean": round(statistics.fmean(ms), 3)}
    return report, [(t, j) for t, j in zip(test.itertuples(), judged)]


def _pct(values, p):
    s = sorted(values)
    return s[min(len(s) - 1, int(p * len(s)))]


def categories(models: Models, judged_test: list) -> dict:
    """Model 2 on harmful test messages whose category a person gave (the dataset's label or our hand fixes),
    and the category the API reports for those it marks yellow or red."""
    rows = [(t, j) for t, j in judged_test if t.zararli == 1 and t.tur_kaynagi in ("etiket", "duzeltme")]
    if not rows:
        return {}
    truth = [CATEGORY[t.tur] for t, _ in rows]
    texts = [t.metin for t, _ in rows]
    if models.model2 is not None:
        predicted = [CATEGORY.get(str(c), str(c)) for c in models.model2.predict(texts)]
    else:
        predicted = [fallback_category(x) for x in texts]
    api = [(j[HEADLINE]["category"], c) for (_, j), c in zip(rows, truth) if j[HEADLINE]["category"]]
    return {"messages": len(rows), "model2_accuracy": round(sum(p == c for p, c in zip(predicted, truth)) / len(rows), 4),
            "per_category": {c: round(sum(p == c for p, t in zip(predicted, truth) if t == c) / n, 4)
                             for c, n in Counter(truth).items()},
            "api_flagged": len(api),
            "api_accuracy_when_flagged": round(sum(a == c for a, c in api) / len(api), 4) if api else None}


def youtube(judge: Judge) -> dict:
    yt = pd.read_csv(DATA / "youtube_test.csv")
    judged = [judge(t, (HEADLINE, "demo_okul")) for t in yt["metin"]]
    return {"messages": len(yt), "platforms": decisions(judged, yt["zararli"], (HEADLINE, "demo_okul"))}


def innocent(judge: Judge) -> dict:
    rows = pd.read_csv(ROOT / "karistirilabilir_kelimeler.csv")
    out = {"sentences": len(rows)}
    judged = [(s, judge(s)) for s in rows["ornek_masum_cumle"]]
    for p in PLATFORMS:
        out[p] = {"blocked": [s for s, j in judged if j[p]["decision"] == "block"],
                  "held": [s for s, j in judged if j[p]["decision"] == "hold"]}
    return out


def gray_zone(judge: Judge) -> dict | None:
    if not (DATA / "belirsiz_test.csv").exists():   # veri_hazirla.py writes it; yerel_veri.py cannot
        return None
    rows = pd.read_csv(DATA / "belirsiz_test.csv")
    colours = Counter(colour(judge(t, (HEADLINE,))[HEADLINE]["reason"]) for t in rows["metin"])
    return {"messages": len(rows), **{c: round(colours[c] / len(rows), 3) for c in ("green", "yellow", "red")}}


def evaluation_set(models: Models, part: str = "hepsi") -> dict:
    store = MemoryStore()
    store.open()
    results = degerlendir.calistir(degerlendir.sec(degerlendir.oku(), part), Moderator(store, models=models))
    agree = [r for r in results if r["beklenen"] == r["gelen"]]
    return {"part": part, "decisions": len(results), "agree": len(agree), "share": round(len(agree) / len(results), 4),
            "per_platform": {p: round(sum(r["beklenen"] == r["gelen"] for r in results if r["platform"] == p)
                                      / sum(r["platform"] == p for r in results), 4) for p in degerlendir.PLATFORMLAR},
            "misses": [f"{r['id']} {r['platform']}: {r['beklenen']} -> {r['gelen']} ({r['metin'][:50]})"
                       for r in results if r["beklenen"] != r["gelen"]]}


def scorecard(r: dict) -> list[tuple[str, str, str, bool | None]]:
    """(target, measured, goal, met) rows, in the PDF's order."""
    t = r["test"]["platforms"][HEADLINE]
    split = "validation split" if r.get("dev") else "test split"
    inn = r["innocent"]
    blocked = {p: len(inn[p]["blocked"]) for p in PLATFORMS}
    rows = [
        (f"Harmful messages caught ({split}, demo_sosyal)", f"{t['harmful_caught']:.1%}", ">= 85 %",
         t["harmful_caught"] >= GOALS["harmful_caught"]),
        (f"False alarms: harmless held or blocked ({split}, demo_sosyal)", f"{t['harmless_false_alarm']:.1%}",
         "<= 5 %", t["harmless_false_alarm"] <= GOALS["harmless_false_alarm"]),
        ("Per source (harmful caught / false alarms)", "; ".join(
            f"{s} {v['harmful_caught']:.0%} / {v['harmless_false_alarm']:.1%}" for s, v in r["test"]["by_source"].items()),
         "reported", None),
    ]
    if r.get("youtube"):
        rows.append(("Unseen platform: YouTube (harmful caught / false alarms)",
                     f"{r['youtube']['platforms'][HEADLINE]['harmful_caught']:.1%} / "
                     f"{r['youtube']['platforms'][HEADLINE]['harmless_false_alarm']:.1%}", "reported", None))
    rows.append(
        (f"Innocent sentences blocked (of {inn['sentences']})", ", ".join(f"{p} {n}" for p, n in blocked.items()),
         "none", not any(blocked.values())))
    if r.get("gray_zone"):
        rows.append(("Gray zone in yellow", f"{r['gray_zone']['yellow']:.0%} (green {r['gray_zone']['green']:.0%}, "
                                            f"red {r['gray_zone']['red']:.0%})", "most", r["gray_zone"]["yellow"] > 0.5))
    rows += [
        ("Category accuracy, human labels (Model 2)", f"{r['categories']['model2_accuracy']:.1%}", ">= 75 %",
         r["categories"]["model2_accuracy"] >= GOALS["category_accuracy"]),
        ("Time per message in process (p50 / p99)", f"{r['test']['ms_per_message']['p50']:.2f} / "
                                                     f"{r['test']['ms_per_message']['p99']:.2f} ms", "< 10 ms",
         r["test"]["ms_per_message"]["p99"] < GOALS["ms_per_message"]),
    ]
    if r.get("simulation"):
        sim = r["simulation"][HEADLINE]
        rows += [
        ("1:1 simulation: restricted, of those who should be (demo_sosyal)", f"{sim['restricted_of_should']:.0%}",
         ">= 90 %", sim["restricted_of_should"] >= simulate.SHOULD_AT_LEAST),
        ("1:1 simulation: restricted, of the others (by harmless messages alone)",
         f"{sim['restricted_of_should_not']:.0%} ({sim['restricted_of_should_not_without_a_harmful_message']:.0%})",
         "<= 5 %", sim["restricted_of_should_not"] <= simulate.SHOULD_NOT_AT_MOST),
        ("Bullying conversations where the victim stops getting the bully's messages",
         sim["bullying_conversations_protected"], "every one", sim["bullying_all_protected"]),
        ]
    for e in r["evaluation_set"]:
        rows.append((f"The team's evaluation set, {e['part']} part (3 platforms)",
                     f"{e['agree']} of {e['decisions']} ({e['share']:.1%})", "reported", None))
    return rows


def markdown(r: dict) -> str:
    lines = [f"# Results\n\nMeasured by `measure.py` on {r['machine']['arch']} ({r['machine'].get('generation') or 'not IBM Z'}),"
             f" {r['when']}, models: {r['models']['status']['model1']} / {r['models']['status']['model2']}"
             + (f" (trained {r['models']['version']['trained']})" if r["models"].get("version") else "")
             + f". {'Validation' if r.get('dev') else 'Test'} split: {r['test']['messages']:,} messages.\n",
             "| Target (PDF section 9) | Measured | Goal | Met |", "|---|---|---|---|"]
    for name, value, goal, met in scorecard(r):
        lines.append(f"| {name} | {value} | {goal} | {'yes' if met else 'no' if met is False else ''} |")
    lines += ["", "Per platform (test split): harmful caught / false alarms (held or blocked) / harmless censored", ""]
    for p, v in r["test"]["platforms"].items():
        lines.append(f"- `{p}`: {v['harmful_caught']:.1%} / {v['harmless_false_alarm']:.1%} / {v['harmless_censored']:.1%}")
    if r.get("simulation"):
        lines += ["", "1:1 simulation per platform: restricted of those who should be / of the others (by harmless "
                  "messages alone) / bullying conversations protected", ""]
    for p, s in (r.get("simulation") or {}).items():
        lines.append(f"- `{p}`: {s['restricted_of_should']:.0%} / {s['restricted_of_should_not']:.0%} "
                     f"({s['restricted_of_should_not_without_a_harmful_message']:.0%}) / "
                     f"{s['bullying_conversations_protected']}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="3,000 test messages instead of all")
    ap.add_argument("--markdown", type=Path, help="also write the scorecard as Markdown")
    ap.add_argument("--out", type=Path, help="the JSON report (default veri/measure_report.json)")
    ap.add_argument("--dev", action="store_true", help="tuning: validation split and the evaluation set's dev part "
                                                         "only, nothing held out (use with SAFENET_MODELS_DIR=models_dev)")
    args = ap.parse_args()

    started = time.time()
    models = Models()
    judge = Judge(models)
    print(f"models: {models.status()} {models.version() or ''}")
    if args.dev and models.version() and "dev" not in models.version():
        print("!! --dev with models that were trained on the validation split: use SAFENET_MODELS_DIR=models_dev")
    if not args.dev and models.version() and "dev" in models.version():
        print("!! models_dev measured on held-out data: the reported numbers are for the models in models/")
    report = {"when": time.strftime("%Y-%m-%d %H:%M"), "machine": {**ibmz.info(), "python": machine.python_version()},
              "models": {"status": models.status(), "version": models.version()}, "dev": args.dev}
    print("validation split ..." if args.dev else "test split ...", flush=True)
    report["test"], judged_test = test_split(judge, args.quick, args.dev)
    report["categories"] = categories(models, judged_test)
    report["innocent"] = innocent(judge)
    if args.dev:
        report["evaluation_set"] = [evaluation_set(models, "dev")]
    else:
        print("YouTube, gray zone, evaluation set, 1:1 simulation ...", flush=True)
        report["youtube"] = youtube(judge)
        report["gray_zone"] = gray_zone(judge)
        report["evaluation_set"] = [evaluation_set(models, "dev"), evaluation_set(models, "test")]
        report["simulation"] = {p: {k: v for k, v in s.items() if k != "_rows"} for p, s in simulate.run(models).items()}
    report["minutes"] = round((time.time() - started) / 60, 1)

    name = "measure_report" + ("_dev" if args.dev else "") + ("_quick" if args.quick else "")
    out = args.out or DATA / f"{name}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print()
    for name, value, goal, met in scorecard(report):
        mark = {True: "OK ", False: "NO ", None: "   "}[met]
        print(f"{mark}{name:72} {value:>26}   goal {goal}")
    if args.markdown:
        args.markdown.write_text(markdown(report), encoding="utf-8")
        print(f"-> {args.markdown}")
    print(f"-> {out} ({report['minutes']} min)")


if __name__ == "__main__":
    main()
