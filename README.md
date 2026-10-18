# SafeNet: IBM LinuxONE üzerinde mesaj güvenliği API'si

**Sysplex Squad · IBM Z Datathon 2026.** Bu sayfa projenin **son durumunu** anlatıyor: ne yapıldı, ne ölçüldü,
hangi dosya nerede, ekipte kimin ne yapması gerekiyor. Kodun ayrıntılı teknik dokümanları İngilizce:
[`safenet/README.md`](safenet/README.md) (başlangıç noktası) ve [`safenet/docs/`](safenet/docs/).

## SafeNet ne yapar

SafeNet bir uygulama değil, bir **API**. Bir platform (okul uygulaması, oyun, mesajlaşma) birebir bir mesajı
teslim etmeden önce SafeNet'e sorar; SafeNet **alıcının ne göreceğine** karar verir:

| Karar | Alıcı ne görür | Örnek |
|---|---|---|
| `allow` | mesajın kendisi | "see you tomorrow at practice" |
| `censor` | küfürleri yıldızlı mesaj | "f***, I missed the bus again" |
| `hold` | moderatör bakana kadar hiçbir şey | okul platformunda hakaret; birinin aktardığı tehdit |
| `block` | hiçbir şey | "But if you show up on Friday I'll f*cking break your legs." |

Cevapta kararın sebebi, kategori (`insult`, `gender`, `religion`, `race`, `sexual`, `threat`), kararı veren cümle
ve kelimeler de gelir. SafeNet her platform, grup ve gönderen için **gizli puan** tutar: saldırmaya devam eden önce
uyarılır, sonra kısıtlanır; A'nın B'ye yazdıkları biriktiğinde A'nın mesajları B'ye gitmez, başkalarına gitmeye
devam eder. **Mesaj metni hiçbir yerde saklanmaz.** Cevap birkaç milisaniyede, IBM z17 (s390x) sunucusundan gelir.

## Son durum (18 Ekim 2026)

