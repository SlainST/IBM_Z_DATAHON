"""YouTube adapter: runs a video's comments through SafeNet before they are shown, and reports what a viewer
would see and which commenters the hidden points flag.

    SAFENET_KEY=... python client/youtube_comments.py comments.json --video dQw4w9WgXcQ
    SAFENET_KEY=... python client/youtube_comments.py comments.csv --only-flagged

Input, either:
  - the JSON of the YouTube Data API v3 commentThreads.list call (part=snippet,replies), saved to a file
    (or several pages as a list), or
  - a CSV with the columns author, text and optionally reply_to (the author the comment answers).
A top-level comment is scored for its author only (group_id = the video). A reply is one-to-one: it goes to the
author it answers, so a commenter who keeps attacking the same person stops reaching them (A -> B relation).
Authors become pseudonymous ids (yt_<hash>) before anything leaves this PC.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safenet_client import SafeNet  # noqa: E402


def from_api(data) -> list[dict]:
    """commentThreads.list response(s) -> [{"id", "author", "text", "reply_to"}]."""
    pages = data if isinstance(data, list) else [data]
    out = []
    for page in pages:
        for item in page.get("items", []):
            top = item["snippet"]["topLevelComment"]
            author = top["snippet"].get("authorDisplayName", "?")
            out.append({"id": top.get("id", item.get("id")), "author": author,
                        "text": top["snippet"].get("textOriginal") or top["snippet"].get("textDisplay", ""),
                        "reply_to": None})
            for reply in item.get("replies", {}).get("comments", []):
                out.append({"id": reply.get("id"), "author": reply["snippet"].get("authorDisplayName", "?"),
                            "text": reply["snippet"].get("textOriginal") or reply["snippet"].get("textDisplay", ""),
                            "reply_to": author})
    return out


def from_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{"id": f"row{i}", "author": r.get("author") or "?", "text": r.get("text") or r.get("metin") or "",
                 "reply_to": r.get("reply_to") or None} for i, r in enumerate(csv.DictReader(f), 2)]


def pseudonym(name: str) -> str:
    return "yt_" + hashlib.sha256(name.encode()).hexdigest()[:12]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("comments", type=Path, help="commentThreads.list JSON or a CSV (author, text[, reply_to])")
    ap.add_argument("--video", default="video", help="the video id: SafeNet's group for these comments")
    ap.add_argument("--url", default=os.getenv("SAFENET_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--only-flagged", action="store_true", help="print only comments not shown as written")
    args = ap.parse_args()
    key = os.getenv("SAFENET_KEY")
    if not key:
        sys.exit("set SAFENET_KEY to the platform's API key (it is never printed)")

    if args.comments.suffix.lower() == ".json":
        comments = from_api(json.loads(args.comments.read_text(encoding="utf-8")))
    else:
        comments = from_csv(args.comments)
    sn = SafeNet(args.url, key=key)
    group = f"yt_{args.video}"
    decisions, flagged_authors = Counter(), Counter()
    for c in comments:
        if not c["text"].strip():
            continue
        a = sn.check(pseudonym(c["author"]), c["text"][:2000], group=group, message_id=f"{group}_{c['id']}",
                     recipient=pseudonym(c["reply_to"]) if c["reply_to"] else None)
        decisions[a["decision"]] += 1
        if a["decision"] != "allow":
            flagged_authors[c["author"]] += 1
        if args.only_flagged and a["decision"] == "allow":
            continue
        shown = a["recipient_sees"] if a["decision"] in ("allow", "censor") else f"[{a['decision']}: {a['reason']}]"
        to = f" (reply to {c['reply_to']})" if c["reply_to"] else ""
        print(f"{c['author']}{to}: {shown}")

    print(f"\n{sum(decisions.values())} comments: " + ", ".join(f"{d} {n}" for d, n in decisions.most_common()))
    for author, n in flagged_authors.most_common(10):
        standing = sn.user(group, pseudonym(author))
        print(f"  {author}: {n} not shown as written, points {standing['points']}, {standing['level']}")


if __name__ == "__main__":
    main()
