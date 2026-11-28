# Yapay zekâya giden veri: her kipte tam olarak ne gider

> Bu belge **hukuki görüş değildir** ve bir aktarımın hukuka uygun olduğunu **iddia etmez**. Kodun ne yaptığını ve
> hangi seçeneklerin teknik olarak mümkün olduğunu anlatır; hangisinin yeterli olduğu avukatın ve sahibin kararıdır
> ([avukata-sorular.md](avukata-sorular.md), Q1 ve Q15). Sağlayıcı seçimi (varsayılan `api.deepseek.com`, model
> `deepseek-chat`) bu çalışmada **değişmedi**.

## Tek geçit

Dile model veya gömme (embedding) çağrısı yapan her kod iki dosyadan geçer. Bunu iki test, kodun sözdizimi ağacı (AST) üzerinden
denetler; yorum ve açıklama metni sayılmaz:

* `backend/tests/test_llm_egress_choke_point.py`: başka hiçbir modül kendi istemcisini kuramaz, model kütüphanesini içe aktaramaz,
  sağlayıcının adresini okuyamaz, sağlayıcı adresi yazamaz (izin listesi satır satır gerekçelidir; liste yalnızca küçülebilir).
* `backend/tests/test_llm_egress_provider_helpers.py`: başka hiçbir modül **geçidin kendi istemcisini ödünç alamaz**. Geçidin içinde
  istemci kuran ya da sağlayıcıya istek gönderen her işlev (bugün `_build_client`, `_raw_chat`, `_build_embeddings`, `_client_embed`)
  elle yazılmış bir listeden değil, geçidin kendi kodundan türetilir; böylece yarın eklenecek bir yardımcı da ilk gününden kapsanır. Bu
  işlevler kendi geçidi dışında hiçbir biçimde anılamaz: içe aktarma (başka adla, göreli yoldan, `*` ile), modül takma adı üzerinden
  erişim, `getattr` / `vars` / `__dict__`, `importlib` ya da `sys.modules` ile adla erişim, başka bir modül üzerinden yeniden dışa aktarma.
  Geçit de bunları dışarıya açamaz: sağlayıcıya ulaşan herkese açık bir işlev yalnızca belgelenmiş giriş noktalarından biri olabilir
  (`complete`, `complete_text`, `complete_json`, `stream`, `embed_texts`; bunlar göndermeden önce maskeleme oturumunu açar). Tek
  belgelenmiş istisna: `services/llm_router.py`, `_raw_chat`'i yalnızca `LLMTaskRouter._call_llm` içinde içe aktarır (`_raw_chat`
  maskeleme oturumunu kendisi açar). Son bağımsız incelemenin denediği atlatma (bir ajana `model_gateway._build_client(...).ainvoke(...)`
  ve `embedding_gateway._client_embed(...)` eklemek) önceki testlerden geçiyordu; şimdi bu ve 20 benzer değişiklik geçici dosyalarla
  denenir ve her biri testi düşürür. Kapsamı: `backend/app/` ve `backend/scripts/`. Statik bir denetim olarak kasıtlı gizlemeyi göremez: `exec`/`eval` dizesi, adı
  çalışma anında hesaplanan `importlib`, `sys.modules` üzerinde dolaşma, modül nesnesini başka bir modülün özniteliğinden alma. Bunlara
  karşı arka kalkan, her çağrı yerinin sahte sağlayıcıyla çalıştırıldığı matristir.

| Geçit | Neyi taşır | Kod |
|---|---|---|
| Model ağ geçidi | sohbet, anlatı, yapılandırılmış çıktı, akış (`complete`, `complete_text`, `stream`, `_raw_chat`) | `backend/app/platform/model_gateway.py` |
| Gömme ağ geçidi | belge parçaları ve sorgu gömmeleri | `backend/app/platform/embedding_gateway.py` |
| Veri azaltma katmanı | kip, maskeleme, geri çevirme, denetim kaydı | `backend/app/platform/llm_egress/` |

49 çağrı yerinin (≈40 ajan modülü) hepsi, sahte bir sağlayıcının **aldığı her şeyi kaydettiği** bir matriste çalıştırılır
(`backend/tests/test_llm_egress_matrix.py`), **uygulamanın o yere gerçekten ulaştığı giriş noktalarından** ve yalnızca o noktaların
kurduğu şirket bağlamıyla (`backend/tests/llm_egress_entries.py`: gerçek `get_current_user`, gerçek WebSocket işleyicisi, gerçek
işçi sarmalayıcıları `_records_run` / `run_ceo_analysis`, gerçek onay sonrası devam `devam_et`; test bağlamı kendisi kurmaz):

* maskeli kipte her giriş noktasından sağlayıcıya ulaşılır (yani şirket orada biliniyordur) ve hiçbir kanarya değer (IBAN'ın her
  yazımı, TCKN, VKN, kart, telefon, Unicode alan adlı e-posta, karşı taraf, tedarikçi, şirket, üye ve mali müşavir adı; ekli, satır
  bölünmüş, büyük harfli, yalnızca ad ya da yalnızca soyad) hiçbir kayıtta bulunmaz;
