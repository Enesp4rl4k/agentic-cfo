# Plan v9 — Yönetim İşletim Sistemi

*2026-11-06 notu: odak ve sıra için [PLAN_V10.md](PLAN_V10.md) geçerlidir; bu belgenin tezi ve K2–K4 içeriği orada beklemeye alındı.*

*2026-11-02. Plan v8'in kalanını içine alır; açık işler için tek plan budur. Süreler tek geliştirici için kaba tahmindir, ilk pilot bulgularıyla yeniden yazılır.*

## 1. Tez

Küçük şirket rapor okuyarak kurumsallaşmaz. Kurumsallaşma, kimin neye karar verdiğinin, neden verdiğinin ve sonra ne olduğunun patronun kafasından çıkıp şirkete geçmesidir.

Bugünkü ajan katmanı çoğunlukla **analist** gibi çalışıyor: veri alır, rapor yazar. Hedef katman **yönetim işletim sistemi**: ritmi tutar, kararı hazırlar, sorumluyu ve tarihi kaydeder, sonucu ölçer, yetkiyi kanıtla devrettirir.

**Değişmez kural: ajanlar ölçer, hazırlar, hatırlatır, önerir. Karar insanındır.**

### Kurumsallaştı demek için beş test

Ürünün başarısı özellik sayısıyla değil, gerçek bir şirkette bunlarla ölçülür:

| # | Test | Kanıt |
|---|---|---|
| 1 | Kararlar kayıtlı | Karar defterinde gerekçe ve seçeneklerle duruyor |
| 2 | Kararların sahibi var | Sorumlu ve tarih atanmış, zamanında kapanıyor |
| 3 | Yetki devredildi | Patronun onayladığı kayıt sayısı düşerken hata oranı artmıyor |
| 4 | Patronsuz çalışıyor | Yedek onaylayıcı var; iki haftalık yoklukta kuyruk birikmiyor |
| 5 | Dışarıya gösterilebiliyor | Banka ya da denetçi, kanıt dosyasını kaynağına kadar izleyebiliyor |

### Varsayımlar (sahip kararı bekliyor, §8)

- **Hedef:** 20–250 çalışanlı, ikinci kuşağa geçen aile şirketleri.
- **Alıcı ve ana kullanıcı:** Patron. **Kanal:** SMMM veya danışman.

## 2. Bugünkü durum

### Açık PR zinciri

