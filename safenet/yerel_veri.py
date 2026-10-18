"""veri/ for a laptop, from the CSVs in the repository root, when veri/ham/ (the raw downloads) is not there.

    python yerel_veri.py      # ~2 min: veri/birlesik_veri.csv, veri/youtube_test.csv, then sohbet_simulasyonu.py

The root birlesik_veri.csv is veri_hazirla.py's output without the id, grup_id and hedefli columns; this adds them
(grup_id with the same near-duplicate grouping, benzerlik.gruplari_bul) and keeps the train / test split as it is.
Without the raw Wikipedia file train.py trains without graded labels (v3, not v4), and without
veri/belirsiz_test.csv measure.py skips the gray zone. Models trained on a laptop only load on a little-endian
machine (models/README.md): use them to compare changes here, and measure the numbers you report on the server.
"""
import subprocess
import sys
from pathlib import Path

import pandas as pd

from benzerlik import gruplari_bul
from temizlik import hedefli_mi

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DATA = ROOT / "veri"


def main():
    DATA.mkdir(exist_ok=True)
    df = pd.read_csv(REPO / "birlesik_veri.csv")
    df["metin"] = df["metin"].fillna("").astype(str)
    df.insert(0, "id", range(len(df)))
    print(f"{len(df)} messages, grouping near-duplicates...")
    df["grup_id"] = gruplari_bul(df["metin"].tolist())
    df["hedefli"] = df["metin"].map(hedefli_mi).astype(int)
    df.to_csv(DATA / "birlesik_veri.csv", index=False)
    print("  " + ", ".join(f"{k} {v}" for k, v in df["bolum"].value_counts().items()))
    pd.read_csv(REPO / "youtube_test.csv").to_csv(DATA / "youtube_test.csv", index=False)
    subprocess.run([sys.executable, "sohbet_simulasyonu.py"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
