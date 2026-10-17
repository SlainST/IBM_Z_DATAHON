"""Karıştırılabilir kelimeler veri setinde nasıl geçiyor?

Çalıştırma:  python kelime_analizi.py   (1-2 dakika sürer)
Girdi:       karistirilabilir_kelimeler.csv, veri/birlesik_veri.csv
Çıktı:       veri/karistirilabilir_ozet.csv     (her kelime kaç mesajda geçiyor, yüzde kaçı zararlı)
             veri/karistirilabilir_ornekler.csv (bu kelimeleri içeren gerçek mesajlardan örnekler)
"""
import re

import pandas as pd

ORNEK_SAYISI = 25  # her kelime için en fazla 25 zararlı + 25 zararsız örnek


def desen(kelime, kategori):
    """Sadece tam kelimeyi bulur: "class" içindeki "ass"ı saymaz.
    Oyun kelimelerinde killed, dies, shooting gibi halleri de sayar."""
    ekler = r"(?:s|d|ed|ing|er|ers)?" if kategori == "oyun_dili" else r"(?:s)?"
    return r"\b" + re.escape(kelime) + ekler + r"\b"


def main():
    liste = pd.read_csv("karistirilabilir_kelimeler.csv").fillna("")
    veri = pd.read_csv("veri/birlesik_veri.csv")
    metin = veri["metin"].astype(str)

    onbellek = {}  # aynı kelimeyi iki kez aramamak için

    def bul(kelime, kategori):
        d = desen(kelime, kategori)
        if d not in onbellek:
            onbellek[d] = metin.str.contains(d, regex=True)
        return onbellek[d]

    def zararli_yuzde(maske):
        return round(100 * veri.loc[maske, "zararli"].mean(), 1) if maske.any() else None

    ozet, ornekler = [], []
    for i, satir in enumerate(liste.itertuples(index=False), 1):
        print(f"\r{i}/{len(liste)} {satir.kelime:<15}", end="")
        m = bul(satir.kelime, satir.kategori)
        mk = bul(satir.karistirilan, satir.kategori)
        ozet.append({
            **satir._asdict(),
            "kelime_gectigi_mesaj": int(m.sum()),
            "kelime_zararli_yuzde": zararli_yuzde(m),
            "karistirilan_gectigi_mesaj": int(mk.sum()),
            "karistirilan_zararli_yuzde": zararli_yuzde(mk),
        })
        bulunan = veri[m]
        for etiket in (0, 1):
            grup = bulunan[bulunan["zararli"] == etiket]
            grup = grup.sample(min(len(grup), ORNEK_SAYISI), random_state=42)
            ornekler.append(grup.assign(kelime=satir.kelime, kategori=satir.kategori))
    print()

    ozet = pd.DataFrame(ozet)
    ozet.to_csv("veri/karistirilabilir_ozet.csv", index=False, encoding="utf-8-sig")

    ornekler = (pd.concat(ornekler)
                .drop_duplicates(["kelime", "metin"])
                [["kategori", "kelime", "zararli", "tur", "kaynak", "metin"]]
                .sort_values(["kategori", "kelime", "zararli"]))
    ornekler.to_csv("veri/karistirilabilir_ornekler.csv", index=False, encoding="utf-8-sig")

    print(f"Özet:     {len(ozet)} kelime  -> veri/karistirilabilir_ozet.csv")
    print(f"Örnekler: {len(ornekler)} mesaj -> veri/karistirilabilir_ornekler.csv")
    print("\nVeri setinde en riskli masum kelimeler (geçtiği mesajların yüzde kaçı zararlı):")
    riskli = ozet[ozet["kelime_gectigi_mesaj"] >= 20].sort_values("kelime_zararli_yuzde", ascending=False)
    print(riskli[["kategori", "kelime", "kelime_gectigi_mesaj", "kelime_zararli_yuzde"]]
          .drop_duplicates("kelime").head(25).to_string(index=False))


if __name__ == "__main__":
    main()
