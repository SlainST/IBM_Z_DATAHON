"""SafeNet stage 2: train Model 1 (harmful or not) and Model 2 (category), and measure both.

Input:   veri/birlesik_veri.csv       output of veri_hazirla.py; "metin" is already temizlik.temizle() output
Output:  models/model1.joblib         harm:     predict_proba(texts)[:, 1] = probability of harmful, classes_ = [0, 1]
         models/model2.joblib         category: predict(texts) = insult | gender | religion | race | sexual | threat
         models/model_info.json       when, where and with what the pair was trained; the API refuses a pair
                                      trained on the other byte order (safenet/ml/models.py)
         veri/training_report.json    every metric and the threshold proposals (gitignored)

Both files are plain scikit-learn Pipelines (joblib.dump(pipeline)): the team's API (safenet/ml/models.py)
loads them and calls predict_proba / predict directly.

Run it ON THE SERVER: a file saved with another scikit-learn / numpy than the server's (1.4.1.post1 / 1.26.4)
may not load in the API.
    python train.py                    # full run (server: ~15 min, one CPU; run it with nice)
    python train.py --sample 20000     # quick trial, writes models_sample/
    python train.py --no-augment       # without the synthetic sentences of augment.py (the first run, v1)
    python train.py --hard-labels      # without the annotators' shares (v3)
    python train.py --evaluate         # no training: measure models/ again -> veri/evaluation_report.json

Graded labels (v4): every Wikipedia comment was labelled by about ten people, and veri/ham/toxicity_parsed_dataset.csv
(the file veri_hazirla.py reads) keeps the share who called it toxic. Where they split (between 30 % and 70 %),
Model 1 learns that share instead of the majority's 0 or 1: such a comment is in the training rows twice, harmful
with weight = share and harmless with weight = 1 - share (the log-loss of a soft label). Validation and test keep
the majority label. Without the raw file, or with --hard-labels, every label is hard (v3).

Synthetic sentences (augment.py) are added to the training rows only, never to validation or test: neutral
sentences for identity words the data made look harmful, threats (only ~480 real ones), swearing at things versus
insults aimed at the reader, and victims' accounts. The held-out checks at the end use other templates and words,
and the PDF example; the team's evaluation set (degerlendirme_seti.csv) is never trained on either.

Overfitting guards:
  - The test split (bolum == "test") is used once, at the very end.
  - C (regularization) and the threshold proposals are chosen on a validation split carved out of the training
    split by grup_id, so near-duplicate messages never sit on both sides (benzerlik.py).
  - Features come from HashingVectorizer: no vocabulary in memory or in the file, memory stays constant.

Why no TF-IDF: TfidfTransformer rebuilds a 1M x 1M idf matrix on every call, so one predict took ~40 ms.
Plain hashed features (binary, l2-normalized) scored the same PR-AUC (0.924 vs 0.922 on a 40k-message trial)
at ~0.5 ms per call and keep the model files small: the API scores every message live.
"""
import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score, precision_recall_fscore_support,
                             roc_auc_score)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import FeatureUnion, Pipeline

import augment
import degerlendir
import temizlik

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "veri"

# Columns of veri/birlesik_veri.csv (veri_hazirla.py)
ID, TEXT, HARMFUL, CATEGORY_TR, CATEGORY_SOURCE, SOURCE, GROUP, SPLIT = (
    "id", "metin", "zararli", "tur", "tur_kaynagi", "kaynak", "grup_id", "bolum")
WIKIPEDIA_RAW = DATA / "ham" / "toxicity_parsed_dataset.csv"   # ed_label_1 = share of annotators who said toxic
GRADED_BETWEEN = (0.3, 0.7)      # annotators split between these shares: Model 1 learns the share (soft label)
# Dataset category names -> the API's category names. Model 2 predicts the API names directly.
CATEGORIES = {"genel_hakaret": "insult", "cinsiyet": "gender", "din": "religion", "irk": "race",
              "cinsel": "sexual", "tehdit": "threat"}
LABELS = list(CATEGORIES.values())

