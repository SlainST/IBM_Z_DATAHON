"""SafeNet 1. aşama: indirilen veri setlerini birleştirir ve temizler.

Çalıştırma:  python veri_hazirla.py   (birkaç dakika sürer)
Girdi:       veri/ham/ klasöründeki indirilmiş CSV dosyaları
             etiket_duzeltmeleri.csv (elle verilen kararlar: zararli / zararsiz / belirsiz)
Çıktı:       veri/birlesik_veri.csv   (eğitim + test, "bolum" sütununda yazar)
             veri/youtube_test.csv    (son sınav, eğitimde hiç kullanılmaz)
             veri/belirsiz_test.csv   (gerçekten belirsiz mesajlar: model bunlara orta puan vermeli)
"""
import hashlib

import numpy as np
import pandas as pd

from benzerlik import gruplari_bul
from kategoriler import kategori_bul
from temizlik import hedefli_mi, temizle_ayrintili

HAM = "veri/ham"
CIKTI = "veri"
DUZELTMELER = "etiket_duzeltmeleri.csv"
EN_UZUN = 1000      # karakter: sohbet mesajları bundan kısa; daha uzunları çoğunlukla Wikipedia makale tartışması
GRUP_SINIRI = 3     # neredeyse aynı mesajlardan en fazla kaç tane tutulur (spam şişmesin diye)
SUTUNLAR = ["id", "metin", "zararli", "tur", "tur_kaynagi", "hedefli", "gizli_kufur", "kaynak", "grup_id", "bolum"]


def yukle():
    """Her dosyayı ortak biçime çevirir: ham | zararli | tur | kaynak"""
    parcalar = []

    # 1) cyberbullying_tweets: türü belli olan tek set
    df = pd.read_csv(f"{HAM}/cyberbullying_tweets.csv")
    # other_cyberbullying: güvenilmez grup.
    # age: yaşa yönelik zorbalık DEĞİL; %98'i "bully" kelimesini içeriyor, çoğu insanların
    #      okulda yaşadığı zorbalığı anlattığı tweetler. Zararlı sayarsak kurbanı susturur.
    df = df[~df["cyberbullying_type"].isin(["other_cyberbullying", "age"])]
    turler = {"ethnicity": "irk", "religion": "din", "gender": "cinsiyet",
              "not_cyberbullying": "yok"}
    parcalar.append(pd.DataFrame({
        "ham": df["tweet_text"],
        "zararli": (df["cyberbullying_type"] != "not_cyberbullying").astype(int),
        "tur": df["cyberbullying_type"].map(turler),
        "kaynak": "cyberbullying",
    }))

    # 2) twitter_parsed: "racism" etiketlilerin çoğu İslam hakkında, o yüzden "din"
    df = pd.read_csv(f"{HAM}/twitter_parsed_dataset.csv").dropna(subset=["Annotation"])
    parcalar.append(pd.DataFrame({
        "ham": df["Text"],
        "zararli": df["oh_label"].astype(int),
        "tur": df["Annotation"].map({"racism": "din", "sexism": "cinsiyet", "none": "yok"}),
        "kaynak": "twitter",
    }))

    # 3) Wikipedia ve Kaggle: zararlı mı belli, neye yönelik olduğu belli değil
    for dosya, kaynak in [("toxicity_parsed_dataset.csv", "wikipedia"),
                          ("kaggle_parsed_dataset.csv", "kaggle")]:
        df = pd.read_csv(f"{HAM}/{dosya}")
        parcalar.append(pd.DataFrame({
            "ham": df["Text"],
            "zararli": df["oh_label"].astype(int),
            "tur": df["oh_label"].map({0: "yok", 1: "bilinmiyor"}),
            "kaynak": kaynak,
        }))

    return pd.concat(parcalar, ignore_index=True)


def hazirla(veri):
    """Kimlik, hedefli, temiz metin ve gizli küfür sütunlarını ekler; ham metni çıkarır."""
    ham = veri["ham"].astype(str)
    veri = veri.assign(
        id=[hashlib.md5(f"{k}|{h}".encode()).hexdigest()[:12] for k, h in zip(veri["kaynak"], ham)],
        hedefli=ham.map(hedefli_mi).astype(int),  # birine sesleniyor mu (@kullanıcı, you, your...)
    )
    sonuc = [temizle_ayrintili(h) for h in ham]
    veri["metin"] = [s[0] for s in sonuc]
    veri["gizli_kufur"] = ["; ".join(s[1]) for s in sonuc]  # örn. "f*ck→fuck; sh1t→shit"
    return veri.drop(columns="ham")


