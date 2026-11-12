# Plan v10 — Odak: pazartesi sabahının nakit cevabı

*2026-11-06. Plan v9'un tezini korur, sırasını ve kapsamını daraltır. v9'un K2–K4 aşamaları bu planın ölçütü tutana kadar bekler. Süreler tek geliştirici için kaba tahmindir; pilot bulgularıyla yeniden yazılır.*

## 1. Hedef

> **8 hafta içinde 3 gerçek aile şirketi, her pazartesi sabahı "bu hafta param yetiyor mu, kime ödemeliyim, kimden tahsil etmeliyim" sorusunun cevabını bizden alsın ve en az 6 hafta üst üste kullansın.**

Tek kullanıcı (patron ya da finans sorumlusu), tek akış:

**belgeyi bağla → defter → Nakit Radarı → pazartesi bülteni → karar**

Bu akışa hizmet etmeyen iş, ölçüt tutana kadar bekler.

## 2. Neden bu odak

- **Genişlik var, kanıt yok.** Yaklaşık 38 ekran ve 8 rol var. Hiçbir gerçek şirket ürünü kullanmadı.
- **Hatalar canlıda çıkıyor.** Bulunan ciddi hataların neredeyse tamamı testlerden değil canlı denemelerden çıktı. Gerçek bir şirketin dağınık verisi henüz ürüne değmedi.
- **Ürün bugün pilota çıkamaz.** Staging ortamı yok, Postgres ve Redis yok, worker yolu bu makinede test edilemiyor. Uygulama yerel SQLite ile çalışıyor.
- **Nakit, değeri en hızlı gösteren yer.** v9 da kurumsallaşmanın kapısını nakit değeri olarak koymuştu (K1). Patron ritmi, haftalık bir sorusuna cevap aldığı için benimser.

## 3. Bugünkü durum