# Regularization: small C = simpler model (less overfitting), large C = follows the training data closer
C_CANDIDATES_MODEL1 = [2.0, 8.0, 32.0]
C_CANDIDATES_MODEL2 = [8.0, 32.0, 128.0]
RULE_WEIGHT = 0.5                # in Model 2, rows whose category came from a keyword rule or a template count half
WEAK_SOURCES = ("kural", "sentetik")
BLOCK_PRECISION = 0.95           # block thresholds: at least 95 % of what gets blocked must really be harmful
THRESHOLDS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]
PLATFORMS = ("demo_okul", "demo_sosyal", "demo_oyun")


def elapsed(start: float) -> str:
    return f"{time.time() - start:.0f} s"


# --- Models ----------------------------------------------------------------------------------------
def features(bits: int) -> FeatureUnion:
    """Words (unigrams + bigrams) and character n-grams (2-5, within word boundaries), 2**bits buckets each.
    binary: a word counts once however often it repeats; l2: long and short messages are on the same scale."""
    def branch(**kw):
        return HashingVectorizer(n_features=2 ** bits, alternate_sign=False, binary=True, norm="l2", **kw)
    return FeatureUnion([("words", branch(analyzer="word", ngram_range=(1, 2), token_pattern=r"(?u)\b\w+\b")),
                         ("chars", branch(analyzer="char_wb", ngram_range=(2, 5)))])


def classifier(C: float) -> LogisticRegression:
    """liblinear: fast on sparse, high-dimensional text features; one-vs-rest for Model 2's six categories.
    (lbfgs needed ~2 s per iteration here for Model 2.)"""
    return LogisticRegression(C=C, solver="liblinear", max_iter=300)


def no_weights(df: pd.DataFrame):
    return None


def row_weights(df: pd.DataFrame) -> np.ndarray:
    return df["weight"].to_numpy()


def annotator_shares() -> pd.Series:
    """id -> share of the annotators who called a Wikipedia comment toxic, from the raw file veri_hazirla.py read
    (the id is made the same way there: md5 of "wikipedia|" + the raw text). Empty without the file."""
    if not WIKIPEDIA_RAW.exists():
        print(f"   {WIKIPEDIA_RAW} not found: hard labels only")
        return pd.Series(dtype=float)
    raw = pd.read_csv(WIKIPEDIA_RAW, usecols=["Text", "ed_label_1"])
    ids = [hashlib.md5(f"wikipedia|{t}".encode()).hexdigest()[:12] for t in raw["Text"].astype(str)]
    return pd.Series(raw["ed_label_1"].to_numpy(), index=ids).groupby(level=0).mean()


def graded(df: pd.DataFrame, shares: pd.Series) -> pd.DataFrame:
    """Adds a "weight" column; a Wikipedia comment whose annotators split (GRADED_BETWEEN) becomes two rows, harmful
    with weight = share and harmless with weight = 1 - share. Labels we fixed by hand stay hard."""
    q = df[ID].map(shares).where((df[SOURCE] == "wikipedia") & (df[CATEGORY_SOURCE] != "duzeltme"))
    soft = q.between(*GRADED_BETWEEN, inclusive="neither")
    return pd.concat([df[~soft].assign(weight=1.0),
                      df[soft].assign(**{HARMFUL: 1, "weight": q[soft]}),
                      df[soft].assign(**{HARMFUL: 0, "weight": 1 - q[soft]})])


def category_weights(df: pd.DataFrame) -> np.ndarray:
    """Rows labelled by a keyword rule or a template count half; then every category gets the same total weight
    (threat has 481 rows, insult 13 thousand)."""
    w = np.where(df[CATEGORY_SOURCE].isin(WEAK_SOURCES), RULE_WEIGHT, 1.0)
    total = pd.Series(w, index=df.index).groupby(df["category"]).transform("sum").to_numpy()
    return w * len(df) / (df["category"].nunique() * total)


def split_validation(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """20 % of the training split for validation, by grup_id."""
    inner, held = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42).split(df, groups=df[GROUP]))
    return df.iloc[inner], df.iloc[held]


