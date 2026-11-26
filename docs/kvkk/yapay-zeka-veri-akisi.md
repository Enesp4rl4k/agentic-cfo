# Yapay zekâya giden veri: her kipte tam olarak ne gider

> Bu belge **hukuki görüş değildir** ve bir aktarımın hukuka uygun olduğunu **iddia etmez**. Kodun ne yaptığını ve
> hangi seçeneklerin teknik olarak mümkün olduğunu anlatır; hangisinin yeterli olduğu avukatın ve sahibin kararıdır
> ([avukata-sorular.md](avukata-sorular.md), Q1 ve Q15). Sağlayıcı seçimi (varsayılan `api.deepseek.com`, model
> `deepseek-chat`) bu çalışmada **değişmedi**.

## Tek geçit

Dile model veya gömme (embedding) çağrısı yapan her kod iki dosyadan geçer; başka hiçbir modül istemci kuramaz, sağlayıcının
adresini okuyamaz, sağlayıcı adresi yazamaz. Bunu `backend/tests/test_llm_egress_choke_point.py` AST ile kanıtlar
(izin listesi satır satır gerekçelidir; liste yalnızca küçülebilir).

| Geçit | Neyi taşır | Kod |
|---|---|---|
| Model ağ geçidi | sohbet, anlatı, yapılandırılmış çıktı, akış (`complete`, `complete_text`, `stream`, `_raw_chat`) | `backend/app/platform/model_gateway.py` |
| Gömme ağ geçidi | belge parçaları ve sorgu gömmeleri | `backend/app/platform/embedding_gateway.py` |
| Veri azaltma katmanı | kip, maskeleme, geri çevirme, denetim kaydı | `backend/app/platform/llm_egress/` |

49 çağrı yerinin (≈40 ajan modülü) hepsi, sahte bir sağlayıcının **aldığı her şeyi kaydettiği** bir matriste çalıştırılır
(`backend/tests/test_llm_egress_matrix.py`): maskeli kipte hiçbir kanarya değer (bilinen IBAN, TCKN, VKN, kart, telefon, e-posta,
karşı taraf, tedarikçi, şirket, üye ve mali müşavir adı) hiçbir kayıtta bulunmaz; ham kipte aynı koşu kanaryayı **taşır**
(yoksa test boş bir kanıt olurdu); kapalı kipte sağlayıcı hiç çağrılmaz. Yeni bir çağrı yeri sürücüsüz eklenemez.

## Kipler

`LLM_DATA_MODE` (sunucu varsayılanı) ve şirketin kendi seçimi (`organizations.llm_data_mode`, ekran: Ayarlar > Veri ve gizlilik >
Yapay zekâya giden veri). Şirket seçimi yalnızca **sıkılaştırabilir**; sunucudan daha gevşek bir kip, ancak işletmeci
`LLM_ORG_MAY_RELAX=true` derse geçerli olur. Her seçim, kim ve ne zaman ile birlikte karar kaydına yazılır
(`llm_data_mode_change`, yalnızca sahip ve yönetici okur).

| Kip | Ne olur |
|---|---|
| `off` | Hiçbir LLM ve gömme çağrısı yapılmaz. Ürün deterministik yollarla çalışır (aşağıda ne kaybedildiği). |
| `masked` (**önerilen varsayılan**) | Kimlik kalıpları ve defterlerin bildiği adlar yer tutucuyla değiştirilir; yanıt, saklanmadan ve gösterilmeden önce geri çevrilir. |
| `raw` | Master'daki davranış: metin olduğu gibi gider. Hiçbir zaman geri düşülen bir değer değil, **açık bir seçim**. Üretimde, yerel olmayan bir sağlayıcıyla birleşirse ön uç denetimi (`preflight`) UYARI verir (`llm_raw_foreign`). |

`LLM_DOCUMENT_TEXT=never` her kipte **hiç belge metni göndermez**: belge okuma deterministik ayrıştırıcılara kalır, yüklemenin
sonucu "Yapay zekâ adımı atlandı" der (karar: kullanıcı boşluğu sessizce görmez).

## Her kipte ne gider