def duzelt(veri):
    """Elle verilen kararları uygular (etiket_duzeltmeleri.csv):
    zararli / zararsiz -> etiket değişir;  belirsiz -> eğitimden çıkıp belirsiz test setine gider."""
    d = pd.read_csv(DUZELTMELER)
    karar = veri["id"].map(dict(zip(d["id"], d["karar"])))
    yeni = karar.map({"zararli": 1, "zararsiz": 0})
    degisen = yeni.notna() & (yeni != veri["zararli"])
    veri.loc[degisen, "zararli"] = yeni[degisen].astype(int)
    veri.loc[degisen, "tur"] = veri.loc[degisen, "zararli"].map({1: "bilinmiyor", 0: "yok"})
    veri.loc[degisen, "tur_kaynagi"] = "duzeltme"
    veri["belirsiz"] = karar.eq("belirsiz")
    print(f"   {degisen.sum()} etiket düzeltildi, {veri['belirsiz'].sum()} satır belirsiz olarak ayrıldı")
    return veri


def anahtar(metinler):
    """Noktalama ve boşluk farkı olsa da aynı mesajı yakalamak için: sadece harf ve rakam."""
    return metinler.str.replace(r"<url>|[^a-z0-9]", "", regex=True)


def ayikla(veri):
    """Boş, çok uzun, belirsiz, çelişkili ve tekrar eden satırları ayırır. (veri, belirsiz) döndürür."""
    a = anahtar(veri["metin"])

    def at(maske, aciklama):
        nonlocal veri, a
        print(f"   {aciklama:<20} {maske.sum():>6} satır")
        atilan = veri[maske]
        veri, a = veri[~maske], a[~maske]
        return atilan

    at(a.str.len() < 3, "Boş / çok kısa:")
    at(veri["metin"].str.contains(r"^(?:redirect|category:|template(?: talk)?:)", regex=True), "Wikipedia sistem:")
    at(veri["metin"].str.len() > EN_UZUN, f"Çok uzun (>{EN_UZUN}):")
    belirsiz = at(veri["belirsiz"], "Belirsiz (ayrıldı):")
    # Elle karar verilmemiş çelişki kaldıysa (aynı mesaj hem zararlı hem zararsız) hepsini at
    at(veri.groupby(a)["zararli"].transform("nunique") > 1, "Çelişkili etiket:")
    # Tekrarlardan birini tut: veri setinin kendi etiketini taşıyan satır, düzelttiğimiz kopyadan önce gelir
    sira = veri["tur_kaynagi"].eq("duzeltme").reset_index(drop=True).sort_values(kind="stable").index
    veri, a = veri.iloc[sira], a.iloc[sira]
    at(a.duplicated(), "Tekrar eden:")
    return veri.drop(columns="belirsiz"), belirsiz.drop(columns="belirsiz")


def youtube_yukle():
    yt = pd.read_csv(f"{HAM}/youtube_parsed_dataset.csv")
    return hazirla(pd.DataFrame({"ham": yt["Text"], "zararli": yt["oh_label"], "kaynak": "youtube"}))


def benzerleri_grupla(veri, yt):
    """Neredeyse aynı mesajları gruplar (benzerlik.py). Bir grubun tamamı bölmede aynı tarafa düşer,
    spam şişmesin diye bir gruptan en fazla GRUP_SINIRI mesaj tutulur. YouTube setinden, eğitim
    verisindeki bir mesajla aynı ya da neredeyse aynı olanlar çıkarılır."""
    gruplar = gruplari_bul(list(veri["metin"]) + list(yt["metin"]))
    veri = veri.assign(grup_id=gruplar[:len(veri)])
    boyut = veri["grup_id"].map(veri["grup_id"].value_counts())
    print(f"   {(boyut > 1).sum()} mesaj, {veri.loc[boyut > 1, 'grup_id'].nunique()} benzer grupta toplandı")
    fazla = veri.groupby("grup_id").cumcount() >= GRUP_SINIRI
    print(f"   Grup sınırını ({GRUP_SINIRI}) aşan {fazla.sum()} benzer mesaj atıldı")
    veri = veri[~fazla].assign(grup_id=lambda d: pd.factorize(d["grup_id"])[0])

    yt_grup = gruplar[len(gruplar) - len(yt):]
    egitimde = np.isin(yt_grup, gruplar[:len(gruplar) - len(yt)]) | anahtar(yt["metin"]).isin(set(anahtar(veri["metin"])))
    print(f"   YouTube setinden eğitim verisine benzeyen {egitimde.sum()} mesaj çıkarıldı")
    return veri, yt[~egitimde]