def choose_c(name, train, valid, target, weights, score, bits, candidates):
    """Extracts the features once, fits one model per C, returns the best C on validation and that model."""
    start = time.time()
    feats = features(bits)
    A = feats.fit_transform(train[TEXT])
    B = feats.transform(valid[TEXT])
    print(f"   features: {A.shape[0]} x {A.shape[1]}, {A.nnz / A.shape[0]:.0f} non-zero per message ({elapsed(start)})")
    scores, models = {}, {}
    for C in candidates:
        start = time.time()
        clf = classifier(C).fit(A, train[target], sample_weight=weights(train))
        scores[C] = round(float(score(clf, B, valid)), 4)
        models[C] = Pipeline([("features", feats), ("clf", clf)])
        print(f"   {name} C={C}: {scores[C]:.4f} ({elapsed(start)})")
    best = max(scores, key=scores.get)
    return best, scores, models[best]


def fit_final(train, target, weights, C, bits) -> Pipeline:
    start = time.time()
    model = Pipeline([("features", features(bits)), ("clf", classifier(C))])
    model.fit(train[TEXT], train[target], clf__sample_weight=weights(train))
    print(f"   fitted on {len(train)} messages ({elapsed(start)})")
    return model


# --- Metrics ---------------------------------------------------------------------------------------
def binary_metrics(y, p, threshold: float = 0.5) -> dict:
    y, p = np.asarray(y), np.asarray(p)
    flagged = p >= threshold
    prec, rec, f1, _ = precision_recall_fscore_support(y, flagged, average="binary", zero_division=0)
    return {"roc_auc": round(roc_auc_score(y, p), 4), "pr_auc": round(average_precision_score(y, p), 4),
            "threshold": threshold, "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
            "flagged_rate": round(float(flagged.mean()), 4), "harmful_rate": round(float(y.mean()), 4)}


def threshold_table(y, score) -> list[dict]:
    """Per threshold: precision (share of flagged that is really harmful) and recall (share of harmful that is flagged)."""
    y, score = np.asarray(y), np.asarray(score)
    rows = []
    for t in THRESHOLDS:
        s = score >= t
        rows.append({"threshold": t, "precision": round(float(y[s].mean()), 4) if s.any() else None,
                     "recall": round(float(s[y == 1].mean()), 4), "flagged": int(s.sum())})
    return rows


def lowest_precise_threshold(y, score, target=BLOCK_PRECISION, min_flagged=30) -> dict | None:
    """The lowest threshold whose precision reaches the target (with at least min_flagged messages above it)."""
    y, score = np.asarray(y), np.asarray(score)
    for t in np.round(np.arange(0.30, 0.991, 0.01), 2):
        s = score >= t
        if s.sum() >= min_flagged and y[s].mean() >= target:
            return {"threshold": float(t), "precision": round(float(y[s].mean()), 4), "flagged": int(s.sum()),
                    "recall": round(float(s[y == 1].mean()), 4)}
    return None


def best_f1_threshold(y, score) -> dict:
    y, score = np.asarray(y), np.asarray(score)
    best = None
    for t in np.round(np.arange(0.20, 0.91, 0.01), 2):
        s = score >= t
        prec = y[s].mean() if s.any() else 0.0
        rec = s[y == 1].mean()
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        if best is None or f1 > best["f1"]:
            best = {"threshold": float(t), "f1": round(float(f1), 4), "precision": round(float(prec), 4),
                    "recall": round(float(rec), 4)}
    return best


# --- The API's own path ----------------------------------------------------------------------------
def api_analyze(model1, model2, texts, game_platform=False) -> list:
    """Exactly what the team's API does with a message: split into sentences, score every sentence and its
    wordless version with Model 1, give a category with Model 2 (safenet.engine.analysis.Analyzer).
    game_platform=True: game words in a game context are taken out first, as on demo_oyun."""
    from safenet.engine.analysis import Analyzer
    from safenet.ml.models import Models

    models = Models()
    models.model1, models.model2 = model1, model2
    analyzer = Analyzer(models)
    return [analyzer._analyze(t, game_platform, 1, True) for t in texts]


