"""Kimliğe (din, ırk, cinsiyet ve cinsel yönelim) yönelik saldırıyı, kimlikten BAHSETMEKTEN ayırır.

Kimlik kelimesinin sadece geçmesi ceza sebebi değildir ("I'm a proud Muslim").
Ceza, kimliğin SALDIRI için kullanılmasına verilir. Üç biçim ayırt edilir:
  bahsetme   kimlik kelimesi geçiyor ama kimse hedef alınmıyor   "my best friend is gay"
  genelleme  bir grubun tamamı hakkında konuşuluyor               "muslims are terrorists", "all women are stupid"
  hedefli    karşıdaki kişiye kimliği üzerinden sesleniliyor        "you dirty muslim", "you're such a girl"

Mesajın zararlı olup olmadığına MODEL karar verir; bu modül sadece biçimi ve grubu söyler.
Puanlar ayarlar.toml'daki [kimlik] bölümünden gelir ve sohbet türüne göre çarpılır.

Temizlenmiş metinle çağırın:  kimlik_analizi(temizle(ham), hedefli=hedefli_mi(ham))
"""
import re

# Kimlik kelimeleri (çoğulları da sayılır). Siyah/beyaz sadece insanları anlatırken kimliktir.
_INSAN = r"(people|man|men|woman|women|guy|guys|person|folks|kid|kids|girl|girls|boy|boys|lady|ladies)"
GRUPLAR = {
    "din": r"muslims?|moslems?|islam|islamic|jews?|jewish|christians?|catholics?|hindus?|sikhs?|buddhists?|atheists?|mormons?",
    "irk": (r"blacks|whites|black " + _INSAN + r"|white " + _INSAN +
            r"|africans?|asians?|arabs?|mexicans?|latinos?|latinas?|hispanics?|immigrants?|refugees?"
            r"|indians?|chinese|pakistanis?|gypsy|gypsies"),
    "cinsiyet": (r"woman|women|girls?|females?|feminists?|gays?|lesbians?|trans|transgender|queers?"
                 r"|bisexuals?|homosexuals?"),
}
# Hakaret kelimesi olarak kullanılan kimlik kelimeleri (kufur_listesi.csv'de seviye 9)
HAKARETLER = {
    "irk": r"niggers?|niggas?|spics?|chinks?|coons?|wetbacks?|gooks?|beaners?|pakis?",
    "din": r"kikes?|ragheads?|towelheads?",
    "cinsiyet": r"faggots?|fags?|dykes?|tranny",
}
_HEPSI = "|".join(f"(?:{d})" for d in list(GRUPLAR.values()) + list(HAKARETLER.values()))
_SEN = r"\b(you|u|ur|your|you're|youre|ya)\b"
HEDEFLI = re.compile(_SEN + r"(?:\W+\w+){0,3}?\W+(?:" + _HEPSI + r")\b")               # "you dirty muslim"
GENELLEME = re.compile(
    r"\b(all|every|those|these|typical|fucking|dirty|filthy|stupid|bloody|damn)\s+(?:" + _HEPSI + r")\b"
    r"|\b(?:" + _HEPSI + r")\s+(are|r|should|must|need to|always|never|cant|can't|dont|don't|ruin|deserve)\b")


def kimlik_analizi(metin, hedefli=False):
    """Döndürür: {"gruplar": [...], "hakaret_kelimesi": bool, "bicim": "hedefli"/"genelleme"/"bahsetme"/None}"""
    gruplar = [g for g, d in GRUPLAR.items() if re.search(rf"\b(?:{d})\b", metin)]
    hakaret = [g for g, d in HAKARETLER.items() if re.search(rf"\b(?:{d})\b", metin)]
    hepsi = sorted(set(gruplar + hakaret))
    if not hepsi:
        bicim = None
    elif HEDEFLI.search(metin):
        bicim = "hedefli"
    elif GENELLEME.search(metin):
        bicim = "genelleme"
    elif hedefli:              # @kullanıcı'ya yazılmış ya da birebir sohbet
        bicim = "hedefli"
    else:
        bicim = "bahsetme"
    return {"gruplar": hepsi, "hakaret_kelimesi": bool(hakaret), "bicim": bicim}


def kimlik_puani(analiz, model_zararli_mi, ayarlar):
    """Gizli puana eklenecek kimlik puanı. Model mesajı zararsız bulduysa kimlik kelimesi puan eklemez."""
    if not analiz["bicim"] or not model_zararli_mi:
        return 0
    k = ayarlar["kimlik"]
    taban = {"hedefli": k["hedefli_saldiri"], "genelleme": k["genelleme"], "bahsetme": k["zararli_bahsetme"]}
    return round(taban[analiz["bicim"]] * ayarlar["kanal"].get("kimlik_carpani", 1.0))
