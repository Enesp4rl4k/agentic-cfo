# KİŞİSEL VERİLERİN İŞLENMESİNE İLİŞKİN AYDINLATMA METNİ — TASLAK

> **TASLAK — hukukçu incelemesi gerekir.** Kodun bugünkü hâline bakılarak yazıldı; hukuki
> görüş değildir. `[...]` alanlar doldurulmalı, "AÇIK KONU" notları
> [acik-konular.md](acik-konular.md)'deki kararlara göre güncellenmelidir. Teknik dayanaklar:
> [veri-envanteri.md](veri-envanteri.md).
>
> **Kimin metni?** Platformda veri sorumlusu, platformu kullanan şirkettir (ve/veya mali
> müşaviri — bkz. veri-isleme-sozlesmesi-taslak §1.1). Bu metin, şirketin **kendi
> kullanıcılarına ve karşı taraflarına** yapacağı aydınlatmanın Platform'a ilişkin kısmı için
> bir şablondur. Platform'un *kendi* veri sorumlusu olduğu veriler (hesap açılışı, faturalama,
> pilot davetleri) için ayrı ve kısa bir metin gerekir — §8.

---

## 1. Veri sorumlusu

`[Şirket unvanı]` ("Şirket"), `[adres]`, `[KEP adresi]`.

Şirket, finansal raporlama için `[Platform adı]` yazılımını ("Platform") kullanmaktadır.
Platform'u işleten `[Platform işleten tüzel kişi]`, Şirket adına **veri işleyen** sıfatıyla
hareket eder.

## 2. Hangi kişisel verilerinizi işliyoruz?

**Platform kullanıcısıysanız** (Şirket çalışanı veya mali müşavir):
- Kimlik ve iletişim: ad-soyad, e-posta adresi; mali müşavirler için ayrıca unvan, vergi no,
  oda sicil no, il, telefon.
- İşlem güvenliği: giriş zamanı, veri değiştiren işlemlerinizde IP adresi ve tarayıcı bilgisi,
  yaptığınız işlemin kaydı.
- Platform içinde yazdığınız sorular, notlar, onay/düzeltme açıklamaları ve geri bildirimler.

**Şirketin müşterisi, tedarikçisi veya başka bir karşı tarafıysanız:**
- Faturada veya banka hareketinde görünen adınız/unvanınız, VKN veya TCKN'niz, vergi daireniz,
  işlem tutarı, tarihi ve açıklaması. Banka hareket açıklamaları IBAN veya ad-soyad
  içerebilir.

**Şirket ortağı veya ilişkili kişiyseniz:** adınız, VKN/TCKN'niz ve Şirketle ilişkinizin türü.

## 3. Hangi amaçla işliyoruz?

- Şirketin nakit durumu, kâr-zarar, alacak-borç ve vergi raporlarının hazırlanması;
- Faturaların banka hareketleriyle eşleştirilmesi ve tahsilat/ödeme takibi;
- Mali müşavirin kayıtları onaylaması ve düzeltmesi;
- Platform güvenliği, yetkisiz erişimin tespiti ve hata ayıklama;
- Kullanıcıya uyarı ve bildirim gönderilmesi.

## 4. Hukuki sebep (KVKK m.5)

- Bir sözleşmenin kurulması veya ifası (m.5/2-c) — Platform kullanıcıları için;
- Hukuki yükümlülüğün yerine getirilmesi (m.5/2-ç) — VUK ve TTK kapsamındaki defter/belge
  düzeni;
- Veri sorumlusunun meşru menfaati (m.5/2-f) — karşı taraf verisinin finansal raporlamada
  kullanılması, güvenlik kayıtları;
- **Yurt dışına aktarılan veriler için m.9 kapsamında ayrı bir dayanak** — §5.

## 5. Kişisel verileriniz kimlere aktarılıyor? — **AÇIK KONU**

- Platform verileri `[Türkiye'deki sunucu sağlayıcısı]` üzerinde, Türkiye'de tutulur.
- **Yurt dışı aktarım:** Platform, raporların açıklama metinlerini üretmek, işlemleri
  sınıflandırmak ve sorularınızı yanıtlamak için yurt dışında yerleşik bir büyük dil modeli
  sağlayıcısına (`[DeepSeek (Çin) / OpenAI (ABD) — karara bağlı]`) metin gönderir. Bu metin;
  fatura/banka hareketindeki karşı taraf adı, işlem açıklaması ve tutarlar ile yüklenen
  belgenin metnini içerebilir. Ayrıntılı alan listesi: veri-envanteri §4.
  `[Bu paragraf, acik-konular §1'deki karara göre yeniden yazılacak: açık rıza alınacaksa
  rıza metni ayrı tutulmalı; maskeleme veya TR/AB-içi model seçilirse paragraf
  daraltılmalıdır.]`
- Bildirim e-postaları için `[e-posta sağlayıcısı]` (bugünkü varsayılan Gmail, yurt dışı).
  Hata izleme (Sentry) bugün kapalıdır; açılırsa buraya eklenmelidir.
- Şirketin açtığı entegrasyonlar (Paraşüt, banka API'leri) veriyi Platform'a *getirir*;
  Platform bu sağlayıcılara kişisel veri göndermez.
- Yetkili kamu kurumlarına, kanunen zorunlu olduğunda.

## 6. Saklama süresi — **AÇIK KONU**

`[acik-konular §2'deki karara göre doldurulacak.]` Önerilen: muhasebe kaynaklı kayıtlar VUK
m.253 uyarınca 5 yıl + içinde bulunulan yıl; güvenlik kayıtları `[2]` yıl; Platform hesabı
kapandıktan sonra hesap verisi `[90]` gün.

## 7. Haklarınız (KVKK m.11)

Kişisel verinizin işlenip işlenmediğini öğrenme, bilgi talep etme, amacını ve aktarıldığı
kişileri öğrenme, düzeltilmesini veya silinmesini isteme, otomatik sistemlerle analiz
sonucunda aleyhinize bir sonuç çıkmasına itiraz etme ve zararın giderilmesini talep etme
haklarına sahipsiniz. Başvurularınızı `[Şirket başvuru kanalı]` üzerinden Şirkete
iletebilirsiniz; Şirket 30 gün içinde yanıtlar.

> Mühendis notu: Bugün Platform'da kişi bazlı veri dökümü veya silme işlevi yoktur
> (veri-envanteri §6). Bu metin yayımlanmadan önce bu işlevin ya da elle yürütülecek bir
> prosedürün hazır olması gerekir.

## 8. Platform'un kendi veri sorumlusu olduğu veriler (ayrı metin gerekir)

Hesap açılışı ve kimlik doğrulama (`users`), pilot davetleri ve geri bildirim (`pilot_invites`,
`user_feedback`), abonelik/ödeme kimlikleri (`organizations.stripe_customer_id`) ve mali
müşavir kayıt bilgileri (`smmm_muhasebeci`) için Platform veri sorumlusudur. Bunlar için
kısa, ayrı bir aydınlatma metni hazırlanmalıdır — bkz. acik-konular §5.
