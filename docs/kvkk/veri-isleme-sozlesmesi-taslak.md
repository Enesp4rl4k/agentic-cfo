# VERİ İŞLEME SÖZLEŞMESİ — TASLAK

> **TASLAK — hukukçu incelemesi gerekir.** Bu metin kodun bugünkü hâline bakılarak bir
> mühendis tarafından yazıldı; hukuki görüş değildir. Köşeli parantez içindeki `[...]`
> alanlar ve "AÇIK KONU" notları sahibi ve avukat tarafından doldurulmalıdır. Teknik
> dayanaklar için bkz. [veri-envanteri.md](veri-envanteri.md); karar bekleyen konular için
> [acik-konular.md](acik-konular.md).

## 1. Taraflar

- **Veri Sorumlusu:** Platformu kullanan şirket (müşteri firma) — `[Unvan, VKN, adres, KEP]`.
  Platforma mali müşaviri (SMMM) aracılığıyla katılan şirketlerde de veri sorumlusu
  **şirketin kendisidir**; SMMM, şirketin talimatıyla hareket eden ayrı bir veri
  sorumlusu / veri işleyen olarak ayrıca değerlendirilmelidir (bkz. §1.1).
- **Veri İşleyen:** `[Platform işleten tüzel kişi, VKN, adres, KEP]` ("Platform").

### 1.1 Mali müşavirin konumu — AÇIK KONU

Kodda SMMM, müşteri şirketin organizasyonuna `smmm` rolüyle katılan bir kullanıcıdır
(`backend/app/models/user.py:40`) ve müşteri listesi kendi `smmm_musteri_kayit`
tablosunda tutulur (`backend/app/models/smmm_portal.py:63`). Üç kurgu mümkündür; avukat
seçmelidir:

1. Şirket = veri sorumlusu, SMMM ve Platform = (alt) veri işleyen.
2. SMMM = kendi meslek faaliyeti için bağımsız veri sorumlusu (3568 s. Kanun saklama
   yükümlülüğü), Platform = SMMM'nin veri işleyeni.
3. Şirket ve SMMM müşterek; Platform her ikisine karşı veri işleyen.

Bu taslak (1)'i esas alır.

## 2. Konu ve süre

Platform, Veri Sorumlusu adına; yüklenen veya bağlanan muhasebe verisinden (e-Fatura/e-Arşiv
XML, banka ekstresi, Excel/CSV, PDF, Paraşüt gibi muhasebe yazılımı senkronu) nakit, kâr-zarar,
alacak-borç ve tahmin raporları üretir. Sözleşme, ana hizmet sözleşmesi süresince yürürlükte
kalır.

## 3. İşlenen veri kategorileri ve ilgili kişiler

Ayrıntı: [veri-envanteri.md §2](veri-envanteri.md). Özet:

| İlgili kişi grubu | Veri kategorisi | Örnek alanlar |
|---|---|---|
| Platform kullanıcıları (şirket çalışanı, SMMM) | Kimlik, iletişim, işlem güvenliği | ad-soyad, e-posta, IP, tarayıcı bilgisi |
| Şirketin karşı tarafları (müşteri/tedarikçi, gerçek kişi olabilir) | Kimlik, finans | unvan/ad, VKN/TCKN, fatura ve banka hareketi açıklaması, tutar |
| Şirket ortakları ve ilişkili kişiler | Kimlik, finans | ad, VKN/TCKN, ilişki türü |
| Şirket çalışanları (İK verisi yüklenirse) | Finans, özlük | maaş, işe giriş tarihi — **AÇIK KONU**, bkz. acik-konular §6 |

Özel nitelikli kişisel veri (KVKK m.6) işlenmesi amaçlanmamaktadır; ancak serbest metinli
banka açıklamalarında ve yüklenen belgelerde bulunabilir. Platform bunu ayırt edemez.

## 4. Veri İşleyenin yükümlülükleri

1. Veriyi yalnızca Veri Sorumlusunun belgelenmiş talimatı doğrultusunda ve §2'deki amaçla işler.
2. **Kiracı ayrımı:** bir organizasyonun verisi başka bir organizasyonun kullanıcısına
   gösterilmez. Teknik dayanak: `backend/app/api/access.py:42` (`can_access`), bütün
   rotaları gezen test `backend/tests/test_route_access.py`.
3. **Erişim kontrolü:** organizasyon içi roller owner / admin / cfo / analyst / viewer / smmm
   (`backend/app/models/user.py:31`). Üye yönetimi yalnız owner/admin
   (`backend/app/api/org.py:70`).
4. **Kayıt tutma:** veri değiştiren her istek, kullanıcı, IP ve tarayıcı bilgisiyle
   `audit_logs` tablosuna yazılır (`backend/app/middleware/audit.py:131`); parola/token
   alanları maskelenir (`backend/app/middleware/audit.py:48`).
5. **Saklama:** Veri Sorumlusunun talimatı ve [acik-konular.md §2](acik-konular.md)'de
   kararlaştırılacak süreler. *Bugün kodda otomatik silme yoktur* — bu madde
   yürürlüğe girmeden önce uygulanmalıdır.