Her şey LinuxONE sunucusunda, modelin **hiç görmediği** veriyle ölçüldü (tasarım PDF'inin 9. bölümündeki hedefler):

| Hedef | Sonuç | Hedef değer | Tuttu mu |
|---|---|---|---|
| Zararlı mesaj yakalama (37,588 test mesajı, sosyal profil) | **86.6 %** | ≥ 85 % | evet |
| Masum mesajda yanlış alarm (bekletildi veya engellendi) | 0.6 % | ≤ 5 % | evet |
| Masum benzer cümleler ("I fed the duck", "I'm a proud Muslim", "Scunthorpe") engellenen | 0 / 124 | hiçbiri | evet |
| Kategori doğruluğu (insanların verdiği etiketler) | 96.4 % | ≥ 75 % | evet |
| Mesaj başına süre, p50 / p99 | 2.4 / 8.3 ms | < 10 ms | evet |
| Zorbalık sohbetlerinde mağdurun zorbanın mesajlarını almaması | 6 / 6 | hepsi | evet |
| Geliştirici 2'nin değerlendirme seti (104 mesaj × 3 platform; dev / test kısmı) | 310 / 312 (183/183, 127/129) | | |
| Gri bölge (insanların anlaşamadığı 70 mesaj) sarı | 24 % | çoğu | hayır |
| Simülasyon: kısıtlanması gerekenler / gerekmeyenler (sadece kişi tipine göre) | 87 % / 6 % (89 % / 11 %) | ≥ 90 % / ≤ 5 % | hayır, yakın |
| Yük: 3 vCPU, gerçek mesajlar, concurrency 4 | ~870 mesaj/sn | | |

**Zararlı mesajların ne kadarı yakalanıyor** (8,362 zararlı test mesajı):

| | Sosyal | Okul | Oyun |
|---|---|---|---|
| Engellendi (alıcı hiç görmüyor) | 47.4 % | 52.2 % | 45.7 % |
| Sansürlendi veya moderatöre bekletildi | 39.2 % | 34.8 % | 38.0 % |
| **Toplam yakalanan** | **86.6 %** | **87.0 %** | **83.7 %** |
| Kaçan (olduğu gibi teslim) | 13.4 % | 13.0 % | 16.3 % |

Kaynağa göre yakalanan (sosyal): cyberbullying 91 %, Wikipedia 83 %, Kaggle 82 %, Twitter 59 %.

**Doğru kategori:** Model 2, insanların kategori verdiği zararlı mesajlarda 96.4 % doğru (race 99.3 %, religion
97.0 %, gender 93.1 %, insult 90.5 %). API'nin sarı ya da kırmızı işaretleyip yazdığı kategori 90.4 % doğru. Seyrek
kategoriler zayıf: sexual 65.5 %, threat 60.4 % (açık tehdit ve cinsel taleplerde kategoriyi kurallar koyuyor).

**Karşılaştırma** (aynı test): bugünkü son hâl 86.6 %; aynı motor eski eşiklerle v4 85.9 %, v3 85.2 %, modelsiz yedek
kurallar (fallback) 54.4 %. Bugün sabah, bu iyileştirmelerden önce: 84.0 %. Ayrıntılar ve tutmayan hedeflerin nedenleri:
[`safenet/docs/RESULTS.md`](safenet/docs/RESULTS.md).

## Nasıl karar veriyor

1. **Gizlenmiş küfür** çözülür ve yıldızlanır: `f*ck`, `sh1t`, `f u c k`, Kiril harfler, görünmez karakterler, `kys`.
2. Mesaj **cümlelere** ayrılır; en kötü cümle karar verir. 300 karaktere kadar mesajlar bir de **bütün olarak**
   skorlanır (zarar cümlelere dağılmışsa, örneğin "you! you blocked me worm why!!"); bu skor en fazla sarı yapar.
3. **Model 1** her cümleye 0-1 arası zararlılık skoru verir, bir de küfürsüz hâline: "f*ck, I missed the bus"
   sadece küfür, "fuck you, nobody likes you" kötü niyet.
4. **Model 2** kategoriyi verir.
5. **Kurallar** (`safenet/ml/rules.py`) skorları ayarlar:
   - açık ve sık görülen örtük tehditler, kendine zarar teşviki, şantaj → en az 0.95, kırmızı
     ("i'll break your legs", "you'll regret coming to school tomorrow", "kys", "or i'll post your pics");
   - ağır zorbalık, cinsel talep, yabancı düşmanlığı → en az 0.92, kırmızı
     ("nobody likes you", "send me a pic of you in your underwear", "go back to your country");
   - düz hakaret → en fazla 0.72, sarı ("you are an idiot" engellenmez, sansürlenir).
6. **Korumalar:**
   - Sadece geçen bir kimlik puan eklemez ("I'm a proud Muslim").
   - Mağdurun anlattığı susturulmaz ("I was bullied", "some kids keep calling me fat and ugly").
   - Önyargıyı eleştiren ceza almaz ("stop making gay jokes", "how is making fun of trans people funny?").
   - Birinin aktardığı tehdit engellenmez, moderatöre gider ("he told me ...").
   - Oyun platformunda, mesajda oyun bağlamı varsa oyun kelimeleri serbest ("gg, I will kill you next round").
   - Olası yazım hatası affedilir ("I fed the fuck at the lake" → "duck"?).
   - İçinde slur harfleri olan masum kelimeler slur sayılmaz ("snigger", "raccoon").
   - Spam: çok link, tekrar eden kelime ya da kalıp.
7. **Renk ve karar:** kırmızı → `block`; sarı → `censor` (okul profilinde `hold`); yeşil → `allow` (küfür varsa `censor`).
8. **Gizli puanlar** (sosyal profil): sarı +10, kırmızı +25, tehdit +40, küfür kelime seviyesi kadar (mesaj başına en
   fazla 15), gizlenmiş küfür kelime başına +3, kimliğe saldırı ayrıca. 40'ta uyarı önerisi, 70'te kısıtlama (5 dk,
   sonra 1 saat, sonra 24 saat). A → B puanı 40'a ulaşınca A'nın B'ye mesajları teslim edilmez. Puan zamanla
   düşmez; son 10 mesajın 7'si temizse her temiz mesaj puanı %10 azaltır.

Bütün eşikler ve puanlar `safenet/ayarlar.toml`'da; her platform bir profil seçer (sosyal medya, eğitim, oyun,
kurumsal). Demo platformları: `demo_sosyal`, `demo_okul`, `demo_oyun`.

## Modeller (v4)

