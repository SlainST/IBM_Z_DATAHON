"""Neredeyse aynı mesajları bulur (MinHash yöntemi).

"die wikipedia die wikipedia..." gibi tekrar sayısı ya da bir iki kelimesi farklı mesajlar birebir
aynı olmadığı için normal tekrar kontrolüne takılmaz. Biri eğitime, öbürü teste düşerse model testte
"ezberden" başarılı görünür. Burada her mesaj 5 harflik parçalara bölünür; iki mesajın parçalarının
en az %80'i ortaksa "neredeyse aynı" sayılır ve aynı gruba konur.

Her mesajın tüm parçalarını herkesle karşılaştırmak çok yavaş olurdu. Bunun yerine her mesajdan
64 sayılık kısa bir "parmak izi" çıkarılır; parmak izleri benzeyenler karşılaştırılır.
"""
import re
import zlib

import numpy as np

ESIK = 0.8     # parçaların en az %80'i ortaksa neredeyse aynı
PARCA = 5      # 5 harflik parçalar
IMZA = 64      # parmak izinin uzunluğu
BANT = 16      # parmak izi 16 banda bölünür; bir bandı tutan mesajlar karşılaştırılır


def _parcalar(metin):
    t = " ".join(re.findall(r"[a-z0-9]+", metin))
    if len(t) <= PARCA:
        return np.array([zlib.crc32(t.encode())], dtype=np.uint64)
    return np.unique(np.fromiter((zlib.crc32(t[i:i + PARCA].encode()) for i in range(len(t) - PARCA + 1)),
                                 dtype=np.uint64))


def gruplari_bul(metinler):
    """Her mesaja bir grup numarası verir; neredeyse aynı mesajlar aynı numarayı alır."""
    rng = np.random.default_rng(42)
    a = rng.integers(1, 2**31, IMZA, dtype=np.uint64)[:, None]
    b = rng.integers(0, 2**31, IMZA, dtype=np.uint64)[:, None]
    p = np.uint64((1 << 61) - 1)
    kumeler = [_parcalar(m) for m in metinler]
    izler = np.array([((a * k + b) % p).min(axis=1) for k in kumeler])

    ebeveyn = np.arange(len(kumeler))

    def kok(i):
        while ebeveyn[i] != i:
            ebeveyn[i] = ebeveyn[ebeveyn[i]]
            i = ebeveyn[i]
        return i

    satir = IMZA // BANT
    for bant in range(BANT):
        kovalar = {}
        for i, iz in enumerate(izler[:, bant * satir:(bant + 1) * satir]):
            kovalar.setdefault(iz.tobytes(), []).append(i)
        for uyeler in kovalar.values():
            ilk = uyeler[0]
            for j in uyeler[1:]:
                ki, kj = kok(ilk), kok(j)
                if ki == kj:
                    continue
                ortak = len(np.intersect1d(kumeler[ilk], kumeler[j], assume_unique=True))
                if ortak / (len(kumeler[ilk]) + len(kumeler[j]) - ortak) >= ESIK:
                    ebeveyn[kj] = ki
    return np.array([kok(i) for i in range(len(kumeler))])
