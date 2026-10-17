"""Birebir, grup ve canlı yayın sohbet simülasyonları üretir (demo, canlı akış, yük ve gizli puan testi için).

Elimizde gerçek sohbet verisi yok. Bu yüzden modelin eğitimde HİÇ görmediği mesajlardan
(birlesik_veri.csv'nin test bölümü) sahte sohbetler kurulur. Mesajlar birbirine cevap vermez;
amaç gerçekçi bir mesaj AKIŞI ve davranışı bilinen kullanıcılar üretmektir. Model eğitiminde KULLANILMAZ.

Kullanıcı tipleri ve "susturulmalı mı?" cevabı (gizli puan sistemi bununla ölçülecek):
  normal     %2 zararlı                                              -> susturulmamalı
  kurban     zorbalığa uğrayan; mesajları normal                      -> susturulmamalı
  tovbe      ilk 2 mesajı zararlı, sonra hep düzgün                   -> susturulmamalı (düzgün mesajlarla puanı düşmeli)
  sakaci     arkadaşıyla küfürlü ama dostça konuşur                   -> susturulmalı (çocukları korumak için
                                                                         arkadaşlar arası küfüre de indirim yok)
  trol       %40 zararlı                                              -> susturulmalı
  zorba      %60 zararlı, hep karşısındakine seslenir                 -> susturulmalı
  tirmanan   önce düzgün, giderek kötüleşir (%0 -> %70)               -> susturulmalı
  gizlemeci  %45 zararlı, küfürleri gizler (f*ck, sh1t, а$$)          -> susturulmalı
  baskinci   canlı yayına toplu saldırı (raid), kısa sürede çok mesaj -> susturulmalı

Çalıştırma:  python sohbet_simulasyonu.py
Çıktı:       veri/sohbetler/birebir.csv, grup.csv, canli_yayin.csv, kullanicilar.csv
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd

from temizlik import ASIL, temizle_ayrintili

rng = np.random.default_rng(42)  # her çalıştırmada aynı sohbetler çıksın
KLASOR = Path("veri/sohbetler")
# Wikipedia'ya özgü konuşmalar (makale, düzenleme, admin...) sohbette doğal durmaz, dışarıda kalır
WIKI = (r"\b(wikipedia|wiki|article|articles|edit|edits|edited|editing|editor|editors|revert\w*|vandal\w*|talk page|"
        r"deletion|deleted|delete|citation|cite|sources?|block\w*|admin\w*|userpage|sock\w*|npov|afd)\b")
KUFUR = r"\b(" + "|".join(sorted((k for k in ASIL if " " not in k), key=len, reverse=True)) + r")\b"
ZARARLI_OLASILIGI = {"normal": 0.02, "kurban": 0.02, "sakaci": 0.02, "trol": 0.40, "zorba": 0.60,
                     "gizlemeci": 0.45, "baskinci": 0.85}
SUSTURULMALI = {"trol", "zorba", "tirmanan", "gizlemeci", "baskinci", "sakaci"}
KIRIL = str.maketrans({"a": "а", "e": "е", "o": "о", "c": "с", "p": "р"})


def havuz_yukle(en_uzun):
    v = pd.read_csv("veri/birlesik_veri.csv").fillna({"gizli_kufur": ""})
    v = v[(v["bolum"] == "test") & (v["metin"].str.len() <= en_uzun) & ~v["metin"].str.contains(WIKI, regex=True)]
    kufurlu = v["metin"].str.contains(KUFUR, regex=True)
    temiz, zararli = v["zararli"] == 0, v["zararli"] == 1
    return {
        "temiz": v[temiz & ~kufurlu],
        "kufurlu_temiz": v[temiz & kufurlu],                  # şakacıların dostça küfürlü mesajları
        "zararli": v[zararli],
        "zararli_hedefli": v[zararli & (v["hedefli"] == 1)],  # zorbalar karşısındakine seslenir
        "zararli_kufurlu": v[zararli & kufurlu],              # gizlemeciler bunları gizleyerek yazar
    }


def _gizle_kelime(kelime):
    """Bir küfrü rastgele bir yöntemle gizler: f*ck, sh1t, a$$, f u c k, Kiril harfli аss, fck."""
    yontem = rng.choice(["yildiz", "rakam", "aralikli", "kiril", "kisaltma"])
    if yontem == "yildiz":
        icerik = re.sub(r"[aeiou]", "*", kelime[1:-1]) if len(kelime) > 3 else "*" * (len(kelime) - 1)
        return kelime[0] + icerik + (kelime[-1] if len(kelime) > 3 else "")
    if yontem == "rakam":
        return kelime.translate(str.maketrans({"i": "1", "o": "0", "e": "3", "a": "@", "s": "$"}))
    if yontem == "aralikli":
        return " ".join(kelime)
    if yontem == "kiril":
        return kelime.translate(KIRIL)
    return {"fuck": "fck", "shit": "sht", "bitch": "btch", "fucking": "fkn"}.get(kelime, kelime[0] + "*" * (len(kelime) - 1))


def gizle(metin):
    """Mesajdaki küfürleri gizler; çözücümüzün geri çözebildiği bir gizleme bulunana kadar dener."""
    for _ in range(10):
        yeni = re.sub(KUFUR, lambda m: _gizle_kelime(m.group(0)), metin)
        if yeni != metin and temizle_ayrintili(yeni)[1]:
            return yeni, True
    return metin, False


def mesaj_uret(havuz, tip, kesir, kacinci):
    """kesir: sohbetin ne kadarı geçti (0-1), kacinci: kullanıcının kaçıncı mesajı (0'dan başlar)."""
    if tip == "tovbe":
        p = 1.0 if kacinci < 2 else 0.0
    elif tip == "tirmanan":
        p = 0.7 * kesir
    else:
        p = ZARARLI_OLASILIGI[tip]
    if rng.random() < p:
        kume = {"zorba": "zararli_hedefli", "gizlemeci": "zararli_kufurlu"}.get(tip, "zararli")
    elif tip == "sakaci" and rng.random() < 0.5:
        kume = "kufurlu_temiz"
    else:
        kume = "temiz"
    m = havuz[kume].iloc[rng.integers(len(havuz[kume]))]
    metin, gizlendi = (gizle(m["metin"]) if kume == "zararli_kufurlu" else (m["metin"], False))
    return m, metin, gizlendi


def sohbet_kur(havuz, sohbet_id, kanal, senaryo, kisiler, mesaj_sayisi, ort_aralik, alici_bul):
    """kisiler: {kullanici: (tip, yazma_agirligi)}; alici_bul(gonderen, zararli) -> alıcı."""
    adlar = list(kisiler)
    agirlik = np.array([kisiler[k][1] for k in adlar], dtype=float)
    zamanlar = np.cumsum(rng.exponential(ort_aralik, mesaj_sayisi))
    sayac, satirlar = {k: 0 for k in adlar}, []
    for sira, zaman in enumerate(zamanlar, 1):
        gonderen = adlar[rng.choice(len(adlar), p=agirlik / agirlik.sum())]
        tip = kisiler[gonderen][0]
        m, metin, gizlendi = mesaj_uret(havuz, tip, zaman / zamanlar[-1], sayac[gonderen])
        sayac[gonderen] += 1
        satirlar.append({"sohbet_id": sohbet_id, "kanal": kanal, "senaryo": senaryo, "sira": sira,
                         "zaman_sn": round(float(zaman), 1), "gonderen": gonderen,
                         "alici": alici_bul(gonderen, m["zararli"]), "kullanici_tipi": tip,
                         "susturulmali": tip in SUSTURULMALI, "metin": metin, "gizlendi": gizlendi,
                         "zararli": m["zararli"], "tur": m["tur"], "hedefli": m["hedefli"], "mesaj_id": m["id"]})
    return satirlar


def birebir(havuz):
    """Özel mesajlaşmalar. Birebir konuşmada her mesaj zaten karşıdakine yazılmıştır."""
    senaryolar = {  # senaryo: (adet, 1. kişinin tipi, 2. kişinin tipi, 1. kişinin yazma payı, ort. mesaj aralığı sn)
        "normal": (16, "normal", "normal", 0.5, 20),
        "zorbalik": (6, "zorba", "kurban", 0.6, 20),
        "kavga": (3, "trol", "trol", 0.5, 20),
        "tirmanan": (4, "tirmanan", "normal", 0.55, 20),
        "tovbe": (4, "tovbe", "normal", 0.5, 600),     # saatlere yayılır: zaman puanı düşürmez, düzgün mesajlar düşürür
        "sakalasma": (4, "sakaci", "sakaci", 0.5, 20),
        "gizlemeci": (3, "gizlemeci", "normal", 0.55, 20),
    }
    satirlar, n = [], 0
    for senaryo, (adet, tip1, tip2, pay, aralik) in senaryolar.items():
        for _ in range(adet):
            n += 1
            a, b = f"dm{n:02d}_a", f"dm{n:02d}_b"
            kisiler = {a: (tip1, pay), b: (tip2, 1 - pay)}
            satirlar += sohbet_kur(havuz, f"dm_{n:02d}", "birebir", senaryo, kisiler, int(rng.integers(15, 41)),
                                   aralik, lambda g, z, a=a, b=b: b if g == a else a)
    return pd.DataFrame(satirlar)


def grup(havuz):
    """Grup sohbetleri, 5-8 kişi."""
    senaryolar = {  # senaryo: (adet, özel üyelerin tipleri)
        "normal": (4, []),
        "trol": (3, ["trol"]),
        "toplu_saldiri": (3, ["zorba", "zorba", "zorba", "kurban"]),  # 3 kişi aynı kişiyi hedef alır
        "tirmanan": (2, ["tirmanan"]),
        "sakalasma": (2, ["sakaci", "sakaci", "sakaci"]),
        "gizlemeci": (2, ["gizlemeci"]),
    }
    satirlar, n = [], 0
    for senaryo, (adet, ozel) in senaryolar.items():
        for _ in range(adet):
            n += 1
            tipler = ozel + ["normal"] * (int(rng.integers(5, 9)) - len(ozel))
            uyeler = [f"g{n:02d}_{i}" for i in range(1, len(tipler) + 1)]
            kisiler = {u: (t, 2.0 if t in SUSTURULMALI else 1.0) for u, t in zip(uyeler, tipler)}
            kurban = next((u for u, t in zip(uyeler, tipler) if t == "kurban"), None)

            def alici_bul(g, zararli, uyeler=uyeler, kurban=kurban):
                if not zararli:
                    return "grup"
                return kurban if kurban and g != kurban else rng.choice([u for u in uyeler if u != g])
            satirlar += sohbet_kur(havuz, f"grup_{n:02d}", "grup", senaryo, kisiler, int(rng.integers(60, 121)),
                                   15, alici_bul)
    return pd.DataFrame(satirlar)


def canli_yayin(havuz):
    """2 canlı yayın: 200 izleyici, dakikada ~75 mesaj; 10. dakikada 15 hesaplık toplu saldırı (raid)."""
    satirlar = []
    for n in range(1, 3):
        tipler = ["trol"] * 4 + ["tirmanan"] * 2 + ["gizlemeci"] * 2 + ["tovbe"] * 3 + ["sakaci"] * 4
        tipler += ["normal"] * (200 - len(tipler))
        kisiler = {f"y{n}_{i:03d}": (t, 3.0 if t in SUSTURULMALI else 1.0) for i, t in enumerate(tipler, 1)}
        akis = sohbet_kur(havuz, f"yayin_{n}", "canli_yayin", "trol_ve_baskin", kisiler, 1800, 0.8,
                          lambda g, z: "yayin")
        # Baskın: 15 yeni hesap, 600-645. saniyeler arasında 3'er zararlı mesaj
        for i in range(1, 16):
            for zaman in np.sort(rng.uniform(600, 645, 3)):
                m, metin, gizlendi = mesaj_uret(havuz, "baskinci", 0, 0)
                akis.append({**akis[0], "sira": 0, "zaman_sn": round(float(zaman), 1), "gonderen": f"y{n}_baskin{i:02d}",
                             "kullanici_tipi": "baskinci", "susturulmali": True, "metin": metin, "gizlendi": gizlendi,
                             "zararli": m["zararli"], "tur": m["tur"], "hedefli": m["hedefli"], "mesaj_id": m["id"]})
        akis = sorted(akis, key=lambda s: s["zaman_sn"])
        for sira, s in enumerate(akis, 1):
            s["sira"] = sira
        satirlar += akis
    return pd.DataFrame(satirlar)


def main():
    KLASOR.mkdir(parents=True, exist_ok=True)
    uzun_havuz, kisa_havuz = havuz_yukle(300), havuz_yukle(150)  # canlı yayında mesajlar daha kısa
    print("Havuzlar:", {k: len(v) for k, v in uzun_havuz.items()})
    hepsi = []
    for ad, df in [("birebir", birebir(uzun_havuz)), ("grup", grup(uzun_havuz)),
                   ("canli_yayin", canli_yayin(kisa_havuz))]:
        df.to_csv(KLASOR / f"{ad}.csv", index=False, encoding="utf-8-sig")
        hepsi.append(df)
        print(f"{ad}: {df['sohbet_id'].nunique()} sohbet, {df['gonderen'].nunique()} kullanıcı, {len(df)} mesaj, "
              f"%{100 * df['zararli'].mean():.1f} zararlı, {df['gizlendi'].sum()} gizlenmiş küfürlü mesaj")

    # Kullanıcı özeti: sonra gizli puan sisteminin kararlarını bununla karşılaştıracağız
    k = (pd.concat(hepsi).groupby(["kanal", "sohbet_id", "gonderen"])
         .agg(kullanici_tipi=("kullanici_tipi", "first"), susturulmali=("susturulmali", "first"),
              mesaj_sayisi=("metin", "size"), zararli_mesaj=("zararli", "sum"),
              ilk_mesaj_sn=("zaman_sn", "min"), son_mesaj_sn=("zaman_sn", "max"))
         .reset_index())
    k.to_csv(KLASOR / "kullanicilar.csv", index=False, encoding="utf-8-sig")
    print("\nKullanıcı tipleri:")
    print(k.groupby(["kullanici_tipi", "susturulmali"]).agg(kisi=("gonderen", "size"),
          mesaj=("mesaj_sayisi", "sum"), zararli=("zararli_mesaj", "sum")).to_string())


if __name__ == "__main__":
    main()