def api_verdicts(analyses, platform_id: str) -> list:
    from safenet import settings
    from safenet.engine.decision import judge

    a = settings.for_platform(platform_id)
    return [judge(x, a) for x in analyses]


def api_scores(analyses, y) -> pd.DataFrame:
    """Per message: the worst sentence's harm and wordless score, and the harm / wordless score of its
    threat and hate (race, religion, gender) sentences: the numbers the API's thresholds are applied to."""
    rows = []
    for x in analyses:
        rows.append((max(s.harm for s in x.sentences),
                     max(s.wordless for s in x.sentences),
                     max((s.harm for s in x.sentences if s.category == "threat"), default=0.0),
                     max((s.wordless for s in x.sentences if s.category in ("race", "religion", "gender")), default=0.0)))
    out = pd.DataFrame(rows, columns=["harm", "wordless", "threat", "hate"])
    out["y"] = np.asarray(y)
    return out


def decision_shares(verdicts, y) -> dict:
    """Share of each decision for really harmful and really harmless messages."""
    df = pd.DataFrame({"decision": [v.decision for v in verdicts], "y": np.asarray(y)})
    table = pd.crosstab(df["y"].map({0: "harmless", 1: "harmful"}), df["decision"], normalize="index").round(4)
    return {row: table.loc[row].to_dict() for row in table.index}


