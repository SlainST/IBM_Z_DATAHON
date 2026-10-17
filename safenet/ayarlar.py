"""ayarlar.toml dosyasını okur ve birleştirir: varsayılan + profil + platforma özel değerler + kanal.

Platformları SafeNet ekibi ayarlar.toml'da yapılandırır. API, isteği yapan platformu API anahtarından tanır
ve o platformun ayarlarını kullanır.

Kullanım:
    from ayarlar import ayarlar_yukle, profil_yukle
    a = ayarlar_yukle("demo_oyun")             # bir platformun ayarları (birebir sohbet)
    a["gizli_puan"]["susturma_esigi"]          # 80 (oyun profili 90, platforma özel 80)
    p = profil_yukle("egitim")                 # hazır profilin kendisi (platformdan bağımsız)
"""
import copy
import tomllib
from pathlib import Path

DOSYA = Path(__file__).with_name("ayarlar.toml")


def _oku():
    with open(DOSYA, "rb") as f:
        return tomllib.load(f)


def _birlestir(taban, ust):
    """ust'teki değerleri taban'ın üzerine yazar (iç içe tablolar dahil)."""
    for anahtar, deger in ust.items():
        if isinstance(deger, dict) and isinstance(taban.get(anahtar), dict):
            _birlestir(taban[anahtar], deger)
        else:
            taban[anahtar] = deger
    return taban


def _kontrol_et(a):
    """Yanlış girilmiş ayarları anlaşılır bir hatayla durdurur."""
    m, g = a["mesaj"], a["gizli_puan"]
    for ad in ["sari_esigi", "cok_kotu_esigi", "tehdit_esigi", "nefret_esigi", "spam_kufur_orani"]:
        if not 0 <= m[ad] <= 1:
            raise ValueError(f"mesaj.{ad} 0 ile 1 arasında olmalı (şu an {m[ad]})")
    if m["sari_esigi"] >= m["cok_kotu_esigi"]:
        raise ValueError("mesaj.sari_esigi, mesaj.cok_kotu_esigi'nden küçük olmalı")
    if m["sari_davranis"] not in ("teslim", "teslim_ve_uyari_onerisi", "beklet"):
        raise ValueError(f"mesaj.sari_davranis geçersiz: {m['sari_davranis']}")
    if not 0 < g["iyilesme_orani"] < 1:
        raise ValueError("gizli_puan.iyilesme_orani 0 ile 1 arasında olmalı")
    if not 1 <= g["iyilesme_esigi"] <= g["iyilesme_penceresi"]:
        raise ValueError("gizli_puan.iyilesme_esigi 1 ile iyilesme_penceresi arasında olmalı")
    if g["uyari_esigi"] >= g["susturma_esigi"]:
        raise ValueError("gizli_puan.uyari_esigi, gizli_puan.susturma_esigi'nden küçük olmalı")
    if g["susturma_sonrasi_puan"] >= g["susturma_esigi"]:
        raise ValueError("gizli_puan.susturma_sonrasi_puan, susturma_esigi'nden küçük olmalı")
    if not 0 < a["iliski"]["engel_esigi"] <= g["susturma_esigi"]:
        raise ValueError("iliski.engel_esigi 0'dan büyük ve gizli_puan.susturma_esigi'nden küçük ya da eşit olmalı")
    k = a["kimlik"]
    if not 0 <= k["zararli_bahsetme"] <= k["genelleme"] <= k["hedefli_saldiri"]:
        raise ValueError("kimlik puanları sıralı olmalı: zararli_bahsetme <= genelleme <= hedefli_saldiri")
    if a["kanal"].get("kimlik_carpani", 1.0) <= 0:
        raise ValueError("kanal.kimlik_carpani 0'dan büyük olmalı")


def _hazirla(hepsi, profil, ozel, kanal):
    if profil not in hepsi["profil"]:
        raise ValueError(f"Bilinmeyen profil: {profil}. Seçenekler: {list(hepsi['profil'])}")
    if kanal not in hepsi["kanal"]:
        raise ValueError(f"Bilinmeyen kanal: {kanal}. Seçenekler: {list(hepsi['kanal'])}")
    a = _birlestir(copy.deepcopy(hepsi["varsayilan"]), hepsi["profil"][profil])
    a = _birlestir(a, ozel)
    a["kanal"] = copy.deepcopy(hepsi["kanal"][kanal])
    _kontrol_et(a)
    return a


def profil_yukle(profil="sosyal_medya", kanal="birebir"):
    """Hazır bir profilin ayarları (hiçbir platforma özel değer eklenmeden)."""
    a = _hazirla(_oku(), profil, {}, kanal)
    a["secim"] = {"profil": profil, "kanal": kanal}
    return a


def ayarlar_yukle(platform_id, kanal="birebir"):
    """Bir platformun ayarları: varsayılan + platformun profili + platforma özel değerler + kanal."""
    hepsi = _oku()
    if platform_id not in hepsi.get("platform", {}):
        raise ValueError(f"Tanımlı olmayan platform: {platform_id}. Tanımlı platformlar: {list(hepsi.get('platform', {}))}")
    ozel = copy.deepcopy(hepsi["platform"][platform_id])
    profil = ozel.pop("profil")
    a = _hazirla(hepsi, profil, ozel, kanal)
    a["secim"] = {"platform": platform_id, "profil": profil, "kanal": kanal}
    return a


if __name__ == "__main__":
    # python ayarlar.py  ->  hazır profilleri yan yana ve tanımlı platformları gösterir
    hepsi = _oku()
    profiller = list(hepsi["profil"])
    satirlar = [("mesaj", "sari_esigi"), ("mesaj", "cok_kotu_esigi"), ("mesaj", "tehdit_esigi"),
                ("mesaj", "nefret_esigi"), ("mesaj", "sari_davranis"), ("mesaj", "oyun_dili_serbest"),
                ("gizli_puan", "iyilesme_esigi"), ("gizli_puan", "iyilesme_orani"),
                ("gizli_puan", "uyari_esigi"), ("gizli_puan", "susturma_esigi"), ("iliski", "engel_esigi"),
                ("kimlik", "zararli_bahsetme"), ("kimlik", "genelleme"), ("kimlik", "hedefli_saldiri")]
    tum = {p: profil_yukle(p) for p in profiller}
    print("HAZIR PROFİLLER")
    print(f"{'ayar':<32}" + "".join(f"{p:>26}" for p in profiller))
    for bolum, ad in satirlar:
        print(f"{bolum + '.' + ad:<32}" + "".join(f"{str(tum[p][bolum][ad]):>26}" for p in profiller))
    print("\nTANIMLI PLATFORMLAR")
    for pid, ayar in hepsi.get("platform", {}).items():
        ozel = {k: v for k, v in ayar.items() if k not in ("ad", "profil")}
        ayarlar_yukle(pid)  # hatalı bir değer varsa burada durur
        print(f"  {pid:<14} profil={ayar['profil']:<13} özel değerler={ozel or 'yok'}  ({ayar.get('ad', '')})")