6. **Gizlilik:** Veriye erişen personel gizlilik taahhüdü altındadır. `[doldurulacak]`
7. **İhlal bildirimi:** Veri İşleyen, öğrendiği bir veri ihlalini gecikmeksizin ve en geç
   `[24]` saat içinde Veri Sorumlusuna bildirir; Veri Sorumlusu Kurul'a 72 saat içinde
   bildirir. Kodda ihlal kaydı için tablo mevcuttur (`backend/app/models/compliance_extended.py:59`),
   işletim süreci yazılmamıştır.
8. **İlgili kişi başvuruları (KVKK m.11):** Veri İşleyen, Veri Sorumlusuna gelen başvurulara
   `[10]` iş günü içinde teknik destek verir. *Bugün kodda kişi bazlı dışa aktarma veya
   silme işlevi yoktur* — bkz. acik-konular §4.
9. **Sözleşme sonu:** Sözleşme bittiğinde veri, Veri Sorumlusunun tercihine göre iade edilir
   veya silinir; yasal saklama yükümlülükleri saklıdır.

## 5. Alt veri işleyenler

Veri Sorumlusu aşağıdaki alt işleyenlere genel yetki verir; yeni bir alt işleyen
eklenmeden `[30]` gün önce bildirim yapılır ve Veri Sorumlusu itiraz edebilir.

| Alt işleyen | Hizmet | Yer | Yurt dışı? | Kodda |
|---|---|---|---|---|
| `[TR VPS sağlayıcısı]` | Sunucu, veritabanı, dosya deposu, Redis | Türkiye | Hayır | docker-compose |
| **Büyük dil modeli sağlayıcısı** (varsayılan DeepSeek; OpenAI alternatif) | Metin üretimi, sınıflandırma | Çin / ABD | **EVET** | `backend/app/config.py:213-218` |
| Hata izleme (Sentry — bugün fiilen kapalı, veri-envanteri §5) | Hata kayıtları | `[ABD/AB]` | Açılırsa **EVET** | `backend/app/services/sentry_monitoring.py:36`, `:51` |
| E-posta gönderimi (SMTP; varsayılan `smtp.gmail.com`) | Bildirim e-postası | `[ABD]` | **EVET** | `backend/app/config.py:177` |
| Slack / WhatsApp (Meta, Twilio), yalnızca müşteri açarsa | Uyarı bildirimi | ABD | **EVET** | `backend/app/config.py:144-151` |
| Paraşüt, Akbank, Garanti (müşteri bağlarsa) | Veri kaynağı (çekme) | Türkiye | Hayır | `backend/app/config.py:173,199,202` |

**Yurt dışı aktarım (KVKK m.9) — AÇIK KONU:** LLM, Sentry ve SMTP satırları yurt dışı
aktarımdır. Hangi alanların LLM istemine girebildiği
[veri-envanteri.md §4](veri-envanteri.md)'te tek tek listelenmiştir. 2024 değişikliği
sonrası m.9 kapsamında hangi aktarım aracının (standart sözleşme + Kurul'a 5 iş günü içinde
bildirim, açık rıza, ya da aktarımı ortadan kaldıran maskeleme / TR-içi model) seçileceği
[acik-konular.md §1](acik-konular.md)'dedir. Bu karar verilmeden bu madde imzalanmamalıdır.

## 6. Teknik ve idari tedbirler (bugünkü durum)

| Tedbir | Durum | Dayanak |
|---|---|---|
| Kiracı ayrımı, tüm rotalarda | Var | `backend/app/api/access.py:42` |
| Dosya yükleme doğrulaması (uzantı, ≤10 MB, XML'de DTD/ENTITY yasağı) | Var | `CLAUDE.md` kural 9, `backend/app/config.py:221` |
| Entegrasyon sırlarının şifreli saklanması | Var | `backend/app/models/erp_integration.py:47`, `backend/app/models/connector_connection.py:40` |
| Denetim kaydı (IP dahil) | Var | `backend/app/middleware/audit.py:131` |
| Sentry'ye PII'nin varsayılan olarak gitmemesi (Sentry bugün kapalı) | Var (kısmi) | `backend/app/services/sentry_monitoring.py:70` |
| Çok faktörlü kimlik doğrulama | **Yok** — 6 haftalık planda | — |
| Yedekleme ve geri dönüş | **Yok** — 6 haftalık planda | — |
| Otomatik saklama/silme | **Yok** | bkz. veri-envanteri §6 |
| LLM'e gitmeden önce maskeleme | **Yok** | bkz. veri-envanteri §4 |

## 7. Denetim

Veri Sorumlusu, yılda bir kez veya bir ihlal sonrasında, `[30]` gün önceden bildirerek
tedbirleri denetleyebilir veya bağımsız denetim raporu isteyebilir.

## 8. Sorumluluk, uygulanacak hukuk

`[Avukat tarafından doldurulacak]` — Türk hukuku, `[İstanbul]` mahkemeleri.
