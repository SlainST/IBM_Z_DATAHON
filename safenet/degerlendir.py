"""Değerlendirme seti: her mesajın her demo platformunda beklenen kararını API'nin verdiği kararla karşılaştırır.

Kullanım (safenet klasöründen):
    python degerlendir.py                  # özet: platform ve tür başına isabet, beklenen/gelen tablosu
    python degerlendir.py --hatalar        # tutmayan her satır
    python degerlendir.py --csv sonuc.csv  # satır satır sonuç (Geliştirici 1 kalibrasyon için)

Her mesaj her platformda YENİ bir gönderenle, birebir sohbette denenir (geçmiş puan yok). Bellek deposu
kullanılır: sunucuya ve Postgres'e dokunmaz. models/ klasöründe model yoksa yedek kurallar cevap verir.

degerlendirme_seti.csv sütunları (sadece İngilizce mesajlar):
    id            D001, D002...
    metin         platformun göndereceği mesaj
    tur           temiz, hakaret, tehdit, nefret, alinti_tehdit, kufur_orani...
    zarar         insanın verdiği zarar düzeyi, Model 1'in 'harm' puanı için hedef:
                  yok < 0,40 · orta 0,60-0,75 · yuksek >= 0,90. Bu aralıklar üç profilin eşikleriyle her
                  platformda aynı rengi verir (ayarlar.toml); aradaki gri bölge belirsiz test setinin işi.
    kategori      sarı ve kırmızı mesajlar için beklenen Model 2 kategorisi (insult, gender, religion,
                  race, sexual, threat); boş = bakılmaz
    demo_sosyal, demo_okul, demo_oyun
                  beklenen karar: allow / censor / hold / block
    neden         beklenen 'reason' (docs/API.md); boş = bakılmaz
    ilgili_karar  satırın dayandığı açık karar (docs/DECISION_ENGINE.md, "Choices the PDF left open")
    aciklama      neden bu karar
"""
import argparse
import csv
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from safenet.engine.moderator import Moderator
from safenet.state.store import MemoryStore

DOSYA = Path(__file__).with_name("degerlendirme_seti.csv")
PLATFORMLAR = ("demo_sosyal", "demo_okul", "demo_oyun")
KARARLAR = ("allow", "censor", "hold", "block")


def oku(dosya=DOSYA):
    with open(dosya, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def calistir(satirlar, mod):
    sonuclar = []
    for s in satirlar:
        for p in PLATFORMLAR:
            etiket = uuid.uuid4().hex[:8]
            r = mod.check(p, {"sender_id": f"d_{etiket}", "recipient_id": f"a_{etiket}",
                              "group_id": "degerlendirme", "text": s["metin"]})
            sonuclar.append({
                "id": s["id"], "platform": p, "tur": s["tur"], "zarar": s["zarar"],
                "beklenen": s[p], "gelen": r["decision"],
                "beklenen_neden": s["neden"], "gelen_neden": r["reason"] or "",
                "beklenen_kategori": s["kategori"], "gelen_kategori": r["category"] or "",
                "harm": r["harm"], "wordless_harm": r["wordless_harm"], "metin": s["metin"],
            })
    return sonuclar


def _oran(n, toplam):
    return f"{n}/{toplam} (%{100 * n / toplam:.0f})" if toplam else "-"


def ozet(sonuclar, durum):
    tutan = [r for r in sonuclar if r["beklenen"] == r["gelen"]]
    print(f"Model 1: {durum['model1']} · Model 2: {durum['model2']}")
    print(f"Karar isabeti: {_oran(len(tutan), len(sonuclar))}\n")

    for p in PLATFORMLAR:
        rs = [r for r in sonuclar if r["platform"] == p]
        print(f"  {p:12s} {_oran(sum(r['beklenen'] == r['gelen'] for r in rs), len(rs))}")

    print("\nbeklenen \\ gelen " + "".join(f"{k:>8s}" for k in KARARLAR))
    tablo = Counter((r["beklenen"], r["gelen"]) for r in sonuclar)
    for b in KARARLAR:
        print(f"{b:17s}" + "".join(f"{tablo[(b, g)]:8d}" for g in KARARLAR))

    print("\ntür başına isabet (en kötüden):")
    turler = defaultdict(list)
    for r in sonuclar:
        turler[r["tur"]].append(r["beklenen"] == r["gelen"])
    for tur, ok in sorted(turler.items(), key=lambda t: sum(t[1]) / len(t[1])):
        print(f"  {tur:18s} {_oran(sum(ok), len(ok))}")

    neden = [r for r in tutan if r["beklenen_neden"] and r["gelen"] != "allow"]
    kategori = [r for r in tutan if r["beklenen_kategori"] and r["gelen_kategori"]]
    print(f"\nkarar tutanlarda neden isabeti: {_oran(sum(r['beklenen_neden'] == r['gelen_neden'] for r in neden), len(neden))}")
    print(f"karar tutanlarda kategori isabeti: "
          f"{_oran(sum(r['beklenen_kategori'] == r['gelen_kategori'] for r in kategori), len(kategori))}")


def hatalar(sonuclar):
    print("\nTutmayanlar (id, platform: beklenen -> gelen):")
    for r in sonuclar:
        if r["beklenen"] != r["gelen"]:
            print(f"  {r['id']} {r['platform']:12s} {r['beklenen']:6s} -> {r['gelen']:6s} {r['gelen_neden']:15s} "
                  f"harm {r['harm']:.2f} kelimesiz {r['wordless_harm']:.2f}  {r['metin'][:60]!r}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hatalar", action="store_true", help="tutmayan her satırı yaz")
    ap.add_argument("--csv", type=Path, help="satır satır sonucu bu dosyaya yaz")
    args = ap.parse_args()

    depo = MemoryStore()
    depo.open()
    mod = Moderator(depo)
    sonuclar = calistir(oku(), mod)
    ozet(sonuclar, mod.models.status())
    if args.hatalar:
        hatalar(sonuclar)
    if args.csv:
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(sonuclar[0]))
            w.writeheader()
            w.writerows(sonuclar)
        print(f"\n{len(sonuclar)} satır -> {args.csv}")