| Veri türü | `off` | `masked` | `raw` |
|---|---|---|---|
| Tutar, tarih, para birimi | gitmez | **olduğu gibi gider** (hiçbir zaman değiştirilmez) | olduğu gibi |
| Karşı taraf, tedarikçi, müşteri adı | gitmez | yer tutucu (`[KARŞI_TARAF_3]`) | olduğu gibi |
| Şirketin kendi adı ve unvanı | gitmez | yer tutucu (`[ŞİRKET_1]`) | olduğu gibi |
| Üye ve mali müşavir adı | gitmez | yer tutucu (`[KİŞİ_2]`) | olduğu gibi |
| IBAN, TCKN, VKN, kart, telefon, e-posta, plaka, "Hesap No" | gitmez | yer tutucu | olduğu gibi |
| İşlem açıklaması (serbest metin) | gitmez | **yalnızca yukarıdakiler değiştirilir; geri kalanı olduğu gibi** | olduğu gibi |
| Belge metni (yedek çıkarım yolu: ilk 8.000 karakter) | gitmez | aynı kısmi maskeleme | olduğu gibi |
| Sohbet sorusu ve geçmişi | gitmez | aynı kısmi maskeleme | olduğu gibi |
| Gömme parçaları (1.800 karakter) ve sorgular | gitmez (TF-IDF'e düşer) | kararlı yer tutucularla (aşağıda) | olduğu gibi |

## Neyi, nasıl buluyor

* **Kalıplar, kontrol basamağıyla** (`detectors.py`): IBAN (TR ve genel, mod 97; TR tam 26 karakter), TCKN (11 hane + iki kontrol
  basamağı), VKN (10 hane + kontrol basamağı), kart (Luhn), telefon (TR biçimleri: `0532 123 45 67`, `+90…`, sabit hat), e-posta,
  plaka, "Hesap No: …". Sağlama tutmayan 11 haneli sayı TCKN **sayılmaz**; sağlaması tutan ama bir **tutar bağlamında** olan sayı
  da sayılmaz (`Tutar:`, `TL`, `,00`, binlik ayracı yanında). VKN için ayrıca "VKN / Vergi No" etiketi gerekir. Binlik ayraçlı
  ve ondalıklı tutarlara, tarihlere, para birimlerine dokunulmaz (test: 800 rastgele satırda baytı baytına aynı).
* **Defterin bildiği adlar** (`dictionary.py`, `names.py`): NER modeli yok. Şirketin kendi tablolarından kurulur: şirket adı ve
  unvanı, işlem tedarikçisi ve karşı tarafı, ana defter, açık kalemler, ilişkili taraflar, karşı taraf takma adları, kategori
  kuralı tedarikçileri, üyeler ve mali müşavir. Eşleşme büyük/küçük harf ve aksan duyarsızdır; Türkçe `İ/ı/I/i`, `Ş/ş`, `Ğ/ğ`, `Ü/ü`,
  `Ö/ö`, `Ç/ç` birbirine katlanır ve katlama **uzunluğu korur**, yani bulunan aralık özgün metindeki aralıktır. "A.Ş.", "AŞ",
  "Ltd. Şti.", "Limited Şirketi", "San. ve Tic." ekleri isteğe bağlıdır (iki yönde). Defterin bildiği vergi numarası etiketsiz de bulunur.
  Her kaynak 5.000 ayrık değerle sınırlıdır; sınır aşılırsa ekran ve denetim satırı bunu söyler (sınırın ötesindeki adlar maskelenmez).
* **Yer tutucular** tiplidir ve **istek başına** numaralanır (ilk görünüşe göre): aynı değer aynı çağrıda aynı yer tutucudur,
  model akıl yürütebilir; bir sonraki çağrıda numaralar yeniden başlar, sağlayıcı iki çağrıyı yer tutucuyla birbirine bağlayamaz.
* **Yanıt geri çevrilir** (saklanmadan ve gösterilmeden önce; akışta bölünmüş yer tutucular bütünlenene kadar tutulur). Modelin
  **uydurduğu** (bu çağrıda hiç verilmemiş) bir yer tutucu yanlış bir ada çevrilmez: `[bilinmeyen taraf]` (kimlik türleri için
  `[bilinmeyen değer]`) görünür. Defterin yazımıyla gösterilir (`ATLAS LOJISTIK` yazılsa da defterdeki ad gelir).

### Gömme: neden kararlı takma adlar

İndeks zamanı ile sorgu zamanı aynı adı aynı belirteçle yazmazsa kosinüs benzerliği bozulur. İstek başına numaralar bunu bozardı. Bu
yüzden gömme yolunda yer tutucu, (şirket, tür, değer) üzerinden **sunucu sırrıyla anahtarlanmış bir özetten** türetilir
(`[KARŞI_TARAF_a1b2c3d4]`): aynı şirkette aynı ad her zaman aynı belirteçtir, başka şirkette farklıdır, sağlayıcı tahmin ettiği bir adı
özetleyerek geri çeviremez. Saklanan satır `<model>+pseud1` etiketiyle yazılır; sorgu yalnızca **kendi etiketindeki** satırları
arar, böylece ham metinden hesaplanmış vektörlerle maskeli metinden hesaplanmış vektörler asla karşılaştırılmaz. Kip değişince
eski satırlar yeniden gömülmez (ham gömülmüş eski satırlar sağlayıcıda ve veritabanında kalır; yeniden indeksleme gerekir). Kararlı belirteç,
aynı varlığın şirket içinde tekrar geçtiğini sağlayıcıya gösterir (adı değil, tekrarı).

## Denetim kaydı (yük yok)

Her mantıksal çağrı için `llm_call_logs` satırı: şirket, amaç (`task_type`: ajan/görev), kip, yer tutucu türü başına değiştirme
sayısı (`replaced.counts`), uyarı bayrakları (`no_organisation_context`, `dictionary_truncated`, `dictionary_incomplete`),
gönderilen bayt (tüm denemeler). İstem, yanıt, ad ya da sayı **hiçbir yerde saklanmaz**. Ekran, son 30 günün çağrı ve bayt sayısını
yalnızca sayı olarak gösterir. Geçiş: `079_llm_egress_audit` (3 sütun `llm_call_logs`'a, 1 sütun `organizations`'a).

## `off` kipinde ne kaybedilir

Rakamlar, raporlar, çalışma sermayesi/pist, kural tabanlı metinler ve belge okuma (banka ekstresi, CSV, e-Fatura ayrıştırıcıları) aynen çalışır.
Kaybedilenler: sohbet ve doğal dil sorgusu (503 "kapalı" yanıtı; WebSocket'te "kapalı" iletisi), model anlatıları (şablon metin veya
"açıklama yok, rakamlar korunuyor"), ayrıştırıcıların tanımadığı belgelerin yapay zekâyla okunması ("Yapay zekâ adımı atlandı" ve inceleme
bekler), THP hesap tahmini (varsayılan hesap), anomali açıklaması, belge anlamsal araması (TF-IDF'e düşer; kalite biraz düşer).

## Kalan risk (düz sözle)

* **Serbest metin açıklamalar ve belgeler hâlâ kişisel veri taşıyabilir.** Ne kalıplar ne de defterin bildiği adlar şunları bulamaz:
  yalnızca bir notta geçen bir kişi, defterde farklı yazılmış bir ad, yazım hatası, takma ad, "Ahmet Bey", yalnızca ad ya da yalnızca soyad,
  pasaport veya başka bir kimlik numarası, adres, kalıbı tutmayan telefon, görseldeki metin.
* **Tutarlar, tarihler ve para birimleri her zaman gider.** Defterin yapısı (kaç işlem, hangi aylar, hangi kategoriler) sağlayıcıya görünür.
* Maskeleme **şirket bağlamı** ister: bağlamsız bir çağrıda (bir sistem işi) yalnızca kalıplar maskelenir ve denetim satırı
  `no_organisation_context` taşır. İstek yolları, işçi işleri ve WebSocket şirket bağlamını kurar.
* Sağlayıcı tarafında tutulan veri (istek günlükleri, eğitim) bu çalışmanın dışındadır; yer tutucular bunu **azaltır**, silmez.
* Bir yer tutucu, modelin cevabında **başka bir bağlamda** geri çevrilince yanlış okunamaz ama okunabilirliği bozabilir: kalite biraz
  değişebilir (özellikle adın anlamına dayanan çıkarımlarda).

## Hangi dosya neyi sınar

`test_llm_egress_pseudonymizer.py` (kontrol basamakları, bağlam, Türkçe harfler, gidiş-dönüş, uydurma yer tutucu), `test_llm_egress_gateway.py`
(maskeli/kapalı/ham, yapılandırılmış çıktı, akış, gömme, denetim satırı, şirket seçimi, ham = master ile baytı baytına aynı),
`test_llm_egress_matrix.py` (49 çağrı yeri), `test_llm_egress_choke_point.py` (kimse geçidi atlayamaz), `test_llm_egress_api.py` (ekran ve karar kaydı).