| PR | İçerik | Durum (2026-11-02'de son görülen) |
|---|---|---|
| #8 | P0: kırık akışlar | Açık, CI yeşil |
| #9 | A1/A2: hesap kodu, vergi ajanı | Açık, CI yeşil; #8'in üstünde |
| #11 | A3/A4: anomali, muhasebe kuyruğu | Açık, CI yeşil; #9'un üstünde |
| #10 | Test veritabanı izolasyonu | Açık, CI yeşil; master'a karşı |

### Yeniden kullanılacak yapılar

| Yapı | Dosya | Bugün ne yapıyor | Eksiği |
|---|---|---|---|
| Karar kaydı | `models/decision_log.py`, `api/decisions.py` | Seçenek, gerekçe, beklenen ve gerçekleşen sonuç | Sorumlu kişi ve son tarih yok |
| Karar paketi | `services/decision_packet.py` | Durum, seçenekler, emsal | Toplantıya bağlı değil |
| Ajan müzakeresi | `services/negotiation/boardroom.py` | Ajanlar konuyu tartışıp uzlaşır | Sonuç "karar" adını taşıyor; insan karar değil, girdi olmalı |
| Müzakere hafızası | `services/negotiation/boardroom_memory.py` | Müzakere ve aksiyonları saklar | **Veritabanı yerine `data/boardroom_memory` dosyasında**; birden çok sunucuda ve DDIA ilkesine göre tutmaz |
| Aksiyon maddeleri | `ActionItemRecord`, `api/actions.py`, `ActionCenter.tsx` | Onayla/reddet/çalıştır | Sorumlu bir **ajan**, insan değil; son tarih yok |
| Aksiyon çalıştırıcı | `services/execution/action_runner.py` | Bütçe, ödeme taslağı, denetim görevi | Otonomi güven ölçülmeden büyümemeli |
| Yetki Matrisi | `platform/authority_matrix.py`, `models/authority_policy.py` | Sürümlü politika, onay kuralları | Eşikleri kanıta göre önermiyor |
| Güven ölçümü | `services/accounting/guven.py` | Seviye başına ölçülen isabet, kurum geçmişi | Yalnız muhasebe; karar türlerine genelleşmeli |
| Kurumsallaşma Endeksi | `services/institutionalization.py` | Altı boyut, trend | §3'teki zayıflıklar |
| İlişkili taraf | `models/related_party.py`, `api/related_party.py` | Kayıt, öneri, kontrol | Ortak hesapları ve kişisel harcama sinyali yok |
| Kanıt | `models/defensibility_packet.py` | Mühürlü kayıt paketi | Dış okuyucu için paket değil |
| Bildirim ve zamanlama | `services/notification_service.py`, `scheduler.py` | Slack, e-posta, WhatsApp, uygulama içi | Toplantı ve taahhüt ritmine bağlı değil |
| SMMM portalı | `models/smmm_portal.py` | SMMM erişimi ve onay | Dağıtım kanalı olarak kullanılmıyor |

### Bulunamayanlar

Kod taramasında isimle bulunamadı (başka adla yazılmış olabilir, başlarken yeniden kontrol edilir): toplantı ve karar defteri modeli, organizasyon yapısı ve görev tanımı, politika-prosedür, halefiyet. İç kontrol yalnız `api/compliance_extended.py` içinde geçiyor.

### Doğrulanmamış olan

**Gerçek şirket kullanımına dair kanıt görmedim.** Doğrulamalar demo verisi ve test dosyalarıyla yapıldı. `models/pilot.py` davet ve geri bildirim tutuyor, ama pilotun nasıl yürütüldüğünü bilmiyorum. Bu planın en büyük riski bu; bu yüzden pilot K1'de başlıyor.

## 3. Ajan katmanında yapısal değişiklikler

Bunlar özellik değil, her aşamada uygulanan kurallar.

**3.1 Üç ajan sınıfı.** Her ajan birine ait olur ve sınıfı çıktıda görünür:

| Sınıf | Görev | LLM | Örnek |
|---|---|---|---|
| Ölçüm | Sayı üretir | Hayır | P&L, nakit radarı, kilit kişi |
| Görüş | Yorumlar, seçenek önerir | Evet, sayı üretemez | Müzakere, risk yorumu |
| Yazıcı | Hazır sayıyı metne döker | Evet, yoksa şablon | Toplantı özeti, bülten |

**3.2 Tek çıktı biçimi: Karar Kartı.** Rol raporlarının üstüne ortak bir sözleşme: durum, seçenekler, her seçeneğin hesaplanmış sonucu, kanıt (kaynak satırlara bağlı), kimin karar vereceği, güven, son tarih. Tek `StepResult` sözleşmesinin (A5) üstüne kurulur.

**3.3 Olaya bağlı çalışma.** Ajanlar yalnız dosya yüklenince değil, vade yaklaşınca, karar gecikince, toplantı yaklaşınca da devreye girer. Önce mevcut `scheduler.py` ile başlanır; işlem günlüğü (F2) gerçekten gerekince gelir.

**3.4 Ölçülen özerklik.** `guven.py` modeli muhasebeden karar türlerine genişler. Bir ajan veya rol, ölçülmüş isabet olmadan daha fazla yetki kazanamaz. Toplu onaylar ölçüme sayılmaz (bugünkü kural korunur).

**3.5 Bağımsız doğrulama.** Her rolde hesaplayan ve doğrulayan ayrı adımdır (S3). Uzlaştırma kuralları o rolün kaynak verisine bağlanır.

**3.6 Endeks kullanım değil kanıt ölçer.** Bugünkü skor ağırlıkla uygulama sinyallerini okuyor ve `key_person_risk` yalnız SMMM onaylayıcılarına bakıyor. Yani şirket uygulamayı çok kullanarak yüksek puan alabilir. Bu K4'te düzeltilir; o zamana kadar skor pazarlamada kullanılmaz.

## 4. Aşamalar

### K0 — Temel · ~2 hafta

| İş | Çıkış ölçütü |
|---|---|
| PR'ları indir: #8 → #9 → #11, #10 | Açık PR yok; CI yeşil; demo `demo_prefill --force` ile yenilendi |
| **Uydurma müzakereyi kaldır:** LLM anahtarı yoksa `boardroom.py` `_mock_boardroom_debate`, konudan bağımsız hazır bir uzlaşı ("pazarlama bütçesi %15 artırılacak", güven 0,85) üretip aksiyon maddeleriyle şirket hafızasına kaydediyor | LLM yoksa sebepli 503 (`llm_unavailable`), kayıt yok; varsa eski sahte kayıtlar işaretlenir. Test: anahtarsız çağrı hiçbir karar ve aksiyon yazmıyor |
| A5: tek sözleşme ve onay kapısı, her koşu `AgentRun`, `AgentJob` lease/reaper | Parametrik test: her rol sözleşmeyi döndürür, düşük güvende bekler, koşusu kayıtlı |
| A6: `SAMPLE_CPI_INDEX` varsayılanı kalkar; LLM yokken sohbet temel sayıları cevaplar | Endeks yoksa `no_data`; örnek sayı ratchet testi |
| Vergi ajanı dürüstlüğü: tahmin dönemi doğru, takvim ileri tarihli, tahmin ile ödenen yan yana | Demo: dönem etiketi rakamlarla tutuyor; geçmiş tarih "yaklaşan" görünmüyor |

### K1 — Güven ve haftalık değer · ~5 hafta (pilot burada başlar)

Patronun her hafta geri dönme nedeni bu aşamadır. Yönetim ritmi ancak buna güvenilirse tutunur.

| İş | Not |
|---|---|
| F1 tek şirket defteri | Kimlik belge id'si veya parmak izi; aynı dosya iki kez 0 satır |
| `open_items` (alacak/borç kalemi) | Karşı taraf, tutar, vade, durum, kaynak belge. Çek ve senet ayrı `instrument` türü olarak modele sığar; ayrıştırıcıları sonraya |
| UBL-TR vade alanları | `PaymentDueDate` bugün okunmuyor |
| Banka mutabakatı | Deterministik eşleştirici, belirsizi insana; gerçek DSO ve müşteri gecikmesi buradan çıkar. **Defterin çift sayım riskini de bu kapatır:** fatura tahakkuk, banka satırı nakittir; 3 günden uzak aralıkla gelirlerse ikisi de gelir sayılır. Eşleşen tahsilat açık kalemi kapatır ve gelir olarak sayılmaz |
| **Nakit Radarı** | 13 hafta; açık haftası, nedeni, üç eylem. Uzlaştırma ayrı doğrulayıcı adımda |
| Yükümlülük takvimi | KDV, muhtasar/SGK, geçici vergi; tutar defterden, takvim kuralları sürümlü veri. Son tarihler resmi kaynakla doğrulanır: `tax_agent.py` SGK için "aynı ayın 28'i" diyor, ertesi ay sonu olması gerekebilir |
| Tahmin kaydı (F4'ün çekirdeği) | Her radar tahmini değişmez; gerçekleşenle notlanır |

**Çıkış:** Demo ve en az bir pilot verisinde radar çalışıyor; dört hafta önceki tahminin sapması ölçülüp gösteriliyor (hedef değil, ilk ölçüm).

### K2 — Yönetim ritmi · ~4 hafta

Hedef, beş testin ilk ikisi.

| İş | Not |
|---|---|
| `decision_log` genişletme | `owner_user_id`, `due_date`, `meeting_id`, `kapanis` (nullable, ekleme migration'ı) |
| `management_meetings` | Dönem, gündem, katılımcı, tutanak, durum |
| **Kurul sekreteri ajanı** | Gündemi kurala göre veriden kurar: nakit açığı, yaklaşan yükümlülük, geciken karar, açık risk. Karar Kartı paketi hazırlar; metni LLM yazar, yoksa şablon |
| **Taahhüt takipçisi** | Sorumluya hatırlatır, gecikeni gündeme taşır, kararın vadesinde gerçekleşeni hesaplar |
| Karar defteri | Ekleme esaslı, düzeltme yeni kayıt; toplantı kapanışında SHA-256 mühür (F5 mührüyle aynı mekanizma) |
| Müzakere hafızası veritabanına | `boardroom_memory` dosyadan tabloya; eski kayıtlar taşınır |
| Müzakere "görüş" olur | `final_decision` ekranda "ajanların görüşü" olarak görünür; karar yalnız insan kaydıyla oluşur |
| Aksiyonların insana bağlanması | `responsible_agent` korunur, `responsible_user_id` ve son tarih eklenir |
| **Pazartesi bülteni** | Nakit değişimi, yaklaşan yükümlülük, geciken karar, tahmin isabeti |
| Tek kapı: `/yonetim` | Toplantı, karar, taahhüt tek ekranda; arka uç kapısız kalmaz |

**Çıkış:** Pilotta art arda iki aylık toplantı sistemle yapıldı; kararların sorumlu ve tarih oranı ile zamanında kapanma oranı ölçülüyor.

### K3 — Yetki devri · ~4 hafta

Hedef, test 3 ve 4. Kilit özellik burada.

| İş | Not |
|---|---|
| Organizasyon yapısı | `org_units`, `positions`; kim hangi birimden ve hangi kategoriden sorumlu. Sade tutulur, tam İK sistemi değil |
| Roller | Bölüm yöneticisi ve kurul üyesi rolleri. **DISPATCH: yetki mantığı değişikliği insan onayı ister** |
| **Yetki devri ajanı** | Onay geçmişinden öneri: "Bu türde 40 kaydı düzeltmeden onayladınız, eşik ₺X'e inebilir." Öneri politikayı değiştirmez; patron kabul edince yeni `AuthorityPolicy` sürümü oluşur |
| Geri alma | Devir sonrası hata oranı izlenir; kötüleşirse otomatik uyarı ve geri alma önerisi |
| Yedek onaylayıcı | Her onay yolu için; yokluk modunda kuyruk yedeğe akar |
| **Kilit kişi v2** | Onaylayıcıya ek: tek müşteri ve tek tedarikçi yoğunluğu (hesaplanır), tek imza ve kritik bilgi (beyan) |
| Yokluk tatbikatı | "İki hafta patron yok" simülasyonu: hangi kuyruk kimde birikir |

**Çıkış:** Pilotta en az bir eşik kanıtla değişti; patronun aylık onay sayısı ve devir sonrası düzeltme oranı raporlanıyor.

### K4 — Kurumsal hafıza ve dış güven · ~4 hafta

Hedef, test 5.

| İş | Not |
|---|---|
| **Aile-şirket ayrımı** | 131/331 ortak hesapları (sınıflandırıcı tablosuna da eklenir), ilişkili taraf ve kişisel görünen harcama sinyalleri. Yalnız işaretler, SMMM'ye yönlendirir; hukuki veya vergisel hüküm vermez |
| **Politika taslakçısı** | Gerçek davranıştan taslak: satın alma limiti, onay zinciri, masraf. Taslak, insan onayı, sürüm, yürürlük tarihi; karar defterine bağlı |
| **Endeks v2** | Dış kanıta dayalı boyutlar: toplantı düzeni, zamanında kapanma, gerçekleşen devir, yokluk tatbikatı, aile-şirket ayrımı. Olgunluk seviyesi ve bir sonraki somut adım |
| **Kanıt dosyası** | Banka veya denetçiye: dönem kapanışı, mizan, karar defteri özeti, yetki politikası; her sayı kaynağına izlenebilir (`DefensibilityPacket` üstüne) |
| Dönem kapanışı (F5) | Ay kilidi ve mühür; sonraki satır düzeltme kaydı |

**Çıkış:** Bir pilot şirket kanıt dosyasını gerçek bir dış tarafa (banka veya denetçi) gösterdi ve geri bildirim alındı.

## 5. Ertelenenler

| İş | Neden | Ne zaman açılır |
|---|---|---|
| CTO ve CMO ajanlarını derinleştirmek | Küçük şirketin önceliği değil | Pilot isterse |
| Ödeme gibi otonom eylemler | Güven ölçülmedi; hata maliyeti yüksek | K3 ölçümü yeterli olunca; önce taslak |
| Çek/senet ayrıştırıcıları | Hangi ERP raporu olduğunu pilot söyler; veri modeli K1'de hazır | İlk pilot dosyası gelince |
| Reel performans (enflasyon) | Değerli ama ritmi kurmuyor; A6 önkoşulu | K2'den sonra |
| Olay günlüğü, görünümler (F2, F3) | Şimdilik `scheduler.py` yeterli | Kayıp olay veya ölçek sorunu görülünce |
| i18n göçü, demo turu | Yönetim katmanını bloklamıyor | Paralel, boşlukta |

## 6. Pilot protokolü (K1'den itibaren)

- **Seçim:** 3–5 şirket; hedef segmentte, SMMM'si katılmaya istekli, Logo/Netsis/Paraşüt verisi alınabilen.
- **Hazırlık:** Yazılı veri işleme ve gizlilik anlaşması, şirket başına ayrı org, onayla veri erişimi.
- **Ritim:** Haftada bir kısa görüşme; ayda bir yönetim toplantısına eşlik.
- **Karar kapıları (öneri, pilot başında netleşir):**
  - Patron K1 sonunda radarı haftalık açmıyorsa K2'ye geçmeden nedeni araştır.
  - K2 sonunda toplantı iki kez üst üste yapılmadıysa ritim tasarımını yeniden yap.
- **Kayıt:** Bulgular `pilot.py` geri bildirimlerine ve bu plana işlenir; demo testinde olmayan her hata, gerçek dosyadan kaynaklı bir test olur.

## 7. Ölçütler

Başlangıç değerleri K1'de ölçülür; önceden hedef uydurulmaz.

| Ölçüt | Kaynak | Test |
|---|---|---|
| Sorumlusu ve tarihi olan karar oranı | `decision_log` | 2 |
| Zamanında kapanan karar oranı | `decision_log` | 2 |
| Yapılan aylık toplantı sayısı | `management_meetings` | 1 |
| Patronun aylık onay sayısı ve düzeltme oranı | `smmm_onay`, politika sürümleri | 3 |
| En yoğun onaylayıcının payı | Endeks | 4 |
| Nakit tahmini sapması | Tahmin kaydı | Güven |
| Patronun haftalık geri dönüşü | Kullanım kaydı | Değer |

## 8. Sahip kararları

| # | Karar | Önerim | Bloklar |
|---|---|---|---|
| 1 | Hedef segment | 20–250 çalışan, kuşak geçişindeki aile şirketi | K1 pilotu |
| 2 | Ana kullanıcı ve kanal | Patron alıcı, SMMM/danışman kanal | K1 pilotu |
| 3 | Pilot şirketler | 3–5 şirket, tanıdık SMMM üzerinden | K1 |
| 4 | Hukuki gözden geçirme | Pilot öncesi KVKK ve sözleşme; K4 çıktıları için ayrıca | K1, K4 |
| 5 | C-suite'te bekleyen koşuyu kim onaylar | Patron, K3'te bölüm yöneticisine devredilebilir | K0 |
| 6 | Yeni roller (DISPATCH) | Bölüm yöneticisi, kurul üyesi | K3 |
| 7 | Bülten kanalı | Önce e-posta, WhatsApp pilot isterse | K2 |
| 8 | TCMB EVDS anahtarı, GİB VKN, mali mühür | Hesap sahibi açar | A6, e-Defter |
| 9 | Docker/Postgres/Redis | Pilot öncesi bir staging ortamı şart; worker yolu bu makinede test edilemiyor | K1 |

## 9. Riskler

| Risk | Azaltma |
|---|---|
| Patron ritmi benimsemez | Önce nakit değeri (K1); toplantı paketi hazır gelir, ek iş istemez |
| Gerçek veri demo gibi davranmaz | Pilot K1'de; her bulgu gerçek dosyadan test |
| LLM uydurma sayı veya hüküm üretir | Görüş ve yazıcı sayı üretemez; doğrulayıcı metindeki sayıları kaynakla karşılaştırır |
| Hukuki veya vergisel tavsiye algısı | Çıktılar işaret ve soru biçiminde, SMMM'ye yönlendirir |
| Kapsam genişler | §5 listesi; pilot kanıtı olmadan yeni rol veya özellik eklenmez |
| Tek geliştirici darboğazı | Aşama başına tek açık PR zinciri; süreler pilotla yeniden yazılır |

## 10. Doğrulama

- Her faz: `python scripts/verify.py` exit 0; `backend/app/agents/` dokunuşunda `pytest tests/test_agents/ -q`.
- Fixture'lar kaynaktan yazılır: gerçek dosya ve elle hesap.
- Her faz canlı denenir, tarayıcıda kullanıcının gördüğü ekranla doğrulanır.
- Migration'lar yalnız ekleme yapar. `CFOState`'ten alan silinmez. Yetki ve hız sınırı değişiklikleri insana gider (CLAUDE.md DISPATCH).
- Her yeni arka uç özelliğinin frontend kapısı olur; her yeni rota sahiplik kontrolü kullanır.

## 11. Sıradaki adım

K0'ın ilk işi PR zincirini indirmek, sonra A5. §8'deki 1–3 numaralı kararlar K1 başlamadan netleşmeli.
