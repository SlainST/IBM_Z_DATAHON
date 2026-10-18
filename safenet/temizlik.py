"""SafeNet metin temizleme.

Bu fonksiyonlar hem eğitimde (veri_hazirla.py) hem de canlı sistemde (API)
AYNEN kullanılmalı. Burada bir şeyi değiştirirseniz modeli yeniden eğitin.

temizle(metin)             -> modelin göreceği temiz metin
temizle_ayrintili(metin)   -> (temiz metin, bulunan gizli küfürler listesi)
hedefli_mi(metin)          -> mesaj birine doğrudan sesleniyor mu (@kullanıcı, you, your...)

kufur_listesi.csv "seviye" sütunu (1-10) gizli puana eklenecek değerdir; sansür ise listedeki
HER kelimeye uygulanır. 1-2 çok hafif (damn, hell), 3-4 hafif (piss, wtf), 5-6 ağır (fuck, bitch),
7-8 aşağılayıcı/cinsel (cunt, whore), 9 nefret söylemi (ırkçı/homofobik hakaret), 10 tehdit (kys).
"""
import csv
import html
import re
import unicodedata
from pathlib import Path

# --- Küfür listesi (kufur_listesi.csv): kelime -> asıl hali ---
with open(Path(__file__).with_name("kufur_listesi.csv"), encoding="utf-8") as f:
    _satirlar = list(csv.DictReader(f))
ASIL = {s["kelime"]: s["asil"] for s in _satirlar}                     # fck -> fuck
SEVIYE = {s["asil"]: int(s["seviye"]) for s in _satirlar}              # fuck -> 6
TEMEL = [s["kelime"] for s in _satirlar if s["kelime"] == s["asil"]]   # yıldızlı eşleştirme için, sık olan önce

# Kiril / Yunan harfleri Latin harflere benzer: "аss" (Kiril а) -> "ass"
BENZER_HARFLER = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "һ": "h", "ӏ": "l", "ո": "n", "ս": "u",
    "α": "a", "ε": "e", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "ι": "i", "κ": "k", "ν": "v", "χ": "x",
    "β": "b", "η": "n",
})
# Rakam ve işaretlerle yazılmış harfler: sh1t, a$$, b!tch, fu(k
LEET_I = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g",
                        "@": "a", "$": "s", "!": "i", "|": "i", "(": "c", "+": "t", "€": "e"})
LEET_L = str.maketrans({**LEET_I, ord("1"): "l"})
JOKER = "*#%?"                                        # harf yerine konan işaretler: f**k
GORUNMEZ = re.compile("[​-‏⁠﻿­]")  # sıfır genişlikli (görünmez) karakterler
KENAR = re.compile(r"([\"'(\[{]*)(.*?)([\"')\]},;:?!.]*)")  # kelimenin başındaki/sonundaki noktalama
# Emojiler ve resimli semboller (😂 🖕 ♥ ⭐ bayraklar, ten rengi işaretleri): tamamen silinir
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⌀-⏿⬀-⯿"
                   "︎️⃣〰〽㊗㊙©®™]")
# Küfür yerine geçen emojiler: silinmeden önce listedeki kelimeye çevrilir (gizli küfür sayılır). Yalnız anlamı tek
# olanlar: 💩 ("this game is 💩") ve 🍆 çoğu zaman şaka ya da sebze, listede değil.
EMOJI_KUFUR = {"🖕": "fuck"}
TEN_RENGI = re.compile("[🏻-🏿️]")


def emoji_kufur(parca):
    """"🖕", "🖕🏽", "🖕🖕" -> "fuck"; başka her şey -> None."""
    t = TEN_RENGI.sub("", parca)
    return EMOJI_KUFUR[t[0]] if t and len(set(t)) == 1 and t[0] in EMOJI_KUFUR else None


def _aksansiz(kelime):
    """fück -> fuck"""
    return "".join(c for c in unicodedata.normalize("NFKD", kelime) if not unicodedata.combining(c))


