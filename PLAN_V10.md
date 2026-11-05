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

**Bitti sayılır:** Radarın "dahil değil" listesi boş, ya da kalan her madde için pilotta veri olmadığı yazılı.

### O4 — Haftalık ritim · Hafta 5–6

- **Pazartesi bülteni:** Önce e-posta. Üç cümle: radardaki değişiklik, yaklaşan yükümlülük, en önemli tek eylem.
  - Sayılar deterministik hesaplanır; LLM yalnızca metni yazar.
  - LLM yoksa şablon kullanılır.
  - Doğrulayıcı, metindeki her sayıyı kaynağıyla karşılaştırır.
- **Karar ve taahhüt kaydı:** Bültendeki eylem "yaptım / ertele / gerek yok" diye cevaplanır. Sorumlu kişi ve tarih kaydedilir. Bu, v9 K2'nin yalnızca bu akışa yeten kısmıdır.

**Bitti sayılır:** Bülten her pazartesi 3 pilota gidiyor; cevaplar kaydediliyor.

### O5 — Ölçmek · Hafta 6–8

- **İsabet:** Gece notlama, 4 hafta önceki tahmini gerçekleşen bakiyeyle karşılaştırır.
- **Gösterim:** Sapma bültende ve ekranda gösterilir. İlk sayı ne çıkarsa o gösterilir.
- **Rapor:** Pilot başına isabet raporu ve bu plana işlenen bulgular.

**Bitti sayılır:** 3 pilotun verisiyle ölçülmüş bir 4 haftalık sapma var.

## 5. Ölçütler

Hedef sayı yalnızca ilk ölçütte var; ötekiler önce ölçülür, sonra hedef konur.

| Ölçüt | Kaynak | Eşik |
|---|---|---|
| Bülteni 6 hafta üst üste açan pilot | Kullanım kaydı | 3 / 3 |
| Radarın 4 haftalık sapması | Tahmin kaydı | Ölçülür, gösterilir |
| Radardan çıkan gerçek karar | Karar kaydı | En az 1 |
| İlk kurulum süresi | Pilot gözlemi | Ölçülür |
| Okunamayan satır oranı | Yükleme raporu | Ölçülür |

**Karar kapıları:**
- 4. haftada hiçbir pilot radarı haftalık açmıyorsa O4'e geçilmez; nedeni pilotla görüşülür.
- 8. haftada ölçüt tutmadıysa sonraki plan yeni özellikle değil, bulgularla yazılır.

## 6. Durdurulanlar

- **Yeni ajan ya da rol yok.** CTO, CMO, COO, CHRO ve CEO ajanları olduğu gibi kalır, menüde görünmez.
- **v9 K2'nin geri kalanı, K3 ve K4 bekler:** kurul sekreteri, boardroom hafızası, yetki devri, Endeks v2, kanıt dosyası. Ölçüt tuttuktan sonra yeniden değerlendirilir.
- **Akış dışı ekranlarda yalnızca güvenlik ve veri bütünlüğü hataları düzeltilir.**
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
| Tek geliştirici darboğazı | Aynı anda tek açık PR zinciri |

## 9. Doğrulama

- Her aşama: `python scripts/verify.py` exit 0; `backend/app/agents/` dokunuşunda `pytest tests/test_agents/ -q`.
- Fixture'lar kaynaktan yazılır; O2'den itibaren kaynak, pilotun kendi dosyasıdır.
- Her aşama canlı denenir: staging'de, kullanıcının gördüğü ekranla.
- CLAUDE.md DISPATCH: yetki ve hız sınırı değişiklikleri, silen migration'lar ve production port değişiklikleri insana gider. O1'deki staging port ve compose değişiklikleri bu kapsamdadır.

## 10. Sıradaki adım

1. `feat/v9-k1-cash-radar` dalını PR olarak açmak.
2. O0: menü daraltma.
3. §7'deki 2 ve 3 numaralı kararlar (pilotlar, barındırma) O1 başlamadan netleşmeli.