| | Model 1: zararlı mı? | Model 2: hangi kategori? |
|---|---|---|
| Yapı | kelime (1-2) ve harf (2-5) n-gram, HashingVectorizer → LogisticRegression, C = 8 | aynı tür özellikler, LogisticRegression (one-vs-rest), C = 128 |
| Eğitim | 150,409 mesaj + 12,462 sentetik cümle; 7,604 Wikipedia yorumunda soft label | sadece zararlı mesajlar (35,826), kategoriler eşit ağırlıkta |
| Test | ROC-AUC 0.9745, PR-AUC 0.9347, F1 0.854 (v3: 0.9739 / 0.9336 / 0.851) | macro F1 0.867 |
| Dosya, hız | 11.3 MB, ~0.5 ms / çağrı | 23.1 MB |

- **Soft label (v4'ün yeniliği):** her Wikipedia yorumunu ~10 kişi etiketlemiş. Etiketçiler %30-70 arasında
  bölünmüşse Model 1 0/1 yerine bu oranı öğreniyor: insanların anlaşamadığı mesaj orta skor alıyor.
- **Sentetik cümleler** (`safenet/augment.py`): kimlik kelimelerinin nötr kullanımı, tehditler ve aynı kalıpta masum
  cümleler, bir şeye küfür ile birine küfür, mağdur anlatımları, masum benzer kelimeler. Test, YouTube,
  değerlendirme seti ve masum örnek cümleler eğitimde hiç kullanılmıyor.
- **Byte order:** modeller sunucuda (big-endian s390x) eğitildi; laptop'ta (x86) yanlış skor verirler. API
  `models/model_info.json`'a bakıp yanlış makinede eğitilmiş modeli reddeder ve fallback kurallarına geçer.
  **Modelleri her zaman sunucuda eğitin ve ölçün.**
- Model dosyaları git'te değil. v4: sunucuda `~/work/fevzi/integration/safenet/models/` (`model1.joblib`,
  `model2.joblib`, `model_info.json`); v3 yedeği: `~/work/fevzi/integration/models_v3/`.

Ayrıntı: [`safenet/models/README.md`](safenet/models/README.md).

## Bu branch'te `main`'e göre ne var

- **Modeller (Geliştirici 1):** v3 ve v4 eğitimi (`train.py`, `augment.py`), `model_info.json` ve byte order
  koruması, kural katmanı (`safenet/ml/rules.py`), bütün mesaj skoru, ölçüm araçları (`measure.py`: PDF'in hedefleri,
  `simulate.py`: 1:1 sohbet simülasyonu).
- **Geliştirici 2'nin işi:** değerlendirme seti (`degerlendirme_seti.csv`, `degerlendir.py`) ve karar motoru dokümanı
  bu branch'te. Bulduğu üç sorun kodda düzeltildi: oyun kelimeleri sadece oyun bağlamında serbest, açık yazılmış
  "kill yourself" tanınıyor, tekrar eden kalıp ("follow me" × 8) spam sayılıyor. `ayarlar.toml` **değiştirilmedi**.
- **Geliştirici 3 için:** hazır Python client (`safenet/client/safenet_client.py`), WhatsApp sohbet dökümü ve YouTube
  yorumları adapter'ları, jüri demosu (`safenet/demo.py`), gerçek mesajlarla load test (`bench/load_test.py --texts`),
  sunucu rehberi (`safenet/deploy/README.md`).
- **API:** cevapların dokümante modelleri ve JSON Schema'ları (`safenet/schemas/`), `/health`'te model sürümü.
  API sözleşmesi (alanlar, tipler) değişmedi.
- **SlainST'in branch'inden (`claude/full-integration-v3`, bu branch'in üstüne kurulmuştu):** değerlendirme setinin
  dev/test ayrımı, `models_dev` ve `measure.py --dev`, validation'da ayarlanmış sarı eşikleri (varsayılan 0.46, okul
  0.44), "h e l l o" düzeltmesi, 🖕, çocukların kendine zarar argosu ("unalive yourself", "go drink bleach").
- **Geliştirici 2'nin branch'inden:** önbellekte mesaj metni tutulmuyor (yıldızlı metin her cevapta yeniden
  yapılıyor), spam sayıları `ayarlar.toml`'da, Windows laptop'larda kurulum.
- **Diğer:** GitHub Actions ile testler, kullanılmayan v0.1 prototip modülleri silindi, dokümanlar güncellendi.

Testler: lokalde 168 geçti (7 model testi model dosyası olmadan atlanır), sunucuda v4 modelleriyle 175 geçti.
Veritabanı şeması ve paketler değişmedi.

## Kimin ne yapması gerekiyor