def _tekrarsiz(kelime):
    """fuuck -> fuck"""
    return re.sub(r"(.)\1+", r"\1", kelime)


def _harfleri_duzelt(t, bulunanlar):
    """Görünmez karakterleri siler, yabancı/aksanlı harfleri Latin harfe çevirir."""
    if t.isascii():
        return t

    def duzelt(m):
        once, kelime, sonra = KENAR.fullmatch(m.group(0)).groups()
        yeni = _aksansiz(GORUNMEZ.sub("", kelime).translate(BENZER_HARFLER))
        if yeni != kelime and yeni in ASIL:
            bulunanlar.append(f"{kelime}→{ASIL[yeni]}")
            yeni = ASIL[yeni]
        return once + yeni + sonra
    return re.sub(r"\S+", duzelt, t)


# Harf harf yazılmış bir dizide küfrün önünde ve arkasında kalan harfler yalnız bu kısa kelimelerden oluşabilir:
# "a f u c k" (a fuck), "u r a f u c k", "s h i t s". "h e l l o"nun sonundaki "o", "c l a s s"ın başındaki "cl"
# ve "a s s i g n"in sonundaki "ign" kelime değil: hello, class ve assign küfür sayılmaz.
ARALIK_ONCE = frozenset({"a", "u", "ur", "ya", "you", "the", "go", "to", "so", "oh", "my", "is", "im", "ok", "lol"})
ARALIK_SONRA = frozenset({"s", "es", "ing", "in", "er", "ers", "ed", "y", "u", "you", "off", "up", "lol"})


def _parcalanir(harfler, kelimeler):
    """harfler boş mu, ya da baştan sona kelimeler'den birleşiyor mu?"""
    if not harfler:
        return True
    return any(harfler.startswith(k) and _parcalanir(harfler[len(k):], kelimeler) for k in kelimeler)


def aralikli_kufur(harfler):
    """Harf harf yazılmış bir dizideki en uzun küfür: (bas, uzunluk) ya da None. "afuck" -> (1, 4), "hello" -> None."""
    for uzunluk in range(len(harfler), 2, -1):
        for bas in range(len(harfler) - uzunluk + 1):
            if (harfler[bas:bas + uzunluk] in ASIL and _parcalanir(harfler[:bas], ARALIK_ONCE)
                    and _parcalanir(harfler[bas + uzunluk:], ARALIK_SONRA)):
                return bas, uzunluk
    return None


def _aralikli_harfler(t, bulunanlar):
    """f u c k, s.h.i.t gibi harf harf yazılmış küfürleri birleştirir."""
    def birlestir(m):
        harfler = re.findall(r"[a-z]", m.group(0))
        bulunan = aralikli_kufur("".join(harfler))             # "a f u c k" içinde "fuck"u bul
        if not bulunan:
            return m.group(0)
        bas, uzunluk = bulunan
        aday = "".join(harfler[bas:bas + uzunluk])
        bulunanlar.append(f"{m.group(0)}→{ASIL[aday]}")
        return " ".join(harfler[:bas] + [ASIL[aday]] + harfler[bas + uzunluk:])
    return re.sub(r"(?<![a-z])(?:[a-z][ .\-_*]{1,2}){2,}[a-z](?![a-z])", birlestir, t)


def _kelime_coz(kelime):
    """Tek kelimedeki gizlemeyi çözer. (yeni_kelime, gizlenmis_mi) ya da None döndürür."""
    if kelime.isalpha():
        if kelime in ASIL:
            return (ASIL[kelime], True) if ASIL[kelime] != kelime else None   # fck -> fuck
        tek = _tekrarsiz(kelime)
        if tek in ASIL:
            return ASIL[tek], ASIL[tek] != tek             # fuuck -> fuck sadece uzatma, gizleme değil
        return None
    if len(kelime) > 20 or "<" in kelime:
        return None
    for leet in (LEET_I, LEET_L):
        aday = re.sub(r"[.\-_]", "", kelime.translate(leet))  # f.u.c.k -> fuck
        if not re.search(r"[a-z]", aday):
            continue
        if any(j in aday for j in JOKER):                   # f**k -> f..k -> fuck
            desen = re.compile("".join("[a-z]" if c in JOKER else re.escape(c) for c in aday))
            for temel in TEMEL:
                if len(temel) == len(aday) and desen.fullmatch(temel):
                    return temel, True
        else:
            for a in (aday, _tekrarsiz(aday)):
                if a in ASIL:
                    return ASIL[a], True
    return None