def tur_belirle(veri):
    """Türü bilinmeyen zararlı mesajlara kelime kurallarıyla kategori verir (kategoriler.py).
    tur_kaynagi: "etiket" = veri setini hazırlayanlar yazmış, "kural" = bizim kuralımız bulmuş,
                 "duzeltme" = zararlı etiketini biz düzelttik, türü kurallar buldu."""
    bilinmeyen = veri["tur"] == "bilinmiyor"
    veri.loc[bilinmeyen, "tur"] = kategori_bul(veri.loc[bilinmeyen, "metin"])
    veri.loc[bilinmeyen & (veri["tur_kaynagi"] == "etiket"), "tur_kaynagi"] = "kural"
    print(f"   {bilinmeyen.sum()} bilinmeyen mesaj kategorilere ayrıldı")
    return veri


def bol(veri):
    """Eğitim / test bölmesi. Gruplar bölünmez: neredeyse aynı mesajların hepsi ya eğitime ya teste gider.
    Her kaynak x etiket kümesinden grupların %20'si rastgele teste ayrılır (tabakalı bölme).
    random_state=42: zar her seferinde aynı gelir, herkes aynı test setini kullanır."""
    gruplar = veri.groupby("grup_id").agg(kaynak=("kaynak", "first"), zararli=("zararli", "max"))
    test = gruplar.groupby(["kaynak", "zararli"]).sample(frac=0.2, random_state=42).index
    return veri.assign(bolum=np.where(veri["grup_id"].isin(test), "test", "egitim"))


def belirsizleri_kaydet(belirsiz):
    """Aynı mesajın kopyalarını tek satırda toplar; hangi kaynağın ne dediğini yazar."""
    etiket = belirsiz["kaynak"] + ":" + belirsiz["zararli"].astype(str)
    ozet = (belirsiz.assign(etiket=etiket)
            .groupby(anahtar(belirsiz["metin"]))
            .agg(id=("id", "first"), metin=("metin", "first"), hedefli=("hedefli", "max"),
                 gizli_kufur=("gizli_kufur", "first"), etiketler=("etiket", lambda s: ", ".join(sorted(set(s))))))
    ozet.to_csv(f"{CIKTI}/belirsiz_test.csv", index=False, encoding="utf-8-sig")
    return ozet


def main():
    print("1) Dosyalar okunuyor...")
    veri = yukle()
    print(f"   Toplam {len(veri)} satır")

    print("2) Metinler temizleniyor, gizli küfürler çözülüyor...")
    veri = hazirla(veri).assign(tur_kaynagi="etiket")
    yt = youtube_yukle()

    print("3) Elle verilen kararlar uygulanıyor...")
    veri = duzelt(veri)

    print("4) Gereksiz satırlar ayıklanıyor...")
    veri, belirsiz = ayikla(veri)

    print("5) Neredeyse aynı mesajlar gruplanıyor...")
    veri, yt = benzerleri_grupla(veri, yt)

    print("6) Türü bilinmeyen zararlı mesajlar kategorilere ayrılıyor...")
    veri = tur_belirle(veri)

    print("7) Eğitim / test olarak bölünüyor (benzer gruplar bölünmeden)...")
    veri = bol(veri)[SUTUNLAR]

    # utf-8-sig: Excel'de açınca özel karakterler bozulmasın diye
    veri.to_csv(f"{CIKTI}/birlesik_veri.csv", index=False, encoding="utf-8-sig")
    yt[["id", "metin", "zararli", "hedefli", "gizli_kufur"]].to_csv(
        f"{CIKTI}/youtube_test.csv", index=False, encoding="utf-8-sig")
    belirsiz = belirsizleri_kaydet(belirsiz)

    print(f"\nBitti: {len(veri)} satır -> {CIKTI}/birlesik_veri.csv")
    print("\nKaynak ve etikete göre (0 = zararsız, 1 = zararlı):")
    print(pd.crosstab(veri["kaynak"], veri["zararli"], margins=True, margins_name="toplam"))
    print("\nZararlı mesajların türleri (etiket = veri setinden, kural = kuralımızdan, duzeltme = biz düzelttik):")
    zararli = veri[veri["zararli"] == 1]
    print(pd.crosstab(zararli["tur"], zararli["tur_kaynagi"], margins=True, margins_name="toplam")
          .sort_values("toplam", ascending=False).to_string())
    print(f"\nEğitim: {(veri['bolum'] == 'egitim').sum()}  Test: {(veri['bolum'] == 'test').sum()}")
    gizli = veri["gizli_kufur"] != ""
    print(f"Gizli küfür bulunan mesaj: {gizli.sum()} (bunların %{100 * veri.loc[gizli, 'zararli'].mean():.0f}'i zararlı)")
    print(f"\nYouTube son sınav seti: {len(yt)} satır -> {CIKTI}/youtube_test.csv")
    print(f"Belirsiz test seti: {len(belirsiz)} mesaj -> {CIKTI}/belirsiz_test.csv")


if __name__ == "__main__":
    main()