### Herkes
- [ ] Branch'i gözden geçirin; hangi parçaların `main`'e gireceğine birlikte karar verin.
- [ ] Kural: her şey `pytest` yeşilken birleşir; API sözleşmesi (`docs/API.md`, `schemas/`) üç kişinin onayıyla değişir.

### Geliştirici 2 (kurallar, ayarlar, testler)
Ölçülmüş öneriler; `ayarlar.toml` sadece senin dosyan, karar senin:
- [x] **Sarı eşikleri:** validation'da ayarlandı ve uygulandı: varsayılan 0.46, okul 0.44 (test: sosyal 86.7 %
      yakalama; okulda masum bekletme 5.2 %).
- [x] **Spam sayıları** `ayarlar.toml`'a taşındı (`spam_link_sayisi`, `spam_tekrar_sayisi`, `spam_tekrar_orani`).
- [ ] **Simülasyon:** "kısıtlanmalı" artık kişi tipi **ya da** tehdit / slur atmış olmak (etikete göre): 87 % / 6 %.
      Puanlarla oynamak iki hedefi birbirine feda ediyor (denendi: tek mesaja 45 sınırı → 82 % / 8 %).
- [ ] **1:1'de tek mesajın puanı:** kimlik içeren tek bir kırmızı mesaj 25 + 30 × 1.5 = 70 puanla gönderenini anında
      kısıtlıyor; simülasyonda haksız kısıtlanan 6 kişinin 3'ü böyle. Tehdit dışındaki tek bir mesaja üst sınır
      konursa "kısıtlanmaması gerekenler" 11 %'den hedefe (≤ 5 %) yaklaşabilir. `python simulate.py --users` ile ölçün.
- [ ] **Arkadaşlar arası küfür:** küfürleşen iki arkadaşın puanı 70'e ulaşmıyor (simülasyonda kaçan 3 kişinin 2'si).
      `kelime_carpani` ya da mesaj başı küfür sınırı ile "kısıtlanması gerekenler" 89 % → ≥ 90 % olabilir.
- [ ] **Test değişikliğini onayla:** "oyunda `I will kill you` serbest" testi, "`gg, I will kill you next round`
      serbest, `I will kill you and your whole family` engellenir" olarak değişti (`tests/test_check.py`).
- [ ] Kuralları gözden geçir: `safenet/ml/rules.py` ve `safenet/docs/DECISION_ENGINE.md`.

### Geliştirici 3 (LinuxONE, deploy, demo)
- [ ] Ekip onaylarsa deploy (aşağıda). Sonra `demo.py` ile kontrol.
- [ ] Load test'i canlı kurulumda (Postgres ile) tekrarla: `bench/load_test.py --texts ...` (sonuçlar `bench/RESULTS.md`).

### Geliştirici 1 (modeller)
- [x] Önyargıyı eleştiren cümleler için kural (`rules.CONDEMN`): kimlik ve eleştirilen zarar kelimeleri olmadan bir
      daha skorlanıyor; okuyucuya etiket ya da slur varsa uygulanmıyor.
- [ ] Gürültülü etiketleri temizlemek ve tweet'ler için de graded label (aşağıda "Sonraki adımlar").

### Ekip kararı gerekenler
- [ ] `docs/API.md`'de `harm` alanının açıklamasına bir cümle eklendi: mesajı sarı yapan bütün mesaj skoruysa `harm`
      o skoru gösteriyor. Alan ve şema aynı, sadece anlamı genişledi.

## Canlı demo (video ve jüri için)

```bash
cd safenet
python demo_web.py --keys-file C:\Users\<sen>\Downloads\api_keys.env    # sunucuya SSH tüneli açar
```

Tarayıcıda http://127.0.0.1:8600 açılır: Ali Ayşe'ye yazar, her mesaj canlı SafeNet API'sinden (LinuxONE) geçer.
Sayfada Ayşe'nin ne gördüğü (teslim / yıldızlı / moderatörde / engellendi), sebep, kategori, kararı veren kelimeler,
Ali'nin gizli puanı ve Ali → Ayşe ilişkisi görünür; üstten platform (sosyal / okul / oyun) seçilir, soldaki örneklere
tıklamak yeterli. Anahtarlar tarayıcıya gitmez. Komut satırı demosu: `python demo.py`.

## Telefonda test: Telegram ve WhatsApp