def _gizli_kufurleri_coz(t, bulunanlar):
    t = _aralikli_harfler(t, bulunanlar)

    def coz(m):
        once, kelime, sonra = KENAR.fullmatch(m.group(0)).groups()
        sonuc = _kelime_coz(kelime) if kelime else None
        if not sonuc:
            return m.group(0)
        yeni, gizli = sonuc
        if gizli:
            bulunanlar.append(f"{kelime}→{yeni}")
        return once + yeni + sonra
    return re.sub(r"\S+", coz, t)


def temizle_ayrintili(metin):
    bulunanlar = []
    t = html.unescape(html.unescape(str(metin)))          # &amp; -> &   &lt;3 -> <3 (bazıları iki kez kodlanmış)
    t = re.sub(r"\\+(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|[ntr])", " ", t)  # yazı olarak kalmış \xa0, \n
    t = re.sub(r"\\+'", "'", t)                           # don\'t -> don't
    t = t.strip().strip('"')                              # Kaggle setindeki baş/son tırnaklar
    t = unicodedata.normalize("NFKC", t)                  # ｆｕｃｋ (geniş harfler) -> fuck
    for e, kelime in EMOJI_KUFUR.items():                 # 🖕 -> fuck (gizli küfür)
        if e in t:
            bulunanlar.append(f"{e}→{kelime}")
            t = t.replace(e, f" {kelime} ")
    t = EMOJI.sub(" ", t)                                 # kalan emojiler silinir
    t = t.lower()                                         # IDIOT -> idiot
    t = _harfleri_duzelt(t, bulunanlar)                   # аss (Kiril), fu​ck (görünmez), fück -> fuck
    t = re.sub(r"^rt\b", " ", t)                          # baştaki RT (retweet işareti)
    t = re.sub(r"https?://\S+|www\.\S+", " <url> ", t)    # linkler
    t = re.sub(r"(?<![\w@])@\w+", " ", t)                 # @kullaniciadi: silinir (model "tweet" ezberlemesin)
    t = re.sub(r"#mkr\w*", " ", t)                        # #MKR tuzağı (yemek programı etiketi)
    t = re.sub(r"#+(\w+)", r"\1", t)                      # #stupid -> stupid
    t = re.sub(r"`+|={2,}|:{2,}", " ", t)                 # Wikipedia işaretleri: `` == ::
    t = re.sub(r"\d{1,2}:\d{2}, \d{1,2} [a-z]+ \d{4}|\(utc\)", " ", t)  # Wikipedia imza tarihi: 12:34, 5 may 2005 (utc)
    t = re.sub(r"^[\s:]+", "", t)                         # satır başındaki : ve boşluklar
    t = re.sub(r"([a-z])\1{2,}", r"\1\1", t)              # stuuuupid -> stuupid
    t = re.sub(r"([!?.])\1{2,}", r"\1\1", t)              # !!!!! -> !!
    t = _gizli_kufurleri_coz(t, bulunanlar)               # f*ck, sh1t, a$$, f u c k, fck, stfu -> düz hali
    t = re.sub(r"\s+", " ", t).strip()                    # fazla boşluklar
    return t, bulunanlar


def temizle(metin):
    return temizle_ayrintili(metin)[0]


def hedefli_mi(metin):
    """Mesaj birine doğrudan sesleniyor mu? Temizlenmemiş (ham) metinle çağırın."""
    t = str(metin).lower()
    return bool(re.search(r"(?<![\w@])@\w+|\b(you|your|yours|yourself|you're|youre|ya|ur|ure)\b|\bu\b(?!\.\w)", t))