# --- Run -------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="quick trial: use this many training rows")
    ap.add_argument("--api-eval", type=int, default=12000,
                    help="at most this many messages go through the API's path (validation and test each)")
    ap.add_argument("--no-augment", action="store_true", help="train without the synthetic sentences of augment.py")
    ap.add_argument("--hard-labels", action="store_true", help="Model 1 without the Wikipedia annotators' shares (v3)")
    ap.add_argument("--evaluate", action="store_true",
                    help="no training: measure the saved models again (e.g. after changing the API's rules)")
    args = ap.parse_args()
    out_dir = ROOT / ("models_sample" if args.sample else "models")
    out_dir.mkdir(exist_ok=True)
    report = {"versions": {"sklearn": sklearn.__version__, "numpy": np.__version__,
                           "python": platform.python_version(), "machine": platform.machine()},
              "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    t0 = time.time()

    print("1) Reading data")
    data = pd.read_csv(DATA / "birlesik_veri.csv")
    data["category"] = data[CATEGORY_TR].map(CATEGORIES)
    train, test = data[data[SPLIT] == "egitim"], data[data[SPLIT] == "test"]
    if args.sample:
        train = train.sample(n=min(args.sample, len(train)), random_state=42)
        test = test.sample(n=min(args.sample // 4, len(test)), random_state=42)
    inner, valid = split_validation(train)
    yt = pd.read_csv(DATA / "youtube_test.csv")
    print(f"   training {len(train)} (inner {len(inner)} + validation {len(valid)}), test {len(test)}")
    report["data"] = {"training": len(train), "validation": len(valid), "test": len(test)}

    if args.evaluate:
        print(f"2-5) No training: measuring the saved models in {out_dir}")
        model1, model2 = joblib.load(out_dir / "model1.joblib"), joblib.load(out_dir / "model2.joblib")
    else:
        model1, model2 = fit_models(args, train, inner, valid, test, yt, report, out_dir)
    evaluate(model1, model2, test, yt, report, args.api_eval)

    report["minutes"] = round((time.time() - t0) / 60, 1)
    name = "evaluation_report" if args.evaluate else "training_report"
    target = DATA / (f"{name}_sample.json" if args.sample else f"{name}.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done in {report['minutes']} min. Report: {target}")


def save(folder: Path, model1, model2, info: dict):
    folder.mkdir(exist_ok=True)
    joblib.dump(model1, folder / "model1.joblib", compress=3)
    joblib.dump(model2, folder / "model2.joblib", compress=3)
    (folder / "model_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")


def fit_models(args, train, inner, valid, test, yt, report, out_dir):
    """Steps 2-5: choose C on validation, propose thresholds, fit and save the final pair."""
    synthetic = pd.DataFrame(columns=[TEXT, HARMFUL, "category"])
    if not args.no_augment:
        innocent = pd.read_csv(ROOT / "karistirilabilir_kelimeler.csv")["ornek_masum_cumle"]
        evaluated = {temizlik.temizle(t) for t in [r["metin"] for r in degerlendir.oku()] + innocent.tolist()}
        synthetic, info = augment.build(train, set(test[TEXT]) | set(yt[TEXT]) | evaluated, TEXT, HARMFUL)
        synthetic = synthetic.assign(**{CATEGORY_SOURCE: "sentetik", SOURCE: "sentetik", GROUP: -1, SPLIT: "egitim"})
        report["augmentation"] = info
        print(f"   + synthetic (training only), {info['harmful']} of them harmful: "
              + ", ".join(f"{k} {v}" for k, v in info["per_kind"].items()))
    inner_fit, train_fit = pd.concat([inner, synthetic]), pd.concat([train, synthetic])
    shares = pd.Series(dtype=float) if args.hard_labels else annotator_shares()
    inner1, train1 = graded(inner_fit, shares), graded(train_fit, shares)
    soft = int((train1["weight"] < 1).sum() // 2)
    print(f"   Model 1: {soft} Wikipedia comments with split annotators trained on their share (soft labels)")

    print("2) Model 1 (harmful?): choosing C on validation PR-AUC")
    c1, c1_scores, model1_valid = choose_c(
        "model1", inner1, valid, HARMFUL, row_weights,
        lambda clf, B, df: average_precision_score(df[HARMFUL], clf.predict_proba(B)[:, 1]), bits=20,
        candidates=C_CANDIDATES_MODEL1)
    report["model1"] = {"C_candidates_pr_auc": c1_scores, "C": c1, "soft_labels": soft}

    print("3) Model 2 (category): harmful messages only, choosing C on validation macro F1")
    inner2, valid2 = inner_fit[inner_fit[HARMFUL] == 1], valid[valid[HARMFUL] == 1]
    c2, c2_scores, model2_valid = choose_c(
        "model2", inner2, valid2, "category", category_weights,
        lambda clf, B, df: f1_score(df["category"], clf.predict(B), average="macro"), bits=19,
        candidates=C_CANDIDATES_MODEL2)
    report["model2"] = {"C_candidates_macro_f1": c2_scores, "C": c2}

    print("4) Threshold proposals: validation messages through the API's path")
    start = time.time()
    valid_api = valid.sample(n=min(args.api_eval, len(valid)), random_state=42)
    sv = api_scores(api_analyze(model1_valid, model2_valid, valid_api[TEXT].tolist()), valid_api[HARMFUL])
    proposals = {
        "sari_esigi": best_f1_threshold(sv["y"], sv["harm"]),
        "cok_kotu_esigi": lowest_precise_threshold(sv["y"], sv["wordless"]),
        "tehdit_esigi": lowest_precise_threshold(sv["y"], sv["threat"], min_flagged=10),
        "nefret_esigi": lowest_precise_threshold(sv["y"], sv["hate"]),
    }
    report["threshold_proposals"] = {
        "measured_on": f"validation, {len(valid_api)} messages; block thresholds aim at precision >= {BLOCK_PRECISION}",
        **proposals,
        "worst_sentence_harm_table": threshold_table(sv["y"], sv["harm"]),
        "worst_sentence_wordless_table": threshold_table(sv["y"], sv["wordless"])}
    summary = ", ".join(f"{k}={v['threshold'] if v else None}" for k, v in proposals.items())
    print(f"   {summary} ({elapsed(start)})")

    print(f"5) Final models on the whole training split (Model 1 C={c1}, Model 2 C={c2})")
    model1 = fit_final(train1, HARMFUL, row_weights, c1, bits=20)
    model2 = fit_final(train_fit[train_fit[HARMFUL] == 1], "category", category_weights, c2, bits=19)
    info = {"trained": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "machine": platform.machine(), "byteorder": sys.byteorder,
            "python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__,
            "model1": {"C": c1, "bits": 20, "soft_labels": soft, "graded_between": list(GRADED_BETWEEN)},
            "model2": {"C": c2, "bits": 19},
            "training_messages": len(train_fit), "synthetic": report.get("augmentation", {}).get("per_kind", {})}
    save(out_dir, model1, model2, info)
    # The pair that never saw the validation split: measure.py --dev tunes rules and thresholds on it
    save(out_dir.with_name(out_dir.name + "_dev"), model1_valid, model2_valid,
         {**info, "training_messages": len(inner_fit), "dev": "fit on the inner split; validation is held out"})
    report["files_mb"] = {f.name: round(f.stat().st_size / 1e6, 1)
                          for f in (out_dir / "model1.joblib", out_dir / "model2.joblib")}
    print(f"   saved {report['files_mb']} MB and model_info.json -> {out_dir}")
    return model1, model2


def evaluate(model1, model2, test, yt, report, api_eval):
    """Steps 6-10: the test split (once), YouTube, and the held-out sentences of augment.py."""
    print("6) Test (once): message level")
    p = model1.predict_proba(test[TEXT])[:, 1]
    report["test_model1"] = binary_metrics(test[HARMFUL], p)
    pos = {idx: i for i, idx in enumerate(test.index)}
    report["test_model1"]["by_source"] = {
        src: {"messages": int(len(g)), "harmful_rate": round(float(g[HARMFUL].mean()), 3),
              "roc_auc": round(roc_auc_score(g[HARMFUL], p[[pos[i] for i in g.index]]), 4)
              if g[HARMFUL].nunique() > 1 else None}
        for src, g in test.groupby(SOURCE)}
    report["test_model1"]["threshold_table"] = threshold_table(test[HARMFUL], p)
    harmful = test[test[HARMFUL] == 1]
    pred = model2.predict(harmful[TEXT])
    prec, rec, f1, n = precision_recall_fscore_support(harmful["category"], pred, labels=LABELS, zero_division=0)
    report["test_model2"] = {
        "macro_f1": round(f1_score(harmful["category"], pred, average="macro"), 4),
        "categories": {c: {"precision": round(prec[i], 3), "recall": round(rec[i], 3), "f1": round(f1[i], 3),
                           "messages": int(n[i])} for i, c in enumerate(LABELS)},
        "confusion": {"rows_true_cols_predicted": LABELS,
                      "matrix": confusion_matrix(harmful["category"], pred, labels=LABELS).tolist()}}
    print(f"   Model 1: ROC-AUC {report['test_model1']['roc_auc']}, F1 {report['test_model1']['f1']} at 0.5;"
          f"  Model 2: macro F1 {report['test_model2']['macro_f1']}")

    print("7) Test (once): through the API's path, decisions per platform")
    start = time.time()
    test_api = test.sample(n=min(api_eval, len(test)), random_state=42)
    analyses = api_analyze(model1, model2, test_api[TEXT].tolist())
    game = api_analyze(model1, model2, test_api[TEXT].tolist(), game_platform=True)
    st = api_scores(analyses, test_api[HARMFUL])
    report["test_api"] = {
        "messages": len(test_api),
        "worst_sentence_harm": binary_metrics(st["y"], st["harm"]),
        "decisions": {"demo_okul": decision_shares(api_verdicts(analyses, "demo_okul"), test_api[HARMFUL]),
                      "demo_sosyal": decision_shares(api_verdicts(analyses, "demo_sosyal"), test_api[HARMFUL]),
                      "demo_oyun": decision_shares(api_verdicts(game, "demo_oyun"), test_api[HARMFUL])}}
    print(f"   ({elapsed(start)})")

    print("8) External test: YouTube comments (never seen in training)")
    report["youtube_model1"] = binary_metrics(yt[HARMFUL], model1.predict_proba(yt[TEXT])[:, 1])
    yt_analyses = api_analyze(model1, model2, yt[TEXT].tolist())
    report["youtube_api"] = {pid: decision_shares(api_verdicts(yt_analyses, pid), yt[HARMFUL])
                             for pid in ("demo_okul", "demo_sosyal")}

    print("9) Held-out checks (never trained on): identity words in neutral and hateful sentences")
    ids = augment.IDENTITIES_EVAL

    def mean_harm(templates):
        texts = [temizlik.temizle(t.format(w)) for t in templates for w in ids]
        return model1.predict_proba(texts)[:, 1].reshape(len(templates), len(ids)).mean(axis=0)
    neutral, hateful = mean_harm(augment.NEUTRAL_EVAL), mean_harm(augment.HATEFUL_EVAL)
    report["heldout_identity"] = {
        "per_identity": {w: {"neutral": round(float(a), 3), "hateful": round(float(b), 3)}
                         for w, a, b in zip(ids, neutral, hateful)},
        "neutral_mean": round(float(neutral.mean()), 3), "neutral_max": round(float(neutral.max()), 3),
        "neutral_above_0.5": int((neutral > 0.5).sum()), "hateful_mean": round(float(hateful.mean()), 3),
        "hateful_min": round(float(hateful.min()), 3)}
    h = report["heldout_identity"]
    print(f"   neutral mean {h['neutral_mean']} (max {h['neutral_max']}, above 0.5: {h['neutral_above_0.5']} of "
          f"{len(ids)}); hateful mean {h['hateful_mean']} (min {h['hateful_min']})")

    print("10) Held-out threats, look-alikes, harmless and aimed sentences, and examples (demo_sosyal)")
    examples = (augment.HELDOUT_THREATS + augment.HELDOUT_BENIGN + augment.HELDOUT_HARMLESS + augment.HELDOUT_AIMED +
                ["see you tomorrow", "fuck, i missed the bus", "you are a worthless idiot", "i'm a proud muslim",
                 "muslims are terrorists", "i will kill you", "we fed the ducks at the lake",
                 "this game is so fucking hard lol", "go back to your country"])
    groups = (["threat"] * len(augment.HELDOUT_THREATS) + ["look-alike"] * len(augment.HELDOUT_BENIGN)
              + ["harmless"] * len(augment.HELDOUT_HARMLESS) + ["aimed"] * len(augment.HELDOUT_AIMED)
              + ["example"] * 9)
    ex = api_analyze(model1, model2, examples)
    verdicts = api_verdicts(ex, "demo_sosyal")
    report["examples"] = [{"group": g, "text": t, "harm": max(s.harm for s in x.sentences),
                           "wordless": max(s.wordless for s in x.sentences),
                           "categories": [s.category for s in x.sentences], "decision": v.decision, "reason": v.reason}
                          for g, t, x, v in zip(groups, examples, ex, verdicts)]
    threats = [e for e in report["examples"] if e["group"] == "threat"]
    report["heldout_threats_blocked"] = f"{sum(e['decision'] == 'block' for e in threats)} of {len(threats)}"
    report["heldout_lookalikes_blocked"] = (
        f"{sum(e['decision'] == 'block' for e in report['examples'] if e['group'] == 'look-alike')} "
        f"of {len(augment.HELDOUT_BENIGN)}")
    flagged = lambda group: sum(e["reason"] not in (None, "profanity") for e in report["examples"]  # noqa: E731
                                if e["group"] == group)
    report["heldout_harmless_yellow_or_red"] = f"{flagged('harmless')} of {len(augment.HELDOUT_HARMLESS)}"
    report["heldout_aimed_yellow_or_red"] = f"{flagged('aimed')} of {len(augment.HELDOUT_AIMED)}"
    for e in report["examples"]:
        print(f"   {e['group']:10} harm {e['harm']:.2f}  wordless {e['wordless']:.2f}  {e['decision']:6}"
              f" {str(e['reason']):13} {e['categories']}  {e['text'][:55]}")
    print(f"   held-out threats blocked: {report['heldout_threats_blocked']}; "
          f"look-alikes blocked: {report['heldout_lookalikes_blocked']}; harmless yellow or red: "
          f"{report['heldout_harmless_yellow_or_red']}; aimed insults yellow or red: {report['heldout_aimed_yellow_or_red']}")


if __name__ == "__main__":
    main()