* ham kipte aynı koşu kanaryayı **taşır** (yoksa test boş bir kanıt olurdu); kapalı kipte sağlayıcı hiç çağrılmaz;
* **şirket bağlamı olmadan** (unutulmuş bir giriş noktasının vereceği durum) maskeli kip reddeder: hiçbir şey gitmez, ret sayılır;
* isim sözlüğü okunamazsa (temsilî yerlerde) yine reddeder.

**LangGraph durum kayıtları (checkpoint).** Ajan düğümlerinin durumu (rakamlar, geri çevrilmiş adlarla anlatılar) bizim
veritabanımızda saklanabilir (PR #157 ile Postgres). Bu, sağlayıcıya giden bir yol değildir: kaldığı yerden devam eden bir
düğüm modele yine yalnızca geçitten ulaşır, geçit her giden yükü o anda yeniden maskeler (ya da şirket bilinmiyorsa reddeder);
durum kaydını bir istemciye veren başka kod yoktur (AST testleri: istemciyi yalnızca iki geçit kurar ve geçidin istemciye dönük
iç işlevlerini başka kod çağıramaz) ve izleme açık olsa bile
düğüm girdisi/çıktısı izlere gitmez (aşağıda "İzleme").
Bu kayıtlar gerçek adları (geri çevrilmiş haliyle) taşıdığı için: şirket silinirken silme işleminin kendi işleminde silinir; silme talebi işleme alındığı andan sonra o şirket için yeni kayıt yazılmaz (`privacy/tombstone.py`, yazıcı reddeder ve süren koşu bir sonraki adımda durur); kaçan olursa silmenin son süpürmesi ve her saklama koşusu siler. Saklama süresi (`RETENTION_CHECKPOINT_DAYS`, 3 gün) `RETENTION_DRY_RUN`'dan bağımsız **uygulanır**: bu kayıtları okuyan kod yoktur.

Yeni bir çağrı yeri sürücüsüz ve giriş noktası bildirilmeden eklenemez. İnceleme, onay sonrası devam yolunun (`devam_et`) şirket
bağlamını kurmadığını buldu; düzeltildi ve matris bu hatayı artık adıyla yakalar.

## Kipler

`LLM_DATA_MODE` (sunucu varsayılanı) ve şirketin kendi seçimi (`organizations.llm_data_mode`, ekran: Ayarlar > Veri ve gizlilik >
Yapay zekâya giden veri). Şirket seçimi yalnızca **sıkılaştırabilir**; sunucudan daha gevşek bir kip, ancak işletmeci
`LLM_ORG_MAY_RELAX=true` derse geçerli olur. Her seçim, kim ve ne zaman ile birlikte karar kaydına yazılır
(`llm_data_mode_change`, yalnızca sahip ve yönetici okur).

| Kip | Ne olur |
|---|---|
| `off` | Hiçbir LLM ve gömme çağrısı yapılmaz. Ürün deterministik yollarla çalışır (aşağıda ne kaybedildiği). |
| `masked` (**önerilen varsayılan**) | Kimlik kalıpları ve defterlerin bildiği adlar yer tutucuyla değiştirilir; yanıt, saklanmadan ve gösterilmeden önce geri çevrilir. Çağrının şirketi bilinmiyorsa ya da şirketin isim sözlüğü tam okunamazsa **hiçbir şey gönderilmez** (aşağıda "Kapalı kalarak başarısız olma"). |
| `raw` | Master'daki davranış: metin olduğu gibi gider. Hiçbir zaman geri düşülen bir değer değil, **açık bir seçim**. Üretimde, yerel olmayan bir sağlayıcıyla birleşirse ön uç denetimi (`preflight`) UYARI verir (`llm_raw_foreign`). |

`LLM_DOCUMENT_TEXT=never` her kipte **hiç belge metni göndermez**: belge okuma deterministik ayrıştırıcılara kalır, yüklemenin
sonucu "Yapay zekâ adımı atlandı" der (karar: kullanıcı boşluğu sessizce görmez).

## Her kipte ne gider

| Veri türü | `off` | `masked` | `raw` |
|---|---|---|---|
| Tutar, tarih, para birimi | gitmez | **olduğu gibi gider**. Değiştirilmeme kuralının kapsamı aşağıda ("Önce sayılar korunur"): tutar olduğunu gösteren bir işareti olan her sayı (ayraç, ondalık, para birimi, yüzde, tutar sözcüğü, tutar adlı bir JSON/sözlük alanı ya da tablo/CSV sütununda eksi işareti) ve her tarih; 200.000 satırlık bulanık testte (beşte biri JSON biçiminde) sıfır değişiklik. Hiçbir işareti olmayan 11 haneli bir tam sayı TCKN sağlamasını tutuyorsa kimlik sayılıp maskelenebilir (aşağıda "Etiketsiz TCKN") | olduğu gibi |
| Karşı taraf, tedarikçi, müşteri adı (defterde olan) | gitmez | yer tutucu (`[[CP_7KQ_3]]`) | olduğu gibi |
| Okunan belgede **ilk kez geçen** ad (henüz defterde yok) | gitmez | **olduğu gibi gider** | olduğu gibi |
| Şirketin kendi adı ve unvanı | gitmez | yer tutucu (`[[CO_7KQ_1]]`) | olduğu gibi |
| Üye ve mali müşavir adı (ad ya da soyad tek başına da) | gitmez | yer tutucu (`[[PER_7KQ_2]]`) | olduğu gibi |
| IBAN, TCKN, VKN, kart, telefon, e-posta, plaka, "Hesap No" — **kanıtla** (etiket ya da şaşmaz biçim) | gitmez | yer tutucu | olduğu gibi |
| Etiketsiz TCKN (11 hane, iki kontrol basamağı tutuyor, tutar/tarih/belge no değil) | gitmez | yer tutucu | olduğu gibi |
| Etiketsiz VKN, etiketsiz 16 haneli kart no, `+90`/boşluk olmadan yazılmış cep no, etiketsiz plaka | gitmez | **olduğu gibi gider** (sayı olduğu varsayılır) | olduğu gibi |
| İşlem açıklaması (serbest metin) | gitmez | **yalnızca yukarıdakiler değiştirilir; geri kalanı olduğu gibi** | olduğu gibi |
| Belge metni (yedek çıkarım yolu: ilk 8.000 karakter) | gitmez | aynı kısmi maskeleme | olduğu gibi |
| Sohbet sorusu ve geçmişi | gitmez | aynı kısmi maskeleme | olduğu gibi |
| Gömme parçaları (1.800 karakter) ve sorgular | gitmez (TF-IDF'e düşer) | kararlı yer tutucularla (aşağıda) | olduğu gibi |

## Neyi, nasıl buluyor

* **Önce sayılar korunur** (`figures.py`). Kimlik kalıpları çalışmadan önce metindeki her tutar (tr-TR `1.234.567,89`, en-US
  `1,234,567.89`, `41176993.01`, tablo ya da CSV hücresini açan eksi işaretli tam sayı (`| -10000000146 |`), para birimi, yüzde, tutar sözcüğü yanındaki tam sayı, **tutar
  adlı bir JSON / sözlük / `anahtar=değer` alanının değeri**), tarih (ayraçlı, ISO, gerçek bir güne denk gelen `20240315` / `15032024`),
  saat, THP hesap kodu (`120.01.001`) ve belge numarası (Fatura/Belge/Fiş No, Dekont, Ref, ETTN) **veri** olarak işaretlenir; hiçbir
  kimlik kalıbı bu karakterlere dokunamaz, etiketli olsa da. Tutar alanı sayılan anahtarlar, arka ucun modele gönderdiği alan adlarından
  derlenmiştir: `amount`, `amount_cents`, `tutar`, `toplam`, `toplam_borc`, `borç`, `alacak`, `bakiye`, `balance_cents`, `total`, `revenue`,
  `net_income`, `gelir_kurus`, `gider_kurus`, `fiyat`, `price`, `cost`, `kdv`, `vat`... (anahtar sözcüklerine bölünür: `amountCents`,
  `toplam_borc`); bir sözcüğü kimlik adıysa (`card`, `iban`, `tckn`, `no`, `number`, `id`...) tutar sayılmaz (`credit_card_number` bir
  karttır). Eksi işareti tek başına tutar kanıtı değildir: yalnız bir tablo/CSV hücresinin başında sayılır ve önünde kimlik
  etiketi ya da kimlik adlı bir anahtar varsa hiç sayılmaz (`TC -10000000146`, `Kimlik No:-10000000146`, `{"tckn": "-10000000146"}`,
  `Tel:-0532 123 45 67`, `Vergi No:-…` maskelenir: etiket kazanır; etiketle değer arasında `: = - –` ayırıcılarından üçe kadarı olabilir). Aynı kural
  para birimi için de geçerlidir: kimlik etiketinin hemen arkasındaki sayıdan **sonra** gelen para birimi (`TCKN 10000000146 USD−109,65`)
  o sayıyı tutar yapmaz; bir sonraki sayıya yapışık para birimi (`TL-974`, `%34`) de önceki sayının birimi sayılmaz.
  **Güvencenin tam sınırı:** tutar olduğunu gösteren bu işaretlerden biri ya da tarih biçimi olan sayı hiçbir zaman
  değiştirilmez. Bunların hiçbiri olmayan bir rakam dizisi (ör. `Açıklama: "10000000146"`, tutar adı taşımayan bir alan) yalnızca şu
  biçimlerde kimlik sayılabilir: ülke harfli IBAN, basılı kart gruplaması, `+90`/boşluklu telefon, iki TCKN kontrol basamağını tutan tek
  parça 11 hane ve defterin bildiği vergi numarası. 11 haneli bir tutar bu işaretlerin hiçbiri olmadan yazılırsa yüzde bir olasılıkla
  TCKN sanılıp maskelenir (model o tutarı görmez; geri çevirmede baytı baytına geri gelir).
* **Kimlikler yalnızca olumlu kanıtla** (`detectors.py`): kontrol basamağı olan türlerde sağlama **ve** biçim **ve** bağlam.
  IBAN: harf + kontrol basamağı + ülkenin tam uzunluğu + mod 97 (boşluk, tire, satır sonu, küçük harf tolere edilir); "TR"siz yazım
  yalnızca hemen önünde "IBAN" etiketiyle. Kart: Luhn + kart veren önek + ("Kart" etiketi ya da basılı 4-4-4-4 gruplama). TCKN/VKN:
  sağlama + etiket (TCKN, T.C. Kimlik No, VKN, Vergi No, JSON alan adları); kimlik etiketli bir TCKN gruplar hâlinde yazılmışsa da
  bulunur (`Kimlik: 100 000 001 46`; etiketsiz gruplu yazım bir sayı olarak kalır). Telefon: hiçbir tutarın sahip olmadığı biçim (`+90`/`0` ile
  başlayan, boşluk/tire/parantezli gruplar; **asla nokta**) ya da etiket (Tel, GSM, Cep). E-posta: Unicode yerel kısım ve alan adı (IDN).
  Plaka ve "Hesap No": kontrol basamağı olmadığı için yalnızca etiketle. Defterin bildiği vergi numarası, korunan bir sayı değilse etiketsiz de bulunur.
* **Etiketsiz TCKN (karar verildi):** 11 haneli, iki TCKN kontrol basamağı tutan ve `figures.py` tarafından tutar, tarih, saat, THP
  kodu ya da bilinen bir alandaki belge numarası olarak sınıflanmamış bir sayı etiketsiz de maskelenir. Bedeli ölçüldü: 200.000 satırlık
  bulanık testte (40.000'i JSON / sözlük / `anahtar=değer` biçiminde, tutar alanlarında bilerek TCKN sağlamasını tutan 11 haneli değerlerle)
  hiçbir tutar ve tarih değişmedi; 5 satırda (%0,0025) etiketsiz 11 haneli bir **referans** numarası da maskelendi ve geri çevirmede
  baytı baytına geri geldi (kullanıcıya gösterilen hiçbir rakam model metninden gelmez).
* **Kalıpla maskelenmeyenler (bilinçli olarak, doğruluk kapsama önce gelir):** etiketsiz VKN, etiketsiz 16 haneli kart
  numarası, `+90` ya da boşluk olmadan yazılmış cep numarası (`05321234567`), etiketsiz plaka. Aynı "orta kural" bunlara uygulansaydı,
  aynı 200.000 satırda korunmayan referans numaralarından şunlara dokunurdu: 10 haneli VKN sağlaması tutan **58**, Luhn ve kart öneki
  tutan 16 haneli **216**, `05` ile başlayan 11 haneli **8.511** referans. 10 ve 16 haneli diziler tutar ve referanslarla çok daha sık
  çakıştığı için bu değişiklikte uygulanmadı (ölçülmüş kalan risk). Bunlar serbest metinde olduğu gibi gider
  (kalan risk). Sebep: aynı biçim tutar ya da referans numarası olarak çok daha sık geçer; bir tutarı bozmak, maskelememekten kötüdür.
* **Defterin bildiği adlar** (`dictionary.py`, `names.py`): NER modeli yok. Şirketin kendi tablolarından kurulur: şirket adı ve
  unvanı, işlem tedarikçisi ve karşı tarafı, ana defter, açık kalemler, ilişkili taraflar, karşı taraf takma adları, kategori
  kuralı tedarikçileri, üyeler ve mali müşavir. Eşleşme **sözcük dizisi** üzerindendir: büyük/küçük harf ve aksan duyarsız (Türkçe
  `İ/ı/I/i` önce katlanır), sözcükler arasında istenen kadar boşluk, satır sonu ya da sıfır genişlikli karakter, satır sonunda tireyle
  bölünmüş sözcük (`Iş-` / `ık Gıda`), Latin harfine benzeyen Kiril ya da Yunan harfi (`Аhmet`'teki Kiril `А`; yalnızca başka Latin dışı
  harf taşımayan sözcükte, gerçek Rusça/Yunanca sözcük kendi harfleriyle kalır). Bu son ikisi **yalnızca eşleştirme içindir**: giden metin
  yeniden yazılmaz, bulunan ad özgün karakterleri ve konumlarıyla yer tutucuya çevrilir, geri çevirmede baytı baytına geri gelir. Son sözcüğe kesme
  işaretli ya da işaretsiz Türkçe ek ("Yılmazın", "Işık Gıdaya", "Lojistiğe"; ek grameri `suffixes.py`'de sınırlı bir listedir, "her şey" değil),
  "A.Ş./Ltd. Şti./San. ve Tic." isteğe bağlı. Kişinin adı ya da soyadı **tek başına** da bulunur; şirketin ayırt edici ilk sözcüğü de.
  Aynı zamanda sıradan bir sözcük olan tek sözcük ("Güneş", "Deniz", "Demir": `common_words.py`) yalnızca ad gibi okunduğunda
  maskelenir: büyük harfle ve cümle başında değilken, ya da kesme işaretli ekle ("Güneş'e"). Çok sözcüklü ad her zaman maskelenir.
  **Ölçüm** (sentetik Türkçe finans metni, tohum 7, 5.000 sıradan + 5.000 adlı cümle): sıradan sözcüğün yanlışlıkla maskelenmesi
  **%0,0**; adın kaçırılması **%8,7** (tire ve benzer harf eklemelerinden sonra yeniden ölçüldü: değişmedi; bu sayıları
  `test_llm_egress_doc_claims.py` her koşuda yeniden ölçer ve bu satırla karşılaştırır). Kaçırılanların hepsi, sıradan sözcükle başlayan bir adın **ilk sözcüğünün tek başına**
  (ya da banka alanında kesilmiş hâlinin) cümle/satır başında geçtiği durumlardır, ör. "Güneş ile toplantı yapıldı", "DENIZ HAVALE";
  adın tamamı satır başında da maskelenir (bağımsız inceleme: 378 satırın 0'ı kaçtı). Test sınırları: ≤%1 ve ≤%25.
  Sıradan sözcük listesi (`common_words.py`) elle derlenmiştir ve satır satır gözden geçirilebilir: hem TDK Güncel Türkçe Sözlük'te
  sıradan ad/sıfat olarak geçen hem de yaygın bir Türkçe ad veya soyad olan sözcükler (Güneş, Deniz, Demir, Yıldız, Kaya, Çelik ...) ve
  şirket adında tek başına duran sektör sözcükleri (Ticaret, Gıda, Lojistik ...). Hiçbir test verisi listeyi belirlemez; testlerde
  sızıntı vakaları uydurma, sözlükte olmayan adlarla (Karvesta, Velorin, Zemtrak) yazılır.
  Eşleştirici sözcük başına bir karma araması yapar: 5.000 adlık sözlükle 8.000 karakter ≈0,03 sn, 100.000 karakter ≈0,35 sn
  (kötü niyetli girdide de doğrusal; `test_llm_egress_names.py`).
  Her kaynak 5.000 ayrık değerle sınırlıdır; sınır aşılırsa ekran ve denetim satırı bunu söyler (sınırın ötesindeki adlar maskelenmez).
* **Yer tutucular** yalnızca ASCII'dir (JSON kaçışında ve sözcüklere bölünmede değişmez): `[[CP_7KQ_3]]` = tür, **çağrı başına**
  rastgele bir ek (nonce), varlık numarası. Anahtar **özgün metnin birebir kendisidir**: iki farklı özgün metin asla aynı yer
  tutucuyu paylaşmaz; aynı varlığın iki yazımı aynı numarayı farklı harfle alır (`[[CP_7KQ_3]]`, `[[CP_7KQ_3b]]`), model bunların tek
  taraf olduğunu görür. Maskeli istemin sistem kısmına yer tutucuların ne olduğunu ve aynen yazılacağını söyleyen bir not eklenir.
* **Yanıt geri çevrilir** (saklanmadan ve gösterilmeden önce; akışta bölünmüş yer tutucular bütünlenene kadar tutulur), **baytı baytına
  özgün yazımıyla**. Model çıktısı **yapılandırılmış veri** olarak kullanılıyorsa (JSON, yapılandırılmış şema) önce **ayrıştırılır**, sonra
  ayrıştırılmış metin değerleri geri çevrilir (tırnak ya da ters bölü içeren bir ad JSON'u bozamaz). Bu çağrıda verilmemiş (uydurulmuş,
  başka çağrıdan, bozulmuş) bir yer tutucu: anlatıda `[bilinmeyen taraf]` (`[bilinmeyen değer]`) olarak görünür; deftere gidecek veride
  (belge okuma, `data_ingestion`) o alan **boş** sayılır, satır "okunamadı" olarak incelemeye düşer; yer tutucu metni asla deftere yazılmaz.
  Model köşeli parantezleri atarsa (`PER_7KQ_1`, `[PER_7KQ_1`) ve belirteç **bu çağrının ekini** (nonce) taşıyorsa bu da yer
  tutucu sayılır: verilmişse geri çevrilir, verilmemişse köşeli parantezli bilinmeyen yer tutucuyla aynı biçimde işaretlenir
  (deftere gidecek alanda boş, anlatıda `[bilinmeyen ...]`). Başka bir ek taşıyan parantezsiz, yer tutucuya benzeyen metin
  (`CO_A12_3`, `ACCT_TRY_100`, `PLATE_34A_1234` gibi gerçek kodlar) bizim değildir, hiçbir şey taşımaz ve **olduğu gibi kalır**.

### Gömme: neden kararlı takma adlar

İndeks zamanı ile sorgu zamanı aynı adı aynı belirteçle yazmazsa kosinüs benzerliği bozulur. İstek başına numaralar bunu bozardı. Bu
yüzden gömme yolunda yer tutucu, (şirket, tür, değer) üzerinden **sunucu sırrıyla anahtarlanmış bir özetten** türetilir
(`[[CP_a1b2c3d4]]`): aynı şirkette aynı ad her zaman aynı belirteçtir, başka şirkette farklıdır, sağlayıcı tahmin ettiği bir adı
özetleyerek geri çeviremez. Saklanan satır `<model>+pseud2.<anahtar sürümü>` etiketiyle yazılır (anahtar sürümü, sunucu sırrının
kısa bir parmak izidir: `BACKEND_SECRET_KEY` değişirse etiket de değişir); sorgu yalnızca **kendi etiketindeki** satırları arar, böylece ham
metinden, başka bir kipte ya da eski bir anahtarla hesaplanmış vektörler asla karıştırılmaz. Bu durum sessiz değildir: şirketin ekranı
"N belge parçası maskeli modda yeniden dizinlenmeyi bekliyor" der, işletmeci `/ready` ayrıntısında toplamı görür. Bakım işi
(`run_rag_backfill_maintenance`, cron; `services/rag_reindex.py`) bu satırları sınırlı partilerle (çalışma başına en çok 200, şirket başına 50,
şirket başına tek çağrı), tekrar edilebilir ve kaldığı yerden devam ederek, geçidin içinden (kip, maskeleme, ret ve denetim satırı geçerli)
yeniden gömer. `off` kipinde yeniden gömme yapılmaz. Ham gömülmüş eski metin sağlayıcının tarafında kalır. Not: bugün üretimdeki kanıt arama
(`retrieve_evidence`) TF-IDF ile sıralar; vektörleri yalnızca henüz bağlanmamış `EmbeddingRagRetriever` okur. Kararlı belirteç, aynı varlığın
şirket içinde tekrar geçtiğini sağlayıcıya gösterir (adı değil, tekrarı).

## Kapalı kalarak başarısız olma (fail closed)

Maskeli kipte geçit şirketi kendisi bulur: çağrıyı yapan kod `org_id` verdiyse o, yoksa isteğin (`get_current_user`, WebSocket) ya da
işin (`_records_run`, `run_ceo_analysis`, onay sonrası `devam_et`, `run_semantic_rebuild`) kurduğu şirket bağlamı. Şirket bilinmiyorsa ya da
isim sözlüğünün bir kaynağı okunamazsa **o çağrı yapılmaz**: arayan, `off` kipindeki gibi dürüst "yapay zekâ adımı yapılamadı" sonucunu ve
deterministik yolu alır (REST'te 503 `llm_egress_refused` ve neden; akışta açık bir ileti), `llm_call_logs` satırı nedenle yazılır
(`error = egress_refused:no_organisation_context` ya da `dictionary_unavailable`), sahibin ekranı 30 günlük ret sayısını nedenleriyle
gösterir, işletmeciye uyarı e-postası gider (`ops_watch`, 24 saatte bir kez) ve `/ready` ayrıntısında süreç başından beri sayı görünür.
Şirket bağlamı olmadan çalışabilecek sistem işleri için açık bir izin listesi vardır (`llm_egress/system_calls.py`, her satır gerekçeli):
**bugün boştur**, çünkü incelenen 49 çağrı yerinin hiçbiri şirketsiz ve kiracı verisi taşımadan çalışmıyor (sabah özeti, gömme ve
yeniden dizinleme şirket başına çalışır ve şirketi açıkça verir).

## İzleme (LangSmith / LangGraph)

İzleme açılırsa her düğümün ve model çağrısının girdisi/çıktısı (ham durum dahil) üçüncü tarafa gidebilirdi; geçidin dışında kalırdı.
Bu yüzden: açık ve belgelenmiş bir ayar olmadan kapalıdır (`LANGSMITH_ENABLED`; PR #157 ile ayrıca onay metni ve başıboş
`LANGCHAIN_TRACING_V2` kilidi gelir); açıkken de **hiçbir yük gitmez**: `llm_egress/tracing.py` süreç başında `LANGSMITH_HIDE_INPUTS` ve
`LANGSMITH_HIDE_OUTPUTS`'u (ve `LANGCHAIN_` yazımlarını) her durumda `true` yapar; izde yalnızca adım adları, süreler, belirteç sayıları ve
hatalar kalır. Üretimde açıksa başlangıç denetimi uyarır (`langsmith_tracing_on`). AST testi, izleme anahtarlarına telemetri dışında
dokunan kodu reddeder.

## Denetim kaydı (yük yok)

Her mantıksal çağrı için `llm_call_logs` satırı: şirket, amaç (`task_type`: ajan/görev), kip, yer tutucu türü başına değiştirme
sayısı (`replaced.counts`), uyarı bayrakları (`dictionary_truncated`, `unresolved_placeholder`, `system_call_patterns_only`),
gönderilen bayt (tüm denemeler); reddedilen çağrılar için `error = egress_refused:<neden>` ve sıfır bayt. Başarısız bir çağrıda `error`
yalnızca hatanın **türünü ve kısa bir kodu** taşır (`TimeoutError:timeout`, `APIStatusError:http_429`, `...:provider_rejected_400`,
`RuntimeError:failed`); hata **iletisi saklanmaz**, çünkü sağlayıcının ya da doğrulayıcının iletisi model çıktısından veya bizim
girdimizden alıntı yapabilir. Kayıt fonksiyonu da bu biçime uymayan bir metnin baştaki tür adı dışındaki kısmını atar. İstem, yanıt, ad ya da sayı **hiçbir yerde saklanmaz**. Ekran, son 30 günün çağrı ve bayt sayısını
yalnızca sayı olarak gösterir. Geçiş: `079_llm_egress_audit` (3 sütun `llm_call_logs`'a, 1 sütun `organizations`'a).

## `off` kipinde ne kaybedilir

Rakamlar, raporlar, çalışma sermayesi/pist, kural tabanlı metinler ve belge okuma (banka ekstresi, CSV, e-Fatura ayrıştırıcıları) aynen çalışır.
Kaybedilenler: sohbet ve doğal dil sorgusu (503 "kapalı" yanıtı; WebSocket'te "kapalı" iletisi), model anlatıları (şablon metin veya
"açıklama yok, rakamlar korunuyor"), ayrıştırıcıların tanımadığı belgelerin yapay zekâyla okunması ("Yapay zekâ adımı atlandı" ve inceleme
bekler), THP hesap tahmini (varsayılan hesap), anomali açıklaması, belge anlamsal araması (TF-IDF'e düşer; kalite biraz düşer).

## Kalan risk (düz sözle)

Bu bölüm, maskeli kipte (`masked`) bile sağlayıcıya neyin gidebileceğini anlatır. Burada yazan her sayı ve her davranış testlerle
ölçülmüştür (en altta hangi dosya). Ölçülmeyen bir konuda güvence verilmez.

**1. Maskeleme bir güvence değildir, bir azaltmadır.** Sistem kişisel veriyi iki yolla bulur: biçimi belli kimlik numaraları (IBAN,
TCKN, kart, telefon, e-posta...) ve şirketin kendi kayıtlarında zaten bulunan adlar. Bu ikisinin dışında kalan kişisel veri, metinde nasıl
yazılmışsa öyle gider. Bir yapay zekâ ya da ad tanıma modeli kullanılmaz; "metindeki her adı bul" diye bir işlev yoktur.

**2. Okunan belgede ilk kez geçen adlar olduğu gibi gider.** Bir fatura, ekstre ya da sözleşme okunurken, o belgede geçen ama şirketin
kayıtlarında henüz bulunmayan bir kişi ya da firma adı **maskelenmez**. Belge okumanın en büyük veri akışı budur ve en az maskelenen kısmıdır.
Aynı şekilde: yalnızca serbest bir notta geçen kişi, kayıtlarda farklı yazılmış bir ad, yazım hatası, takma ad, "Ahmet Bey" gibi
hitaplar, adres, pasaport ya da başka ülkelerin kimlik numaraları, görüntüdeki metin.

**3. Kayıtlarda bulunan adlar da bazen kaçar; ölçülen oran %8,7.** Sentetik Türkçe finans metninde (5.000 adlı cümle) kayıtlı bir adın
gönderilen metinde kalma oranı %8,7'dir; sıradan bir sözcüğün yanlışlıkla maskelenme oranı %0,0'dır. Kaçanlar, sıradan bir sözcükle
başlayan bir adın ilk sözcüğünün tek başına geçtiği durumlardır ("Güneş ile toplantı yapıldı", "DENIZ HAVALE"). Bu oran gerçek
müşteri metninde ölçülmemiştir; gerçek metinde farklı olabilir.

**4. Bilinçli olarak maskelenmeyen kimlik biçimleri.** Aşağıdakiler, tutar ve referans numaralarıyla çok sık karıştığı için kalıpla
maskelenmez ve olduğu gibi gider (bir tutarı bozmak, onu maskelememekten kötü sayıldı; sayılar yukarıda "Kalıpla maskelenmeyenler"de):
* etiketsiz vergi kimlik numarası (VKN): önünde "VKN" ya da "Vergi No" yazmayan 10 haneli sayı;
* etiketsiz 16 haneli kart numarası: önünde "Kart" yazmayan ve basılı 4-4-4-4 gruplamasıyla yazılmamış;
* araç plakası: önünde "Plaka" ya da "Araç" yazmıyorsa;
* cep telefonu: `+90` öneki ya da gruplar arası boşluk/tire olmadan yazılmışsa (`05321234567`, `5321234567`) ve noktalı yazımlar
  (`0532.123.45.67`), önünde "Tel/GSM/Cep" etiketi yoksa;
* etiketsiz yazılmış bir TCKN ise maskelenir (11 hane, iki kontrol basamağı tutuyor); ama boşluklarla gruplara bölünmüşse yalnızca
  önünde kimlik etiketi ("TC", "Kimlik", "TCKN") varken bulunur.

**5. Her zaman gidenler.** Tutarlar, tarihler, para birimleri, oranlar ve **defterin yapısı** (kaç işlem, hangi aylar, hangi hesaplar ve
kategoriler, hangi tutarın kime ait bir yer tutucuyla eşleştiği) maskeli kipte de olduğu gibi gider. Sağlayıcı bir şirketin adını
görmeden de onun finansal resmini görür.

**6. Gömmeler (embedding).** Maskeli kipte gömmeye giden metinde adlar, şirkete özgü ve **değişmeyen** belirteçlerle değiştirilir. Bu
belirteç adı göstermez, ama aynı adın aynı şirketin farklı belgelerinde tekrar geçtiğini sağlayıcıya gösterir. Bu değişiklikten **önce**
maskesiz gömülmüş metin, sağlayıcıya o zaman gönderilmiştir; bizim tarafta yeniden dizinlemek o kopyayı sağlayıcıdan geri almaz.

**7. Sağlayıcının tuttuğu veri bu çalışmanın dışındadır.** Sağlayıcının istekleri ne kadar süre sakladığı, kendi eğitiminde kullanıp
kullanmadığı ya da nerede işlediği sözleşme ve sağlayıcı seçimi konusudur; bu kod onu ne denetler ne de doğrular. Yer tutucular
sağlayıcıya giden kişisel veriyi azaltır, sağlayıcının elindekini silmez.

**8. Ham kip (`raw`) her şeyi gönderir.** Şirket ham kipi seçerse (yalnızca işletmeci izin verdiyse mümkündür) hiçbir maskeleme yapılmaz:
adlar, IBAN'lar, kimlik numaraları, belge metni olduğu gibi gider. Bu bir geri düşme değil, açık ve kayda geçen bir seçimdir.

**9. Diğer bilinen sınırlar.**
* Reddedilen ya da `off` kipindeki anlatılar şablon metne düşer ve metnin başında bunu söyler ("Yapay zekâ adımı atlandı ..."); ajan
  özet düğümleri (`node_*_summary`) bu notu henüz taşımaz.
* Belge okumada iki geçişli bir yol (aynı belgede ayrıştırıcıların bulduğu adları yapay zekâ adımından önce listeye eklemek) düşünüldü,
  yapılmadı: yapay zekâ adımı yalnızca hiçbir ayrıştırıcı belgeyi tanımadığında çalışır, o anda eklenecek ad yoktur.
* Bir yer tutucu, adın anlamına dayanan çıkarımlarda yanıtın kalitesini biraz değiştirebilir.

## Hangi dosya neyi sınar

`test_llm_egress_fidelity.py` (200.000 rakam/tarih/referans satırında sıfır değişiklik, 60.000 karışık satırda her rakam aynı ve geri çevirme
baytı baytına; incelemenin bulduğu bozuk biçimler sabit vaka olarak), `test_llm_egress_names.py` (incelemenin sızdırdığı ad, IBAN ve e-posta
yazımlarının hepsi, sıradan sözcük ölçümü, büyük sözlükte süre), `test_llm_egress_pseudonymizer.py` (kanıt kuralları, Türkçe harfler, birebir geri
çevirme, uydurma yer tutucu, akış, `repr`/pickle eşlemeyi göstermez), `test_llm_egress_gateway.py` (maskeli/kapalı/ham, JSON önce ayrıştırılır,
yapılandırılmış çıktı, akış, gömme, ret, denetim satırı, ham = master ile baytı baytına aynı), `test_llm_egress_matrix.py` (49 çağrı yeri, gerçek
giriş noktalarından; bağlamsız ve sözlük okunamaz durumları), `test_llm_egress_choke_point.py` (kimse kendi istemcisini kuramaz: dinamik içe aktarma,
istemci fabrikası, ortam değişkeni yazımı, izleme anahtarları dahil), `test_llm_egress_provider_helpers.py` (kimse geçidin istemcisini ödünç
alamaz; inceleme mutasyonu ve 20 benzeri geçici dosyalarla), `test_llm_egress_doc_claims.py` (bu belgedeki ölçüm sayıları ve "maskelenmez"
listesi kodla karşılaştırılır), `test_llm_audit_error.py` (denetim kaydında hata iletisi yok), `test_llm_egress_tracing.py` (izde yük yok),
`test_llm_egress_api.py` (ekran ve karar kaydı).
