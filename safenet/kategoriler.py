"""Türü bilinmeyen zararlı mesajlara kelime kurallarıyla kategori verir.

Wikipedia ve Kaggle setlerinde mesajın sadece "zararlı" olduğu yazıyor, neye yönelik
olduğu yazmıyor. Bu kurallar o mesajları anahtar kelimelere bakarak gruplara ayırır.
Sıra önemli: bir mesaj birden fazla kurala uyarsa listedeki İLK kategori seçilir
(en tehlikelisi olan tehdit en başta).
"""
import pandas as pd

KURALLAR = [
    ("tehdit", [
        r"\b(kill|murder|shoot|stab|hang|burn|rape|beat|hurt|punch|strangle|choke|behead|slit)\w*\s+(you|u|ya|him|her|them|yourself|urself)\b",
        r"\b(kill|murder|rape|shoot|stab|burn|hurt)\w*\s+(your|ur|yo)\s+(family|mom|mother|mum|dad|father|kids|children|wife|house|home|dog)\b",
        r"\b(i'?ll|i will|i'?m going to|im going to|i'?m gonna|im gonna|gonna)\s+(\w+\s+){0,2}(kill|murder|shoot|stab|rape|hurt|beat|punch|strangle)\b",
        r"\b(hope|wish)\s+(you|u|he|she|they)\s+(\w+\s+){0,2}(die|dies|died|get raped|gets raped|rot|burn|suffer|get cancer|get killed|gets killed)\b",
        r"\b(you|u)\s*(will|are going to|r going to|gonna|'re going to|re gonna)\s+(\w+\s+)?(die|suffer|regret|pay|bleed|burn)\b",
        r"\b(you|u)('re| are| r)?\s*(gonna|going to|will)\s+(get|be)\s+(raped|killed|shot|stabbed|beaten|murdered|hurt)\b",
        r"\b(kys|kill (your|ur|yo) ?self|kill urself|go die|drop dead|die in a fire|watch your back|i know where you live|"
        r"you'?re dead|you are dead|ur dead|dead meat|death threat|i'?ll find you|i will find you)\b",
    ]),
    ("irk", [
        r"\b(nigg(er|a|az|ers|as|uh)|negro(es)?|coons?|spics?|chinks?|gooks?|wetbacks?|beaners?|pakis?|honk(y|ies)|gypp?s(y|ies)|racial\w*|blacks|whites|"
        r"black (people|man|men|woman|women|guy|guys|person|folks)|white (people|man|men|woman|women|guy|guys|trash|boy|boys|folks)|"
        r"africans?|asians?|chinese|mexicans?|arabs?|indians?|pakistanis?|immigrants?|ethnic\w*|latinos?|hispanics?)\b",
    ]),
    ("din", [
        r"\b(muslims?|moslems?|islam\w*|jihad\w*|quran|koran|allah|mohamm[ae]d|muhammad|prophet|christians?|christianity|catholics?|bible|church|"
        r"jews?|jewish|judaism|zionists?|kikes?|hindus?|hinduism|atheists?|religio\w*|mosques?|sikhs?|buddhis\w*|ragheads?|towelheads?)\b",
    ]),
    ("cinsiyet", [  # cinsiyet ve cinsel yönelim
        r"\b(gays?|fags?|faggots?|fagg?ot\w*|homos?|homosexual\w*|lesbians?|dykes?|queers?|trann(y|ies)|transgender\w*|sissy|"
        r"women|woman|girls?|females?|feminis\w*|feminazis?|sexis\w*|misogyn\w*|whores?|sluts?)\b",
    ]),
    ("cinsel", [  # cinsel içerik ve cinsel taciz
        r"\b(penis\w*|vagina\w*|boobs?|titties|nipples?|blowjob\w*|blow job|handjob\w*|porn\w*|masturbat\w*|jerk off|dildo\w*|orgasm\w*|"
        r"horny|cum|cumming|semen|sperm|anal|anus|sex|sexy|sexual\w*|rape\w*|molest\w*|pedo\w*|paedo\w*)\b",
        r"\b(suck|lick|eat|blow|ride|touch)\w*\s+(my|his|your|ur|a|ma)\s+(dick|cock|balls|pussy|ass|tits|boobs|penis|nuts)\b",
    ]),
    # "yas" kategorisi yok: denediğimiz kural sadece ~200 mesaj buldu ve örneklerin çoğu
    # yaşla ilgili değildi. Güvenilir yaş verisi bulunursa buraya eklenebilir.
]
VARSAYILAN = "genel_hakaret"  # hiçbir kurala uymayan zararlı mesaj


def kategori_bul(metinler):
    """Her mesaj için kategori adını döndürür (pandas Series)."""
    sonuc = pd.Series(VARSAYILAN, index=metinler.index)
    atandi = pd.Series(False, index=metinler.index)
    for kategori, desenler in KURALLAR:
        uydu = pd.Series(False, index=metinler.index)
        for desen in desenler:
            uydu |= metinler.str.contains(desen, regex=True)
        sonuc[uydu & ~atandi] = kategori
        atandi |= uydu
    return sonuc