**Telegram (canlı):** bot her mesajı canlı SafeNet'ten geçirir. @BotFather'da `/newbot` ile token alın, `/setprivacy`
→ bot → **Disable**. Sonra:

```bash
cd safenet
python client/telegram_bot.py --token <token> --keys-file C:\Users\<sen>\Downloads\api_keys.env   # --platform demo_okul
```

Bota özel mesaj yazın: her mesaja alıcının ne göreceğini cevaplar (karar, sebep, kategori, puan, süre). Gruba ekleyip
"mesaj silme" ve "üyeleri kısıtlama" yetkili yönetici yaparsanız grubu yönetir: zararlıyı siler, küfrü yıldızlayıp
yeniden yazar, uyarır, kısıtlanan kişiyi süre bitene kadar susturur. Birine cevap (reply) olarak yazılan mesaj o kişiye
yazılmış sayılır (A → B koruması).

**WhatsApp (sohbet dökümü):** WhatsApp kişisel mesajlara anlık erişime izin vermiyor; sohbeti telefonda "Sohbeti dışa
aktar" (medyasız) ile .txt alıp geçirin: her mesajda karşı tarafın ne göreceği çıkar. Önce tünel
(`ssh -N -L 8000:127.0.0.1:8000 safenet`), sonra:

```bash
SAFENET_KEY=<demo_sosyal anahtarı> python client/whatsapp_chat.py sohbet.txt --only-flagged
```

## Çalıştırma

Lokalde (laptop):

```bash
cd safenet
pip install -r requirements/dev.txt
python -m pytest                                    # testler (model dosyası olmadan fallback kurallarıyla)
SAFENET_DEV_KEYS=1 uvicorn safenet.api:app --port 8000   # SADECE lokalde: "dev-demo_sosyal" gibi anahtarlar
```