| Parça | Durum |
|---|---|
| Tek şirket defteri, tekilleştirme (#14) | master'da |
| e-Fatura vadeleri, açık kalemler (#15) | master'da |
| Banka mutabakatı, ödeme davranışı (#16) | master'da |
| Şirket görünümü defterden (#17) | master'da |
| Nakit Radarı: 13 hafta, kanıtlanmış banka bakiyesi | `feat/v9-k1-cash-radar` (`e8fffb7`), push edilmedi; ekranı yok |
| Tekrarlayan ödemeler, vergi/SGK takvimi, çek/senet | Yok; radar bunları "dahil değil" diye listeliyor |
| Tahmin kaydı ve notlama | Yok |
| Pazartesi bülteni | Yok |
| Staging ortamı | Yok |

## 4. Aşamalar

### O0 — Kapsamı daraltmak · Hafta 0

- **Menü:** Akışın dışındaki ekranlar menüden kalkar, kod silinmez.
  - **Kalanlar:** Başlangıç, Verilerimi Bağla, Nakit Radarı, Command Center, P&L, Cash Flow, Ayarlar.
  - **Gizlenenler:** CTO, CMO, COO, CHRO, CEO, boardroom, simülasyon, duyarlılık, şablonlar, intelligence.
- **Bayrak:** Gizleme bir org ayarıdır. Demo ve eski kullanıcılar etkilenmez.
- **Karar:** Segment ve pilot listesi yazılı olarak bu plana işlenir (§7).

**Bitti sayılır:** Yeni bir pilot org yalnızca akışın adımlarını görüyor.

### O1 — Pilota çıkabilir hale gelmek · Hafta 1–2

- **Staging:** Postgres, Redis ve worker'ın ayrı süreç olarak çalıştığı bir ortam, günlük yedek ve geri dönüş prosedürü.
- **Hukuki zemin:** KVKK aydınlatma metni, veri işleme sözleşmesi, açık rıza akışı. Hukukçu gözden geçirir; metni ajan yazmaz.
- **Gözlem:** Her pilot org için hata ve yavaşlık alarmı. `AgentRun` ve SLO uç noktaları buraya bağlanır.

**Bitti sayılır:** Pilot şirket kendi tarayıcısından giriyor. Worker yolu ilk kez gerçek ortamda koşmuş ve canlı denenmiş.

### O2 — Gerçek veri girişi · Hafta 1–3 (O1 ile paralel)

- **Kaynaklar:** Paraşüt veya Logo, bakiye sütunlu banka ekstresi, e-Fatura.
  - Paraşüt API sözleşmesi bugün doğrulanmamış; ilk pilotla doğrulanır.
- **İlk kurulum:** Pilotun kendi dosyalarıyla yapılır, örnek dosya kullanılmaz.
  - Okunamayan her satır raporlanır.
  - Gerçek dosyadan çıkan her hata, o dosyadan türetilmiş bir test olur.
- **Radar ekranı:** `/ledger/cash-radar`'ın frontend kapısı. Başlangıç nakdinin tarihi, "dahil değil" listesi ve vadesiz kalemler ekranda görünür.

**Bitti sayılır:** Her pilotun ilk kurulumu 30 dakikanın altında. Radar, pilotun gerçek banka bakiyesinden başlıyor.

### O3 — Radarı tamamlamak · Hafta 3–5

- **Tekrarlayan ödemeler:** Kira ve maaş gibi kalemler geçmiş banka hareketlerinden çıkarılır. En az 3 tekrar gerekir ve kaynak satırlar gösterilir; tekrar bulunamazsa kalem eklenmez.
- **Vergi ve SGK takvimi:** Son günler resmî kaynaktan, sürümlü veri olarak tutulur. Tutarlar defterdeki hesap kodlarından hesaplanır. Kaynağı gösterilemeyen kural eklenmez.
- **Çek ve senet:** Önce pilotlardan birinin elindeki ERP raporu okunur.
- **Tahmin kaydı:** Her radar çıktısı değişmeyen bir kayıt olarak saklanır.
- **Öneri kaydı:** Radarın önerdiği her eylem (§10) makine tarafından okunabilir bir beklentiyle saklanır.

**Bitti sayılır:** Radarın "dahil değil" listesi boş, ya da kalan her madde için pilotta veri olmadığı yazılı.

### O4 — Haftalık ritim · Hafta 5–6

- **Pazartesi bülteni:** Önce e-posta. Üç cümle: radardaki değişiklik, yaklaşan yükümlülük, en önemli tek eylem.
  - Sayılar deterministik hesaplanır; LLM yalnızca metni yazar.
  - LLM yoksa şablon kullanılır.
  - Doğrulayıcı, metindeki her sayıyı kaynağıyla karşılaştırır.
- **Karar ve taahhüt kaydı:** Bültendeki eylem "yaptım / ertele / gerek yok" diye cevaplanır. Sorumlu kişi ve tarih kaydedilir. Bu, v9 K2'nin yalnızca bu akışa yeten kısmıdır.
- **Beklenti ve sonuç alanları:** Karar kaydı serbest metin değil, ölçülebilir bir beklenti taşır (§10): hangi hafta, hangi tutar, hangi bakiye. Sonuç, sahibin cevabı ve defterin kendisinden doldurulur.

**Bitti sayılır:** Bülten her pazartesi 3 pilota gidiyor; cevaplar kaydediliyor.

### O5 — Ölçmek · Hafta 6–8

- **İsabet:** Gece notlama, 4 hafta önceki tahmini gerçekleşen bakiyeyle karşılaştırır.
- **Gösterim:** Sapma bültende ve ekranda gösterilir. İlk sayı ne çıkarsa o gösterilir.
- **Öneri başarısı:** Nakit tahmininin yanında, önerilen eylemlerin işe yarayıp yaramadığı da ölçülür: eylem yapıldı mı, beklenen etki gerçekleşti mi, sahip önerileri ne oranda düzeltti (§10).
- **Rapor:** Pilot başına isabet raporu ve bu plana işlenen bulgular.

**Bitti sayılır:** 3 pilotun verisiyle ölçülmüş bir 4 haftalık sapma ve bir öneri başarı oranı var.

## 5. Ölçütler

Hedef sayı yalnızca ilk ölçütte var; ötekiler önce ölçülür, sonra hedef konur.

| Ölçüt | Kaynak | Eşik |
|---|---|---|
| Bülteni 6 hafta üst üste açan pilot | Kullanım kaydı | 3 / 3 |
| Radarın 4 haftalık sapması | Tahmin kaydı | Ölçülür, gösterilir |
| Radardan çıkan gerçek karar | Karar kaydı | En az 1 |
| Beklentisi ölçülebilir olan karar oranı | Karar kaydı | Ölçülür (hedef %100) |
| Önerinin işe yarama oranı | Beklenti ve sonuç kaydı | Ölçülür, karar türüne göre |
| Sahibin öneriyi düzeltme oranı | Karar kaydı | Ölçülür, karar türüne göre |
| İlk kurulum süresi | Pilot gözlemi | Ölçülür |
| Okunamayan satır oranı | Yükleme raporu | Ölçülür |

**Karar kapıları:**
- 4. haftada hiçbir pilot radarı haftalık açmıyorsa O4'e geçilmez; nedeni pilotla görüşülür.
- 8. haftada ölçüt tutmadıysa sonraki plan yeni özellikle değil, bulgularla yazılır.

## 6. Durdurulanlar

- **Yeni ajan ya da rol yok.** CTO, CMO, COO, CHRO ve CEO ajanları olduğu gibi kalır, menüde görünmez.
- **v9 K2'nin geri kalanı, K3 ve K4 bekler:** kurul sekreteri, boardroom hafızası, yetki devri, Endeks v2, kanıt dosyası. Ölçüt tuttuktan sonra yeniden değerlendirilir.
- **Akış dışı ekranlarda yalnızca güvenlik ve veri bütünlüğü hataları düzeltilir.**
- **Paralel ajanlar ve RLHF yapılmaz.** Darboğazımız hız değil güven; paralellik hataları daha hızlı üretir. Sahibin onay, ret ve düzeltmeleri model eğitimine değil, eval setine ve kurallara gider (§10).
- **Pilotta karşılığı olmayan iş yapılmaz.** "Güzel olur" diye özellik eklenmez; her yeni iş bir pilot bulgusuna dayanır.

## 7. Sahip kararları

| # | Karar | Önerim | Durum | Bloklar |
|---|---|---|---|---|
| 1 | Segment | 10–100 çalışanlı, vadeli satış yapan üretim veya toptan aile şirketi | Genel onay 2026-11-06 | O0 |
| 2 | Pilot şirketler | 3 aday, tanıdık şirketler veya SMMM üzerinden | Açık | O1 |
| 3 | Barındırma | Bulutta küçük bir staging (yönetilen Postgres ve Redis); sağlayıcı sizin seçiminiz | Açık | O1 |
| 4 | Hukuki gözden geçirme | Pilot öncesi KVKK ve sözleşme | Açık | O1 |
| 5 | Bülten kanalı | Önce e-posta | Önerildi | O4 |
| 6 | Gizlenen ekranlar | §4 O0 listesi | Önerildi | O0 |

v9 §8'deki öteki kararlar (yeni roller, TCMB EVDS anahtarı, mali mühür) bu planın dışında kalır.

## 8. Riskler

| Risk | Azaltma |
|---|---|
| Pilot bulunamaz | O0'dan başlayarak aranır; O1–O3 pilotsuz da ilerler, ama ölçüt pilotsuz ölçülemez |
| Gerçek veri demo gibi davranmaz | Kurulum pilotun dosyasıyla yapılır; her bulgu test olur |
| Radar yanlış alarm verir | Başlangıç yalnızca kanıtlanmış bakiye; bilinmeyen tarih yerleştirilmez; eksikler ekranda yazılı |
| Staging maliyeti ve bakımı | Küçük başlanır; yedek ve geri dönüş ilk haftada denenir |
| Kapsam yeniden genişler | §6 listesi; her PR açıklaması hangi O aşamasına hizmet ettiğini yazar |
| Dağınık gerçek KOBİ verisi elimizde yok | Zor durum üreteci vekildir (§13.3); üretecin bilmediği zorlukları yalnızca gerçek veri gösterir. İlk gerçek veri bulunduğunda her bulgu üretece ve teste eklenir |
| Tek geliştirici darboğazı | Aynı anda tek açık PR zinciri |

## 9. Doğrulama

- Her aşama: `python scripts/verify.py` exit 0; `backend/app/agents/` dokunuşunda `pytest tests/test_agents/ -q`.
- Fixture'lar kaynaktan yazılır; O2'den itibaren kaynak, pilotun kendi dosyasıdır.
- Her aşama canlı denenir: staging'de, kullanıcının gördüğü ekranla.
- CLAUDE.md DISPATCH: yetki ve hız sınırı değişiklikleri, silen migration'lar ve production port değişiklikleri insana gider. O1'deki staging port ve compose değişiklikleri bu kapsamdadır.

## 10. Yapay zeka ve yönetim katmanı: karar kalitesi döngüsü

Gücümüz, yapay zekayı yönetim katmanıyla birleştirmek. Bunun kanıtı rapor üretmek değil, **kararın sonucunu ölçmek**. Bugünkü durum:

| Var | Yok |
|---|---|
| Sayıları LLM üretmez; defter, mutabakat ve radar deterministik. | Önerinin sonucu makine tarafından okunacak biçimde kaydedilmiyor (`DecisionLog.outcome_note` serbest metin). |
| Güven kapısı ve ayrı doğrulayıcı adımı; düşük güven sahibin kuyruğuna düşer. | Eval'lar sayı doğruluğunu ölçüyor ("FAVÖK 5.213.800 mü"); tavsiyenin iyi olup olmadığını ölçen yok. |
| `AgentRun` kaydı, SLO, `DecisionLog`, yetki matrisi. | Ajanların önerisi ile sahibin kararı arasındaki fark veri olarak tutulmuyor (muhasebe kuyruğu dışında). |
| Eval altyapısı, altın testler, düzeltmeden kural çıkaran döngü, muhasebede seviye başına isabet (`guven.py`). | Yönetim kararlarında aynı güven ölçümü yok. |

### Üç seviye

1. **Ölç ve hazırla.** Sayıyı hesapla, riski göster, seçenekleri çıkar. Bugün büyük ölçüde var.
2. **Öner, insan karar versin, sonucu ölç.** Her öneri bir beklentiyle kaydedilir ("bu tahsilat gelirse 3. haftadaki açık kapanır"), sonra gerçekle karşılaştırılır. Plan v10'un odağı budur.
3. **Eşik altında kendi karar versin.** Küçük, geri alınabilir işler (ör. ödeme taslağı). Ölçüt: bir karar türünde öneri isabeti en az N kez gerçekle karşılaştırılmış ve sahibin düzeltme oranı bir eşiğin altına inmiş olmalı. N ve eşik ilk pilot verisiyle konur, önceden uydurulmaz. Muhasebe kuyruğunda bu mekanizma var (`guven.py`); genelleştirilir.

### Parçalar ve sıra

| Parça | Ne zaman | Karar |
|---|---|---|
| Eval odaklı döngü | O3–O5 | **Yapılır.** Önerinin beklentisi, sonucu ve sahibin düzeltmesi kaydedilir; nakit tahmininin yanında öneri başarısı da notlanır. |
| Hook ve harness | O1–O2 | **Yapılır, küçük.** Ajan çıktısı öncesi ve sonrası doğrulayıcı, sayı-kaynak kontrolü ve yetki matrisi tek sözleşmede toplanır. Çoğu var (v9 A5); eksik olan bütünlük. |
| Arka plan ajanları | O1 sonrası | **Kısmen.** Bülten, vade hatırlatma, gece notlama zaten arka plan işi; staging olmadan denenemez. |
| Paralel ajanlar | Ufuk 3 | **Yapılmaz şimdi.** Pilotta bir koşu fiilen yavaşsa ele alınır. |
| RLHF | Yok | **Yanlış araç.** Model eğitmiyoruz. Onay, ret ve düzeltmeler veri olarak saklanır; eval setine ve kurallara dönüşür. İnce ayar, işaretli binlerce örnek olmadan zarar verir. |

**Değişmez kural (v9'dan):** Ajanlar ölçer, hazırlar, hatırlatır, önerir. Karar insanındır; seviye 3 ancak yukarıdaki ölçütle ve sahibin açık onayıyla açılır.

## 11. Ufuklar

**Ufuk 1 (hafta 0–8): pilot yolu.** §4'teki O0–O5. Aşağıdaki iki teknik iş bu ufka girer, çünkü pilotta bir hata çıktığında bulunabilir olmak zorundayız:

- **`worker.py`'yi bölmek.** 1.482 satırla projedeki en büyük dosya: iş yürütme, şirket görünümü ve yan etkiler iç içe. Şirket görünümü ve yan etkiler ayrı modüllere taşınır; davranış değişmez, mevcut testler aynen geçer.
- **Pilot dosyalarından test külliyatı.** Her gerçek pilot dosyası, ayrıştırıcı ve defter için kaynaktan bir testin girdisi olur. Bugüne kadarki hataların neredeyse hepsini canlı denemeler buldu.
- **Bilgi grafı hijyeni.** `.graphifyignore` ile `.claude/` ve `graphify-out/` graf dışı bırakılır; `connectors/github.py` ile `registry.py` arasındaki döngüsel bağımlılık çözülür.

**Ufuk 2 (Ufuk 1'in ölçütü tutarsa): yönetim ritmi.** v9 K2: toplantı ritmi, karar ve taahhüt defteri, boardroom hafızasının veritabanına taşınması. Bülten ve karar kaydı bunun tohumudur.

**Ufuk 3 (pilot kanıtı varsa): yetki ve hafıza.** v9 K3 ve K4: yetki devri, kurumsal hafıza, dış okuyucu için kanıt dosyası. Seviye 3 otonomi (§10) burada, karar türü başına ve ölçütle açılır. Rol ajanları (CTO, CMO, COO, CHRO) ancak bir pilot isterse menüye döner.

## 12. Uygulamadan sonra: iş yol haritası

Ufuk 1'in uygulaması bittiğinde, pilot verisiyle birlikte ayrı bir **iş yol haritası** yazılır. İçeriği o güne kadar uydurulmaz; yazılırken şu sorular pilot bulgularıyla cevaplanır:

- **Fiyat ve paketleme:** pilotun ödemeye razı olduğu bedel ve birim.
- **Kanal:** doğrudan satış mı, SMMM ve danışman üzerinden mi; pilot geri bildirimi hangisini gösteriyor.
- **Segment:** pilotun gösterdiği gerçek segment, §7'deki varsayımla karşılaştırılır.
- **Birim ekonomisi:** bir şirketin kurulum süresi, destek yükü ve LLM maliyeti (şu an ölçülmemiş).
- **Rakip konumu:** karar sonucunu ölçmenin (§10) pilotta fark yaratıp yaratmadığı.

Bu bölümün çıktısı yeni bir belge (`BUSINESS_ROADMAP.md`) olur; bu plan onu başlatan koşulu burada kaydeder.

## 13. Motor ve ajan katmanı planı

Bu bölüm, §1'deki pilot hedefinin **mühendislik tarafıdır**: pilotun dayanacağı CFO motorunu ve mevcut ajanları kanıtlı, çökmeyen ve yapay zekayı verimli kullanan hale getirir. Pilot şirket bulunamasa da ilerleyebilir; O1'deki sahip kararlarını beklemez.

### 13.1 Hedef

> **12 hafta sonunda CFO motorunun doğruluğu, dayanıklılığı ve yapay zeka katmanı, kaynağı gösterilebilen verilerle ölçülmüş olsun: ölçülmemiş hiçbir sayı ekranda "gerçek" gibi durmasın.**

Ölçülür hale gelecekler:

| # | Ölçüt | Nasıl ölçülür | Eşik |
|---|---|---|---|
| 1 | Hesaplanan oranlar kaynak tablolarla tutuyor mu | KAP bilançolarındaki yayımlanmış rakamlar ve oranlar (§13.3) | Fark 0 (kuruşa kadar) |
| 2 | Otomatik mutabakat ne kadar doğru | Zor durum üretecinde yanlış otomatik eşleşme sayısı | **0 yanlış otomatik eşleşme**; kaçırılan eşleşme oranı ölçülür |
| 3 | Aynı veri, aynı sonuç | Metamorfik testler: iki kez yükleme, sıra değiştirme, dosyayı ikiye bölme | Rakamlar değişmez |
| 4 | Yapay zeka metni sayıyı uyduruyor mu | LLM'li altın küme: anlatıdaki her sayı kaynakla karşılaştırılır | **Uydurma sayı 0**; kapıya düşen oran, maliyet ve gecikme ölçülür |
| 5 | Kıyas sayıları kaynaklı mı | Kaynağı gösterilemeyen kıyas değeri sayısı | 0 |
| 6 | Bozulduğunda ne oluyor | Kaos testleri: worker ölümü, Redis yok, yavaş veritabanı | Sessiz yanlış sonuç 0; her koşu ya tamamlanır ya kapıya düşer ya da hata kaydı bırakır |

### 13.2 İlkeler: veriyi tasarla, projeyi değil

*Designing Data-Intensive Applications*'dan, bu depoda zaten `DDIA_COMPLIANCE.md` ve plan v5 §V5'te geçen ilkelerin bu plana uyarlanışı. Kural: **bir özellik, hangi veriyi türettiğini, kaynağını ve yeniden üretilebilirliğini yazmadan başlamaz.**

1. **Tek doğruluk kaynağı.** Para defterdedir (`canonical_transactions`, `open_items`). Şirket görünümü, radar, özet ve bülten **türetilmiş veridir**; hiçbiri kendi kaynağını saklamaz.
2. **Türetilmiş veri silinip yeniden üretilebilir.** Her görünüm defterden saf bir fonksiyonla hesaplanır. Test: görünümü sil, yeniden hesapla, rakamlar aynı çıkmalı.
3. **Her etki bir kez.** Aynı girdi iki kez gelirse ikinci kez sayılmaz (kimlik anahtarı, idempotent yazma). Bu defter için yapıldı; öneri, bülten ve hatırlatma gibi **dış etkiler** için de aranır.
4. **Şema evrimi geriye uyumlu.** Migration'lar yalnız ekler; eski istemci yeni alandan etkilenmez.
5. **Uçtan uca doğrulama.** Hesaplayan ajan kendi sonucunu doğrulamaz; ayrı adımdaki doğrulayıcı ve güven kapısı kalır.
6. **Hata sessiz geçmez.** Her koşu `AgentRun` bırakır; zaman aşımı, yeniden deneme ve ölü iş toplayıcısı var olanlarla devam eder.
7. **Ölçmeden güvenme.** Ölçülmemiş bir özellik "hazır" sayılmaz; kapıdan geçmesi için güveni ölçülür.

### 13.3 Gerçek veri: ne bulunabilir, ne bulunamaz

İnternette **gerçek bir KOBİ'nin işlem düzeyindeki defteri ve ekstresi yoktur**; kişisel ve ticari sır olduğu için yayımlanmaz. Bulunabilenler ve ne işe yaradıkları:

| Kaynak | Gerçek mi | Ne için kullanılır | Ne için kullanılamaz |
|---|---|---|---|
| **GİB e-Fatura ve e-Defter paketleri** | Evet (otorite) | Zaten kullanılıyor (`scripts/fetch_gib_corpus.py`) | Dağınık gerçek davranışı vermez |
| **KAP finansal raporları** (borsa şirketleri, XBRL) | Evet, denetlenmiş | Oran ve tablo formüllerimizi yayımlanmış rakamlara karşı sınamak (§13.1 #1) | İşlem düzeyi veri yoktur; şirketler KOBİ değildir |
| **TCMB Sektör Bilançoları** | Evet, toplu | Sektöre göre kıyas aralıkları (§13.1 #5) | Tek şirket davranışı vermez; KOBİ'ye özel değildir |
| Üçüncü taraf sentetik defter veri setleri (ör. LedgerLab, Mindweave) | Hayır, sentetik | Yapısal çeşitlilik, bizim yazmadığımız örnek | "Gerçek" sayılmaz; lisansları kontrol edilmeli |
| Bizim zor durum üretecimiz | Hayır, sentetik | Bilinen zorlukları sistematik üretmek (§13.4) | Bilmediğimiz zorlukları bulamaz |

**Sonuç:** Motorun doğruluğunu ve dayanıklılığını bu kaynaklarla sınayabiliriz. Dağınık gerçek KOBİ davranışının (gecikmiş ödemeler, aynı açıklamalı farklı ödemeler, kısmi ödemeler) bizim zorlukları doğru tahmin edip etmediğini yalnızca gerçek bir şirketin verisi gösterir. Bu eksiklik §8'e risk olarak yazıldı; veri bulunana kadar zor durum üreteci vekildir ve bunu açıkça bilmeliyiz.

**İndirmeler izne bağlıdır.** Hiçbir kaynak, dosya adı, adres ve boyutu sahibine gösterilip onay alınmadan indirilmez.

**Bulunan bir sorun (E2'nin ilk işi):** `backend/app/services/benchmark.py` sektör ortancalarını koda gömülü bir sözlükte tutuyor ve çıktıya "TCMB/BDDK Sektör İstatistikleri 2023-2024" kaynağını yazıyor; bu kaynağın bu sayıları gerçekten verdiği doğrulanmadı. Yüzdelik aralıkları (p25/p75) da bazı yerlerde ortancanın 0,6 ve 1,4 katı olarak tahmin ediliyor. `benchmark_intelligence.py` benzer biçimde "Türkiye SaaS raporu 2024" ve "KOSGEB" gibi kaynaklara atıfla gömülü yüzdelikler taşıyor. Bunlar plan v8'in dürüstlük ilkesine aykırı olabilir: kaynağı gösterilemeyen kıyas değeri kaldırılır ya da TCMB tablosundan alınıp tarihi ve kaynağıyla yazılır.

### 13.4 Aşamalar

Tek geliştirici için kaba süreler; her aşama bir önceki bitmeden başlamaz, ama E1 ile E2'nin ilk yarısı paralel gidebilir.

#### E1 — Veri sözleşmesi ve yeniden üretilebilirlik · Hafta 1–3
- Türetilmiş her görünüm (şirket görünümü, radar, özet) için yazılı bir veri sözleşmesi: girdisi, kaynağı, hangi fonksiyonla hesaplandığı.
- Test: görünümü silip yeniden hesaplamak aynı rakamları verir; yükleme sırasını değiştirmek rakamları değiştirmez.
- `company_view` imzası bugün satır kimliklerine bağlı; yeniden kurulan bir defterin imzası farklı çıkar. Rakama bağlı bir imza ya da bunun bilinçli bir kabul olarak yazılması.
- `worker.py` bölünür: iş yürütme, şirket görünümü ve yan etkiler ayrı modüller; davranış değişmez, mevcut testler aynen geçer.

**Bitti sayılır:** Yeniden üretilebilirlik testleri CI'da yeşil; `worker.py` bölünmüş.

#### E2 — Doğruluk külliyatı ve zor durum üreteci · Hafta 2–5
- **KAP bilançoları:** 3–5 şirketin yayımlanmış tabloları (farklı sektör). Beklenen değerler tablodaki rakamlardır; hesapladığımız oran ve marjlar bunlarla kuruşuna kadar tutmalı (§13.1 #1). İndirme izne bağlıdır (§13.3).
- **TCMB sektör verisi:** Kıyas aralıkları gömülü sözlükten çıkarılıp tarihi ve kaynağı olan bir tabloya taşınır (§13.1 #5). Kaynağı gösterilemeyen kıyas değeri kaldırılır.
- **Zor durum üreteci:** bilinen zorlukları parametreyle üretir: aynı açıklamalı farklı ödemeler, kısmi ödeme, bir ödemeyle birçok fatura, döviz, ters işaretli satırlar, BOM, ayırıcı ve tarih biçimi çeşitleri, Türkçe karakter (İ/ı), kesik satır.
- **Metamorfik testler:** iki kez yükleme, sıra değiştirme, dosyayı ikiye bölme, ilgisiz dosya ekleme: sonuç değişmez (§13.1 #3). Özellik tabanlı bir test kütüphanesi gerekirse CLAUDE.md'nin ikinci kuralı gereği önce `requirements.txt`'e yazılır.
- Mutabakatta **yanlış otomatik eşleşme 0** olmalı; kaçırılan eşleşme oranı ölçülüp yazılır (§13.1 #2).

**Bitti sayılır:** §13.1'in 1, 2, 3 ve 5 numaralı ölçütleri ölçülmüş ve testte.

#### E3 — Yapay zeka katmanının ölçümü · Hafta 4–8
- **LLM'li altın küme:** E2'nin verisinden yaklaşık 20 senaryo; gerçek bir model anahtarıyla uçtan uca koşar. Ölçüler: anlatıdaki sayıların kaynağa uyumu, uydurma sayı (hedef 0), kapıya düşen oran, maliyet ve gecikme.
- LLM'siz sürüm her CI'da koşar; LLM'li sürüm elle ya da gecelik koşar (maliyet).
- `eval_harness.py` genişler; model değişikliği (model kataloğu) aynı altın kümede iki modelin karşılaştırılmasıyla güvenli hale gelir.
- Öneri için **beklenti ve sonuç kaydı** şeması (§10) bu aşamada tasarlanır; O3–O5 onu kullanır.

**Bitti sayılır:** §13.1'in 4 numaralı ölçütü ölçülmüş; LLM maliyeti ilk kez sayı olarak biliniyor.

#### E4 — Roller defterden beslenir · Hafta 7–10
Diğer ajanlar ayrı ürün gibi değil, **defterin bakış açıları** olarak geliştirilir. Bir rolün yeni özelliği ancak şu üçünü sağlıyorsa yapılır: (1) defterden okur, ayrı veri hattı yoktur; (2) aynı güven kapısından geçer; (3) ölçülebilir bir sonucu vardır.

| Rol | İlk bulgu (defterden) |
|---|---|
| CHRO | Maaş giderinin gelire oranı ve trendi, SGK ödemelerinin düzenliliği |
| COO | Tedarikçi yoğunlaşması, vadesi geçmiş borç |
| CMO | Pazarlama giderinin gelirle ilişkisi |
| CTO | Bulut ve yazılım giderlerinin trendi |

Her bulgu pazartesi bültenine (O4) girer ve beklenti ve sonuç kaydı taşır.

**Bitti sayılır:** Dört bulgu türü defterden üretiliyor; hiçbiri ayrı dosya istemiyor.

#### E5 — Dayanıklılık · Hafta 9–12
- **Olay günlüğü:** Defter değişince görünümlerin yenilenmesi bugün eşzamanlı çağrıyla yapılıyor; sıralı ve yeniden oynatılabilir bir olay akışına taşınır (plan v5 F2). Çift gönderim ve kayıp olay testleri.
- **Kaos testleri** (staging, O1 sonrası): worker öldürme, Redis yok, yavaş veritabanı, bozuk girdi. Beklenti: sessiz yanlış sonuç yok; her koşu tamamlanır, kapıya düşer ya da hata bırakır (§13.1 #6).
- **SLO'lar** gerçek ortamda ölçülür; ilk sayılar bu plana işlenir.
- **Dönem kapanışı** (plan v5 F5): ay kilidi ve mühür, E5'in sonunda değerlendirilir.

**Bitti sayılır:** §13.1'in 6 numaralı ölçütü staging'de ölçülmüş.

### 13.5 Pilot yoluyla ilişkisi

| Pilot yolu (§4) | Motor planı (§13.4) |
|---|---|
| O0, O2 | Bitti |
| O1 (staging) | E5'in kaos testlerinin önkoşulu |
| O3 (radar tamamlama, tahmin kaydı) | E2 ve E3'ün ölçümlerinden yararlanır; öneri kaydı E3'te tasarlanır |
| O4 (bülten) | E4'ün bulguları bültene girer |
| O5 (ölçmek) | E3 ve E5'in ölçüm altyapısı |

Sahip kararları (pilot şirketler, barındırma) olmadan ilerleyebilecek olanlar: **E1, E2, E3 ve E4**. Bu yüzden sıradaki iş E1'dir.

## 14. Açıklık defteri

Bu oturumda ve önceki turlarda kayda geçen açıklıkların tek listesi. Her satırın **kanıtı** vardır: "doğrulandı" demek bu turda koddan yeniden okunduğu, "hafıza notu" demek önceki bir turdan taşındığı ve yeniden doğrulanmadığı anlamına gelir. Risk, **pilot şirketin parasına ve güvenine** etkisine göre yazıldı.

**Kural:** Her PR hangi açıklığı kapattığını (G numarasıyla) yazar; kapanan satırın durumu aynı PR'da güncellenir. Bir açıklık, önce onu yeniden üreten **kırmızı bir test** yazılmadan kapatılmış sayılmaz.

### 14.1 Para ve güven (pilot için en yüksek risk)

| # | Açıklık | Kanıt | Risk | Kapatma | Durum |
|---|---|---|---|---|---|
| G1 | Bazı yazımlar **güven kapısını atlıyor**: Risk, Denetim, Uyum ve CEO sonuçları şirket bağlamına doğrudan yazılıyor; CTO senkronu da. CLAUDE.md'ye göre kapı yük taşıyıcıdır. | Doğrulandı: `agents/orchestration/auto_chain.py:400,471,496,576`, `api/ceo.py:603`, `services/scheduled_sync.py:646` `update_agent_result` çağırıyor; yalnız `post_completion.py` ve `context_persist.py` kapıdan geçiyor. | **Yüksek.** Sahip onayı olmadan bağlama giren bir sonuç Command Center'a ve (O4) bültene beslenir. | Tek yazım noktası: tüm çağrılar `persist_agent_completion` üzerinden. Mimari testi `update_agent_result` çağıran her yeri tarar; yeni bir çağrı eklenemez. | **Kapandı** (`write_derived_result`; `test_derived_results_gate.py`). Kalan doğrudan yazarlar listelenmiş ve gerekçeli: CTO senkronu bir bağlayıcı katmanı (API'den okunan commit sayısı, model yok). |
| G2 | **Bağlayıcı senkronu kendi kimliğiyle yazıyor**; aynı fatura hem dosyadan hem Paraşüt/ERP senkronundan gelirse iki kez sayılabilir. | Doğrulandı: `services/data_sync/accounting/importers.py` kendi `source_type`'ıyla yazıyor; defterin kimliği belge UUID'si ya da içerik parmak izi. Çift sayımın gerçekten olduğu **henüz yeniden üretilmedi**. | **Yüksek.** Paraşüt tek tıkla bağlantısı pilot yolunda. | Önce çift sayımı yeniden üreten test; sonra senkron kimliğini ortak kimlik sözleşmesine (§13, `data-contracts.md`) bağlamak. | Açık |
| G3 | **El ile kategori düzeltmesi deftere ulaşmıyor.** | Doğrulandı: `api/corrections.py` yalnız `Transaction`'ı değiştiriyor; defter satırı bir sonraki yeniden okumada güncelleniyor. | Orta. Düzeltme yapılan şirketin kâr rakamı eski kategoriyle kalır. | Düzeltme, aynı kimlikli defter satırını da günceller ve görünümü yeniler. | Açık |
| G4 | Anlamsal özet **5.000 satırda sıralamasız kesiliyor**. | Doğrulandı: `services/semantic/rebuild.py:81` `limit(5000)`, `order_by` yok. | Orta. Büyük defterde rastgele satırlar düşer; "canlı giriş" yanlış çıkar ve sahte çelişki uyarısı doğurabilir. | Satır çekmek yerine veritabanında toplama; 6.000 satırlık test. | **Kapandı** (`_load_canonical` toplamı veritabanında alır; `test_semantic_canonical_totals.py`). |
| G5 | **Mükerrer ve eşleşme kararları türetilmiş tabloların içinde.** | Doğrulandı: `docs/data-contracts.md` ("Bilinen boşluk"). | Orta. Defter silinip kurulursa kararlar kaybolur. | Eklemeli, silinmez karar günlüğü (E5); o zamana kadar defter tabloları elle silinmez. | Açık |
| G6 | **Bir ödeme birden çok faturayı kapatamıyor.** | Doğrulandı: `services/reconciliation.py` başlığı "birkaç fatura uyuyorsa", "faturanın bir kısmı" durumlarını öneri yapıyor; toplu havale yok. | Orta. KOBİ'lerde toplu havale yaygın; satır "kendi parası" gibi sayılabilir. | Toplamı birkaç açık kalemin toplamına tam eşit olan hareket için öneri; her kalem tanımlı olmalı. Yanlış otomatik eşleşme 0 kalır (§13.1 #2). | **Kapandı** (`_decide_lump`: yalnız öneri, aynı karşı taraf + ad açıklamada + tek çözüm; `test_batch_payment_reconciliation.py`). |
| G7 | **Vergi tahminleri sabit oranlı.** | Doğrulandı: `services/regional/tax.py` KDV %20, stopaj "tahmini" %20. | **Yüksek**, O3'te vergi takvimi radara girecek. Yanlış tutar yanlış açık demek. | Tahmin etiketi; oranlar GİB kaynağından sürümlü veri; tutarlar defterdeki hesap kodlarından (191/391, 360). Kaynağı gösterilemeyen oran eklenmez. | Açık |
| G8 | **Şirket görünümü bütün dönemleri topluyor**, ekranda dönem görünmüyor. | Önceki turda canlı görüldü (13 ay toplam); `post_completion.py` `company_rows` hepsini okuyor. | Orta, pilot yıllar boyu veri yükleyecek. | Görünüm bir dönem seçer (varsayılan son 12 ay) ve ekranda dönem etiketi gösterir. | Açık |
| G9 | **Sohbetin kanıtı son yüklemenin satırlarıyla sınırlı.** | Doğrulandı: `services/chat_grounding.py` etkin CFO `job_id`'sine bağlı. | Orta. Sohbet, defterde olan bir paradan habersiz kalabilir. | Defter tabanlı kanıt. | Açık |

### 14.2 Yapay zeka ve ölçüm

| # | Açıklık | Kanıt | Risk | Kapatma | Durum |
|---|---|---|---|---|---|
| G10 | **LLM'li uçtan uca hiç ölçülmedi.** Canlı denemelerin hepsi model anahtarsız koştu. | Oturum kaydı: günlüklerde "openai_api_key is a placeholder". | **Yüksek.** "AI CFO"nun anlatı yarısının kalitesi bilinmiyor. | E3: altın küme, uydurma sayı 0 (§13.1 #4). | Açık |
| G11 | **Defter değişimi başına ikinci analiz koşusu**; LLM maliyeti ölçülmemiş. | Doğrulandı: `post_completion.refresh_company_view` her imza değişiminde `run_cfo_pipeline` koşturuyor. | Orta. | E3'te maliyet ölçümü; gerekirse sayılar hemen, anlatı gecikmeli. | Açık |
| G12 | **Karar kalitesini ölçen bir şey yok**; öneri beklentisi ve sonucu serbest metin. | §10. | Orta, değer önermesinin kanıtı. | E3: beklenti ve sonuç alanları. | Açık |
| G13 | **Rol ajanları (CHRO, Risk, Denetim, Uyum) güvenini ölçmüyor**, hep sahip kuyruğunda bekler. | Hafıza notu, yeniden doğrulanmadı. | Düşük (bu yolda kullanılmıyor). | E4: defterden bulgu ve güven ölçümü. | Açık |
| G14 | Sektör kıyası hâlâ doğrulanmamış değerlerle ve hepsi SaaS değeri. | #26 ve #28 etiketledi; kaynaklı tablo yok. | Düşük (etiketli, modele girmiyor). | Gerçek TCMB tablosu (indirme onayı bekliyor). | Kısmen kapandı |

### 14.3 Radar ve ekran

| # | Açıklık | Kanıt | Risk | Kapatma | Durum |
|---|---|---|---|---|---|
| G15 | Radar **kira/maaş, vergi/SGK, çek/senet** içermiyor. | Doğrulandı: `cash_radar.NOT_INCLUDED` ve ekranda "Radara dahil değil". | **Yüksek.** Radar iyimser kalabilir; bu yüzden ekranda açıkça yazıyor. | O3. | Açık |
| G16 | Radar metinleri sunucudan **Türkçe sabit**, menüde **İngilizce etiketler** var. | Doğrulandı: `layout.tsx` ("Cash Flow", "Upload"), radar eylem başlıkları. | Orta, pilotun ilk izlenimi. | Etiketler ve eylem metinleri i18n'e. | Açık |

### 14.4 Dış bağlantılar ve operasyon

| # | Açıklık | Kanıt | Risk | Kapatma | Durum |
|---|---|---|---|---|---|
| G17 | **Dış bağlayıcıların sözleşmesi doğrulanmamış**: Paraşüt API; GİB senkronunda uydurma API kararı. | Hafıza notu (`hardening-plan`, `easy-integration-plan`), yeniden doğrulanmadı. | Yüksek, yalnızca bu bağlayıcı kullanılırsa. | Resmî belgeye karşı sözleşme testi; doğrulanana kadar ekranda "doğrulanmadı" ve varsayılan kapalı. | Açık |
| G18 | **Staging yok; worker gerçek ortamda hiç koşmadı; geri yükleme tatbikatı yapılmadı; Helm şablonu üretilmedi.** | #23 açıklaması, `docs/ops/managed-postgres.md` §5. | **Yüksek**, pilot öncesi. | O1: sağlayıcı seçimi (sahip kararı) ve ilk tatbikat. | Sahip kararı bekliyor |
| G19 | **KVKK ve hukuki gözden geçirme yok.** | §7 karar 4. | **Yüksek**, pilot öncesi. | Sahip kararı. | Sahip kararı bekliyor |
| G20 | **Gerçek KOBİ verisi yok**; zor durum üreteci vekil. | §13.3. | Yüksek (belirsizlik). | Üreteç + ilk gerçek veride her bulgu teste. Sahip veriyi sağlayana kadar açık kalır. | Sahip kararı bekliyor |
| G21 | Kök dizinde 15'ten fazla eski plan belgesi. | Doğrulandı. | Düşük. | `docs/arsiv/` altına taşımak, ayrı PR. | Açık |

### 14.5 Kapatma sırası

Her dalgadaki işler birbirinden bağımsız PR'lardır; her biri kırmızı testle başlar, canlı denenir, `verify` yeşil olunca birleşir.

**Dalga 1: para ve güven (hafta 1–2).** Sahip kararı gerektirmez.
1. **G1** güven kapısını atlayan yazımlar: en yüksek risk, en küçük iş; mimari testi bir daha açık bırakmaz.
2. **G4** özetin sıralamasız kesilmesi.
3. **G3** kategori düzeltmesinin deftere ulaşması.
4. **G2** önce çift sayımı yeniden üret, sonra kimliği birleştir.
5. **G8** dönem seçimi ve etiketi.

**Dalga 2: doğruluk ve ölçüm (hafta 3–6).**
6. **G6** toplu havale eşleştirmesi (yanlış otomatik eşleşme 0 sınırıyla).
7. **G7** vergi tahminlerinin kaynaklı hale gelmesi ve **G15** radarın tamamlanması (O3).
8. **G10, G11, G12** LLM'li altın küme, maliyet ölçümü ve beklenti/sonuç alanları (E3).
9. **G9** sohbetin defterden kanıt alması.

**Dalga 3: dayanıklılık ve cila (hafta 7–12).**
10. **G5** karar günlüğü ve olay günlüğü (E5).
11. **G13** rol bulguları defterden (E4).
12. **G16** i18n, **G14** gerçek sektör tablosu (onayla), **G21** belge arşivi.

**Sahip kararı bekleyenler (G18, G19, G20)** ve **G17** bu sıranın dışındadır; engel kod değil karardır. Her biri çözülmeden pilot başlamaz; bu yüzden sahibin önüne açıkça konur.

### 14.6 Ölçüt

Dalga 1 bittiğinde: G1–G4 ve G8 satırları "Kapandı" ve her birinin testi CI'da. Dalga 2 bittiğinde: §13.1'in 2, 4 ve 6 numaralı ölçütleri ölçülmüş. Açık kalan her satırın nedeni (kod, karar ya da veri) yazılı.

## 15. Sıradaki adım

1. **Dalga 1'in G1'i** (§14.5): güven kapısını atlayan yazımlar, kırmızı mimari testiyle.
2. G4, G3, G2, G8 sırayla.
3. KAP ve TCMB dosyaları için indirme izni (§13.3); dosya adı, adres ve boyut gösterilerek.
4. Sahip kararları (G18, G19, G20): barındırma sağlayıcısı, hukuki gözden geçirme, gerçek veri.
5. Ufuk 1 bittiğinde iş yol haritası (§12).