Sunucuda, kendi klasörünüzde, `veri/` ile (git'te değil; `veri_hazirla.py` üretir) ve sunucuda eğitilmiş modellerle:

```bash
nice -n 10 .venv/bin/python train.py          # ~17 dk, tek CPU; soft label için veri/ham/toxicity_parsed_dataset.csv gerekir
nice -n 10 .venv/bin/python measure.py        # PDF'in bütün hedefleri, ~5 dk
.venv/bin/python simulate.py --users          # 1:1 sohbet simülasyonu, kullanıcı başına
.venv/bin/python degerlendir.py --hatalar     # Geliştirici 2'nin seti, sadece tutmayanlar
python demo.py --url http://127.0.0.1:8000 --keys-file <anahtar dosyası>   # jüri demosu (anahtarlar ekrana basılmaz)
```

Sunucuda sadece 3 vCPU var: uzun iş (eğitim, ölçüm) başlatmadan önce ekibe haber verin.
`SAFENET_DEV_KEYS=1` sunucuda asla açılmaz; anahtarlar ve `safenet.env` git dışında kalır.

## Deploy (v4, ekip onayıyla)

**Durum (18 Ekim, 15:33): canlıda `main` ve v4 modelleri çalışıyor.** Sunucudaki `~/IBM_Z_DATAHON` `main`'de
(6ee7003). Canlı kontrol: "see you tomorrow" → `allow`, "you are an idiot" → `censor`, PDF'in tehdit örneği →
`block` (Postgres ile).

- Güncelleme: `cd ~/IBM_Z_DATAHON && git pull && systemctl --user restart safenet-api`.
- v2'ye geri dönmek gerekirse: `rm -f safenet/models/model_info.json && cp
  ~/work/fevzi/models_v2_canli_yedek_20261018_150925/* safenet/models/ && git checkout 7d2871f` ve restart.
- v4 modellerinin yedeği: `~/work/fevzi/models_v4_yedek/`.

Modeller değişirse (yeni eğitim) adımlar:

Bugünkü sonuçlar v4 modelleri **ve** bu branch'teki motorla birlikte ölçüldü; sadece model dosyalarını kopyalamak
aynı sonucu vermez.

```bash
# 1) Kod: bu branch main'e birleştikten sonra
cd ~/IBM_Z_DATAHON && git pull
# 2) Canlıdaki modellerin (v2) yedeği, kendi klasörünüze
cp -r safenet/models ~/work/<isminiz>/models_v2_yedek
# 3) v4 modelleri (üç dosya, model_info.json dahil)
cp ~/work/fevzi/integration/safenet/models/{model1.joblib,model2.joblib,model_info.json} safenet/models/
# 4) Yeniden başlat ve kontrol et
systemctl --user restart safenet-api
curl -s localhost:8000/health    # "model1": "loaded", "model_version": {"trained": "2026-10-18T09:09:58+0000", ...}
```

Geri almak için: `~/work/<isminiz>/models_v2_yedek` içindekileri `safenet/models/`'e kopyalayıp yeniden başlatın.
Ayrıntı: [`safenet/deploy/README.md`](safenet/deploy/README.md).

## Dosya haritası

| Yol | Ne |
|---|---|
| [`safenet/README.md`](safenet/README.md) | kodun başlangıç noktası (İngilizce) |
| `safenet/safenet/api/` | FastAPI uygulaması, istek/cevap modelleri, API anahtarları |
| `safenet/safenet/engine/` | analiz (cümleler, modeller, kurallar), renk ve karar, gizli puanlar |
| `safenet/safenet/ml/` | modellerin yüklenmesi ve fallback kuralları (`models.py`), kural katmanı (`rules.py`) |
| `safenet/safenet/pipeline/` | küfür bulma ve yıldızlama, cümleler, oyun kelimeleri, yazım hatası, spam |
| `safenet/safenet/state/` | Postgres ya da bellek: puanlar, ilişkiler, sayaçlar (metin yok) |
| `safenet/ayarlar.toml` | bütün eşikler, puanlar, profiller, platformlar (Geliştirici 2) |
| `safenet/train.py`, `safenet/augment.py` | model eğitimi ve sentetik cümleler |
| `safenet/measure.py`, `safenet/simulate.py`, `safenet/degerlendir.py` | ölçüm: PDF hedefleri, simülasyon, değerlendirme seti |
| `safenet/client/`, `safenet/demo.py` | client, WhatsApp ve YouTube adapter'ları, jüri demosu |
| `safenet/bench/` | load test ve sonuçları |
| `safenet/docs/` | API, karar motoru, durum (state), sonuçlar |
| `safenet/models/README.md` | modeller: nasıl eğitildi, sonuçlar, threshold önerileri, sınırlar |
| `safenet/deploy/` | LinuxONE kurulumu, systemd servisi, sunucu rehberi |
| `birlesik_veri.csv`, `youtube_test.csv`, `karistirilabilir_kelimeler.csv` | hazırlanmış veri |

## Bilinen sınırlar

- Sadece İngilizce (eğitim verisi gibi).
- Gri bölge: insanların anlaşamadığı mesajların sadece 23 %'ü sarı; tweet'lerde etiketçi oranı yok.
- İnce önyargılı tweet'ler 57 % yakalanıyor; bilinmeyen örtük tehditler kaçıyor ("i know your address and i am
  coming over tonight").
- Uzun YouTube yorum zincirlerinde yanlış alarm 17 % (tek kötü cümle bütün zinciri işaretliyor).
- Okul profili masum mesajların 5.9 %'unu moderatöre bekletiyor (öneri yukarıda).
- Simülasyon hedefleri puan ayarlarından dolayı tutmuyor (öneriler yukarıda).

## Sonraki adımlar (öneriler)

1. Gürültülü etiketleri temizlemek: model ile etiketin en çok çeliştiği ~1,000 eğitim mesajını yeniden etiketlemek.
2. Laptop'ta büyük bir toxicity modelinden bütün veriye soft label almak (distillation); sunucuda torch gerekmez,
   tweet'ler de graded label kazanır.
3. Gerçek sohbet verisi: 1-2 bin gerçekçi DM, okul ve oyun mesajı ile ölçmek ve eğitmek.
4. Moderatör geri bildirimi: bekletilen mesajlarda moderatörün kararı etiket olarak dönsün, periyodik yeniden eğitim.
5. Türkçe desteği: Türkçe veri setleriyle ikinci bir Model 1.
6. IBM Z: z17'nin AI hızlandırıcısı (NNPA) için IBM Snap ML ya da IBM Z Deep Learning Compiler denemek.

## Ekip

| Rol | Sorumluluk |
|---|---|
| Geliştirici 1: modeller | eğitim, sentetik veri, kural katmanı, ölçümler |
| Geliştirici 2: kurallar | ayarlar, kelime listeleri, kimlik analizi, değerlendirme seti, testler |
| Geliştirici 3: LinuxONE | sunucu, deploy, load test, adapter'lar, demo |

Lisans: MIT ([LICENSE](LICENSE)).
