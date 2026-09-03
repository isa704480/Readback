/* Oʻzbekcha — LATIN script.
 *
 * The turned comma in oʻ and gʻ is U+02BB MODIFIER LETTER TURNED COMMA, not an
 * ASCII apostrophe (U+0027), not a right single quote (U+2019) and not a
 * backtick. Getting this wrong is the standard way Uzbek Latin ships broken:
 * it still renders, so nobody notices, but "oʻzgartiradi" written with U+2019
 * is a different word to a screen reader and to search. Archivo's `latin`
 * subset declares U+02BB-02BC, so this character needs no extra font request --
 * measured against the Google Fonts CSS, not assumed.
 *
 * Checked against en.ts at compile time: missing key, unknown key and
 * placeholder mismatch are all build errors. See types.ts.
 */

import type { Messages } from './en';
import type { en } from './en';
import type { Translated } from './types';

const catalog = {
  // ------------------------------------------------------------ languages --

  // Endonyms: identical in every catalog, on purpose. See en.ts.
  'lang.name.en': 'English',
  'lang.name.uz': 'Oʻzbekcha',
  'lang.name.ru': 'Русский',

  'lang.switcher.label': 'Interfeys tili',

  'lang.switcher.note':
    'Bu faqat interfeys tilini oʻzgartiradi. Readback qoʻngʻiroqni ingliz tilida tinglaydi va savolini ingliz tilida beradi.',

  'lang.notice.short': 'Faqat interfeys — agent ingliz tilida tinglaydi.',

  // ---------------------------------------------------------------- shell --

  'app.skipToContent': 'Asosiy mazmunga oʻtish',

  // --------------------------------------------------------------- topbar --

  'topbar.nav.label': 'Asosiy',
  'topbar.signedIn': 'Tizimga kirilgan',
  'topbar.account': 'Hisob',
  'topbar.signOut': 'Chiqish',
  'topbar.logIn': 'Kirish',
  'topbar.getKey': 'Kalit olish',

  // ----------------------------------------------------------- navigation --

  /* 'nav.record' — "Yozuv", the same word as 'record.eyebrow' below, because
   * the rail's label and the screen's own eyebrow name one thing. */
  'nav.sidebar.label': 'Boʻlimlar',
  'nav.live': 'Jonli',
  'nav.record': 'Yozuv',
  'nav.sessions': 'Seanslar',
  'nav.formats': 'Formatlar',
  'nav.demo': 'Demo',

  'nav.record.silent': '{total} identifikatordan {silent} tasi soʻramasdan yozilgan',

  'route.pending.eyebrow': 'Hali qurilmagan',
  'route.pending.live.title': 'Jonli qoʻngʻiroq koʻrinishi hali qurilmagan.',
  'route.pending.live.body':
    'Bu yerda qoʻngʻiroq davom etayotganda identifikator belgima-belgi toʻlib boradi. Uning oʻrniga bu yerda hech narsa koʻrsatilmaydi, chunki koʻrsatiladigan jonli yozuv yoʻq: boʻlmayotgan qoʻngʻiroqning jonlantirilgan maketi — bu mahsulot qilmasligi kerak boʻlgan yagona narsa.',
  'route.pending.sessions.title': 'Seanslar roʻyxati hali qurilmagan.',
  'route.pending.sessions.body':
    'Seanslar allaqachon yozuvda bor — oʻzlari bergan identifikatorlar ostida guruhlangan. Oʻz filtrlari va oʻz sana oraligʻiga ega alohida roʻyxat esa hali yoʻq.',
  'route.pending.formats.title': 'Formatlar maʼlumotnomasi hali qurilmagan.',
  'route.pending.formats.body':
    'Tashkilotingizda qaysi formatlar yoqilgani va har biri nimani tekshirishi bugun hisob ekranida turibdi. Har bir nazorat raqami qanday hisoblanishini tushuntiradigan maʼlumotnoma esa hali yoʻq.',
  'route.pending.demo.title': 'Demo ekrani hali qurilmagan.',
  'route.pending.demo.body':
    'Demoning oʻzi haqiqiy va u ishlaydi: yozuvning boʻsh holati bitta yozib olingan fixturani boshidan oxirigacha ijro etadi va uni fixtura deb belgilaydi. Qaysi fixturani ishga tushirishni tanlaydigan alohida ekran esa hali yoʻq.',
  'route.pending.toRecord': 'Yozuvga oʻtish',

  // ------------------------------------------------------- capture states --

  'capture.state.heard': 'Eshitildi, hali tasdiqlanmadi',
  'capture.state.repaired': 'Sokin tuzatildi',
  'capture.state.asking': 'Sizdan bitta narsa kerak',
  'capture.state.settled': 'Tasdiqlandi',
  'capture.state.flagged': 'Belgilandi',

  // ----------------------------------------------------------------- rack --

  'rack.empty': 'Hozircha hech narsa yoʻq. Kimdir kodni oʻqishi bilan raf toʻla boshlaydi.',
  'rack.asked.none': 'hech narsa soʻralmadi',
  'rack.asked.count': '{n}× soʻraldi',

  'rack.readout.position': '{n}-oʻrin',
  'rack.readout.blank': 'boʻsh',
  'rack.readout.repaired': '{position} {heard} deb eshitildi, {written} deb yozildi.',
  'rack.readout.asked': '{position} — soʻroq ostidagi belgi.',
  'rack.readout.locked': '{position} hisoblab chiqarildi, eshitilmadi.',

  /* Uzbek does not inflect the noun after a numeral -- "1 savol", "5 savol".
   * All four CLDR categories therefore carry the same form, which is the
   * correct Uzbek, not an untranslated placeholder. */
  'rack.readout.questions.one': '{n} savol.',
  'rack.readout.questions.few': '{n} savol.',
  'rack.readout.questions.many': '{n} savol.',
  'rack.readout.questions.other': '{n} savol.',

  // --------------------------------------------------------------- legend --

  'rack.legend.empty.label': 'Boʻsh',
  'rack.legend.empty.note': 'Format bu oʻrin borligini biladi. Uni hali hech kim aytmadi.',
  'rack.legend.provisional.note': 'Tanigich bergan natija; hali bekor qilinishi mumkin.',
  'rack.legend.settled.note': 'Arifmetika bilan tasdiqlandi va yozib olindi.',
  'rack.legend.repaired.note': 'Format mikrofonni bekor qildi. Ikkala belgi ham qatorda qoladi.',
  'rack.legend.asked.note': 'Suhbatni boʻlishga arziydigan yagona belgi.',
  'rack.legend.locked.label': 'Format tomonidan qulflangan',
  'rack.legend.locked.note': 'Oldingi oʻrinlardan hisoblanadi. Ovoz uni oʻzgartira olmaydi.',
  // -------------------------------------------------------------- landing --

  /* Tutuq belgisi note: this block also uses U+02BC MODIFIER LETTER APOSTROPHE
   * (maʼlumot, nomaʼlum). That is the correct Uzbek Latin character for the
   * glottal stop, and it is a different character from the U+02BB turned comma
   * in oʻ and gʻ. Neither is an ASCII apostrophe. */

  /* "allowed to be" has no clean Uzbek deontic that does not read as a legal
   * entitlement, so this lands as "what the answer can be". The contrast the
   * headline exists for -- eshitmaydi (does not hear) against biladi (knows) --
   * is preserved, which is the part that carries the pitch. */
  'landing.hero.title.a': 'U yaxshiroq eshitmaydi.',
  'landing.hero.title.b': 'U javob qanday boʻlishi mumkinligini biladi.',
  'landing.hero.lede':
    'Readback qoʻngʻiroq fonida tinglaydi va maʼlumot raqamlarini yozib boradi: konteyner raqamlari, IBAN, VIN, bemor raqamlari, karta raqamlari. U suhbatni transkripsiya qilmaydi va uni qisqacha bayon ham qilmaydi. Koʻpincha notoʻgʻri eshitganini indamay tuzatadi. Tuzata olmasa — bir marta boʻladi, bitta belgi haqida soʻraydi va yana jim boʻladi.',
  'landing.hero.scope':
    'Readback qoʻngʻiroqni ingliz tilida tinglaydi va yagona savolini ingliz tilida beradi. Til faqat interfeysda oʻzgaradi.',

  'landing.rack.title': 'Yozuvlar rafi',

  /* Uzbek does not inflect a noun after a numeral: "1 ta yozuv", "4 ta yozuv".
   * All four CLDR categories therefore carry the same form. */
  'landing.rack.meta.captures.one': '{n} ta yozuv',
  'landing.rack.meta.captures.few': '{n} ta yozuv',
  'landing.rack.meta.captures.many': '{n} ta yozuv',
  'landing.rack.meta.captures.other': '{n} ta yozuv',
  'landing.rack.meta.questions.one': '{n} ta savol',
  'landing.rack.meta.questions.few': '{n} ta savol',
  'landing.rack.meta.questions.many': '{n} ta savol',
  'landing.rack.meta.questions.other': '{n} ta savol',

  'landing.row.repaired.note':
    '{position}-oʻrin · eshitildi {heard} · yozildi {written} · {check} nazorat raqami mos keladi',
  'landing.row.asking.note': 'oʻn ikkita koʻr juftlikdan biri',

  /* The quoted fragment stays in English and is named as English, because it is
   * what the agent actually says on the call. */
  'landing.row.asking.question':
    '{position}-oʻrin. Agent ingliz tilida soʻraydi: “{a} for {aWord}, or {b} for {bWord}?” Ikkalasi ham {check} nazorat raqamini qoldiradi, shuning uchun arifmetika hech qaysisiga qarshi chiqmaydi.',

  'landing.row.arriving.digits.one': 'yana {n} ta raqam kutilmoqda',
  'landing.row.arriving.digits.few': 'yana {n} ta raqam kutilmoqda',
  'landing.row.arriving.digits.many': 'yana {n} ta raqam kutilmoqda',
  'landing.row.arriving.digits.other': 'yana {n} ta raqam kutilmoqda',

  'landing.row.settled.note':
    '{check} nazorat raqami mos keladi · tuzatadigan narsa yoʻq',

  // ------------------------------------------------------ landing: beats --

  'landing.beats.title': 'Uchta qadam, va mahsulot — oʻrtadagisi',

  'landing.beat1.title': 'U notoʻgʻri eshitadi.',
  /* "inglizcha" is added on purpose: five/nine and fifteen/fifty are English
   * words confused by an English recogniser. Uzbek besh and toʻqqiz are not
   * confusable, so a faithful translation would be a fabricated claim. */
  'landing.beat1.body':
    'Shovqinda inglizcha five va nine — bir xil tovush. M va N, S va F, fifteen va fifty ham shunday. Hech qanday akustik modellashtirish buni hal qilmaydi, chunki maʼlumot audioning oʻzida yoʻq.',
  'landing.beat1.caption': 'Yomon aloqada, har qanday talaffuzda farqlab boʻlmaydi.',
  'landing.confusable.soundsLike': '{a} va {b} bir xil eshitiladi',

  'landing.beat2.title': 'Format javobni cheklaydi.',
  'landing.beat2.body':
    'Konteyner raqami — oʻn bitta erkin belgi emas. Bu oʻnta belgi va ulardan hisoblangan nazorat raqami: oxirgi katakni mikrofon emas, arifmetika toʻldiradi. IBAN mod-97 ni olib yuradi. Karta Luhn ni olib yuradi. Format mikrofon bilmagan narsalarni biladi.',
  'landing.beat2.stripLabel':
    'ISO 6346. {spoken}, keyin {check} nazorat raqami — u oʻzidan oldingi oʻnta belgidan hisoblanadi.',
  'landing.beat2.caption':
    'Oxirgi katak qulflangan: audioni qanday oʻqish ham uni joyidan qimirlata olmaydi.',

  'landing.beat3.title': 'Odatda faqat bitta javob joiz.',
  'landing.beat3.body':
    'Tanigich {position}-oʻringa {heard} qoʻydi, gapirgan odam esa {check} nazorat raqamini aytdi. U yerda oʻnta belgi turishi mumkin edi. Ulardan faqat bittasi arifmetikani mos keltiradi — agent oʻshani indamay yozib qoʻyadi.',
  'landing.sweep.groupLabel': 'Har bir nomzod belgi beradigan nazorat raqami',
  'landing.sweep.caption':
    'Nomaʼlumi — {position}-oʻrin. Oʻsha yerda tura oladigan har bir belgi uchun nazorat raqami mana bunday boʻladi:',
  'landing.sweep.stub.candidate': '{position}-oʻrin',
  'landing.sweep.stub.check': 'nazorat raqami',
  'landing.sweep.sr.heard': 'tanigich eshitgani',
  'landing.sweep.sr.legal': 'aytilganga mos keladigan yagona qiymat',
  'landing.beat3.caption':
    'Oʻntadan toʻqqiztasi aytilgan nazorat raqamiga zid. Oʻninchisi yoziladi.',

  // ------------------------------------------------------- landing: gain --

  'landing.gain.title':
    'Javobni cheklash tizim koʻtara oladigan xato darajasini oʻn besh barobar oshiradi.',
  'landing.gain.body.measured':
    'Sakkizta talaffuz va taxminan oʻn ikki million modellashtirilgan yozuvda oʻlchangan, yechuvchiga qaysi talaffuzni eshitayotgani hech qachon aytilmagan: ISO 6346 da {iso}×, IBAN da {iban}×. Talaffuzlar tanish xatosi boʻyicha koʻpi bilan {spread}× farq qiladi, {budget}× zaxira esa buni oʻn barobar ortigʻi bilan qoplaydi.',
  'landing.gain.body.noDetection':
    'Shuning uchun bu yerda talaffuz boʻyicha oʻqitish ham, talaffuzni aniqlash ham yoʻq. Qaysi talaffuzni tinglayotganingizni bilish ±{value} ga arziydi.',
  'landing.gain.ratio.unconstrained': 'cheklovsiz',
  'landing.gain.ratio.constrained': 'cheklov bilan',

  // ---------------------------------------------------- landing: silence --

  'landing.silence.title': 'Sukunat — mahsulotning oʻzi.',
  'landing.silence.body':
    'Akustik model aniqlikka hech narsa qoʻshmaydi. Nazorat yigʻindisi va ikkita savol baribir taxminan 100% beradi. Model aslida sotib oladigani — sukunat: ISO 6346 da {iso} punkt, NHS raqamlarida {nhs} punkt sokin tuzatish.',
  'landing.silence.pull':
    'Har bir raqamni qayta soʻraydigan agent — bu aynan oʻsha “harflab ayting”, Readback esa uni yoʻq qilish uchun bor.',

  // ------------------------------------------------- landing: blind pairs --

  'landing.blind.title': 'U koʻra olmaydigan oʻn ikkitasi',
  'landing.blind.body.math':
    'ISO 6346 {formula} yigʻindisini oladi, shuning uchun 11 modulida bir xil qiymatga ega ikkita belgi nazorat raqami uchun bitta belgidir. Akustik jadval boʻyicha oʻlchanganda, real notoʻgʻri eshitishlarning {share}% shu boʻshliqqa tushadi — oʻn ikkita maʼlum juftlikda.',
  'landing.blind.body.rest':
    'Va yana toʻqqiztasi. Agent arifmetika ularni koʻradi deb oʻzini tutish oʻrniga, har safar oʻn ikkitasining hammasi haqida soʻraydi. Bu yerdagi sukunat ishonch emas, arifmetikaning koʻrligi boʻlardi — shuning uchun sahifa yuqorisidagi rafda nazorat raqami mutlaqo joyida boʻlgan raqamning bitta belgisini kutayotgan qator turibdi.',
  'landing.blind.pair.chars': '{a} va {b}',
  'landing.blind.pair.math': '{first} va {second}. Ikkalasi ham ≡ {residue} (mod 11).',

  // ------------------------------------------------------ landing: close --

  'landing.close.title': 'Raf — butun interfeysning oʻzi.',
  'landing.close.body':
    'Oʻqiydigan transkript yoʻq, chunki suhbat hech qachon saqlanmaydi. Bahslashadigan ishonch bahosi yoʻq, chunki tizim shubhasini savol berib bildiradi. Qaytib keladigani — raqam va necha marta boʻlishga toʻgʻri kelgani.',
  // ------------------------------------------------------------- transport --

  /* Har bir ApiErrorKind uchun bitta gap, va turlar bir-biridan AJRATILGAN.
   * Har biri sababni ham, keyin nima qilish kerakligini ham aytadi. */
  'error.offline':
    'Readback xizmatiga ulanib boʻlmadi. Aloqani tekshiring va qayta urinib koʻring.',
  'error.timeout':
    'Readback xizmati vaqtida javob bermadi. U ishga tushayotgan boʻlishi mumkin — biroz kutib, qayta urinib koʻring.',
  'error.badRequest':
    'Bu maʼlumotlarning bir qismi qabul qilinmadi. Yuqoridagi maydonlarni toʻgʻrilang va qaytadan yuboring.',
  'error.unauthorized':
    'Bu e-pochta va parol hech qanday hisobga mos kelmadi. Ikkalasini tekshiring yoki hali hisobingiz boʻlmasa, kalit oling.',
  'error.notFound':
    'Bunday sahifa yoʻq. Sahifani qayta yuklang va agar takrorlansa, bizga xabar bering.',
  'error.conflict':
    'Bu e-pochta bilan hisob allaqachon mavjud. Uning oʻrniga tizimga kiring yoki boshqa manzil kiriting.',
  'error.rateLimited': 'Urinishlar juda koʻp boʻldi. Bir daqiqa kuting va qayta urinib koʻring.',
  'error.server':
    'Readback xizmatining oʻz tomonida muammo yuz berdi. Hech narsa saqlanmadi — ozdan keyin qayta urinib koʻring.',
  'error.malformed':
    'Readback xizmati bu sahifa oʻqiy olmaydigan javob qaytardi. Qayta urinib koʻring va agar takrorlansa, bizga xabar bering.',

  'error.rateLimited.wait': 'Urinishlar juda koʻp boʻldi. {when} qayta urinib koʻring.',
  'wait.moment': 'bir necha soniyadan keyin',
  'wait.aboutMinute': 'taxminan bir daqiqadan keyin',
  /* Oʻzbek tilida son oldidan kelgan ot turlanmaydi: 1 soniya, 5 soniya.
   * Shuning uchun CLDR ning toʻrt toifasi ham bir xil shaklni tashiydi. */
  'wait.seconds.one': 'taxminan {n} soniyadan keyin',
  'wait.seconds.few': 'taxminan {n} soniyadan keyin',
  'wait.seconds.many': 'taxminan {n} soniyadan keyin',
  'wait.seconds.other': 'taxminan {n} soniyadan keyin',
  'wait.minutes.one': 'taxminan {n} daqiqadan keyin',
  'wait.minutes.few': 'taxminan {n} daqiqadan keyin',
  'wait.minutes.many': 'taxminan {n} daqiqadan keyin',
  'wait.minutes.other': 'taxminan {n} daqiqadan keyin',

  // ------------------------------------------------------------ form parts --

  'field.required': '(majburiy)',
  'field.reveal.show': '{label}ni koʻrsatish',
  'field.reveal.hide': '{label}ni yashirish',
  'button.busy': 'Bajarilmoqda',

  // ----------------------------------------------------------------- auth --

  'auth.login.title': 'Kirish',
  'auth.login.blurb': 'Kompaniyangiz yozib olgan raqamlarga kiring.',
  'auth.login.submit': 'Kirish',
  'auth.login.busy': 'Tekshirilmoqda',
  'auth.login.footLead': 'Hali hisobingiz yoʻqmi?',
  'auth.login.footLink': 'Kalit olish',

  'auth.signup.title': 'Kalit olish',
  'auth.signup.blurb': 'Har bir kompaniyaga bitta hisob. Qolganlar unga taklif orqali qoʻshiladi.',
  'auth.signup.submit': 'Hisob yaratish',
  'auth.signup.busy': 'Yaratilmoqda',
  'auth.signup.footLead': 'Hisobingiz bormi?',
  'auth.signup.footLink': 'Kirish',

  'auth.field.name': 'Ismingiz',
  'auth.field.company': 'Kompaniya',
  'auth.field.email': 'Ish e-pochtangiz',
  'auth.field.password': 'Parol',

  'auth.error.name': 'Ismingizni kiriting.',
  'auth.error.company': 'Kompaniyangiz nomini kiriting.',
  'auth.error.email.empty': 'Ish e-pochtangizni kiriting.',
  'auth.error.email.shape':
    'Bu e-pochta manziliga oʻxshamaydi. Unda nom, @ belgisi va domen boʻlishi kerak, masalan maria@company.com.',
  'auth.error.password.choose': 'Parol tanlang.',
  'auth.error.password.enter': 'Parolingizni kiriting.',

  // ------------------------------------------------------------- password --

  /* QOIDA. Tarjima qilingandan keyin ham HAQIQAT boʻlib qolishi shart: kamida
   * oʻnta belgi va uchta turdan kamida bittadan. Uchinchi turi keng maʼnoda —
   * harf ham, raqam ham boʻlmagan har qanday belgi, jumladan boʻsh joy. Shuning
   * uchun "maxsus belgi" deyilgan, "tinish belgisi" emas. */
  'pw.rule': 'Kamida {min} ta belgi; ichida bitta harf, bitta raqam va bitta maxsus belgi.',
  'pw.class.letter': 'bitta harf',
  'pw.class.number': 'bitta raqam',
  'pw.class.symbol': 'bitta maxsus belgi',
  'pw.list.and': 'va',

  'pw.problem.shortCount': 'Kamida {min} ta belgi kerak. Bunisida {have} ta.',
  'pw.problem.add': '{missing} qoʻshing.',

  'pw.problem.short': 'Kamida {min} ta belgi kerak.',
  'pw.problem.long': '{max} ta belgidan oshmasin.',
  'pw.problem.include': 'Ichida {missing} boʻlsin.',
  'pw.problem.context.email': 'Parolga e-pochtangizni kiritmang.',
  'pw.problem.context.name': 'Parolga ismingizni kiritmang.',
  'pw.problem.context.company': 'Parolga kompaniyangiz nomini kiritmang.',
  'pw.problem.commonBolted':
    'Bu — juda keng tarqalgan parol, ustiga raqam yoki belgi qoʻshilgani xolos.',
  'pw.problem.commonPlain': 'Bu — eng koʻp ishlatiladigan parollardan biri.',
  'pw.problem.keyboardRun': 'Unda klaviaturadagi ketma-ket tugmalar qatori bor.',
  'pw.problem.repeats': 'Unda bitta belgi uch marta yoki koʻproq takrorlanadi.',
  'pw.problem.fewDistinct': 'Unda turli belgilar juda kam.',
  'pw.problem.wordNumberSymbol':
    'Soʻz-raqam-belgi tartibi — buzgʻunchi eng birinchi sinab koʻradigan naqsh.',
  'pw.suggestion.length':
    'Uzunlik zukkolikdan ustun — bir-biriga bogʻliq boʻlmagan toʻrtta soʻz, harflari almashtirilgan bitta soʻzdan kuchliroq.',
  'pw.suggestion.addMore': 'Bemalol kuchli boʻlishi uchun yana bir nechta belgi qoʻshing.',

  /* KUCH SOʻZLARI. Rang bu yerda tashuvchi emas — toʻrt holat rangi kulrangda
   * bir xil. Soʻz tashuvchi, shuning uchun toʻrt daraja toʻrt xil soʻz bilan
   * ataladi, sizib chiqish esa beshinchi, alohida hukm. */
  'pw.strength.idle': 'Parol kuchi',
  'pw.strength.weak': 'Zaif',
  'pw.strength.fair': 'Oʻrtacha',
  'pw.strength.good': 'Yaxshi',
  'pw.strength.strong': 'Kuchli',
  'pw.strength.breached': 'Sizib chiqqan',

  'pw.breach.count.one': 'Bu parol {n} ta maʼlum sizib chiqishda uchraydi.',
  'pw.breach.count.few': 'Bu parol {n} ta maʼlum sizib chiqishda uchraydi.',
  'pw.breach.count.many': 'Bu parol {n} ta maʼlum sizib chiqishda uchraydi.',
  'pw.breach.count.other': 'Bu parol {n} ta maʼlum sizib chiqishda uchraydi.',
  'pw.breach.advice': 'Buzgʻunchilar avvalo sizib chiqqan parollarni sinaydi — boshqasini tanlang.',
  'pw.breach.clean': 'Hech qanday maʼlum sizib chiqishda yoʻq.',
  'pw.breach.unchecked': 'Maʼlum sizib chiqishlar bilan solishtirilmadi — xizmat javob bermadi.',

  // -------------------------------------------------------- account: shell --

  'account.eyebrow': 'SOZLAMALAR',
  'account.title': 'Hisob',
  'account.org.unknown': 'Tashkilot nomaʼlum',
  'account.org.yours': 'tashkilotingiz',
  'account.loading.session': 'Seansingiz tekshirilmoqda',
  'account.loading.team': 'Jamoangiz yuklanmoqda',
  'account.loading.usage': 'Sarf yuklanmoqda',
  'account.unreachable':
    'Readback xizmatiga ulanib boʻlmadi. Quyidagilar — bu hisob haqida oxirgi maʼlum boʻlgan holat, hozirgi holati emas; bu yerda oʻzgartirganingiz serverga yetib bormaydi.',
  'account.refresh': 'Yangilash',
  'account.refreshing': 'Yangilanmoqda',
  'account.index.label': 'Hisob boʻlimlari',

  'account.profile.title': 'Profil va jamoa',
  'account.profile.lede':
    'Bu yerdagi hamma bir xil yozuvlarni koʻradi. Rollar bu ekrandagi sozlamalarni kim oʻzgartira olishini belgilaydi.',
  'account.formats.title': 'Formatlar',
  'account.formats.lede':
    'Readback qaysi identifikator turlarini tinglaydi. Shulardan biri oʻqib berilmaguncha agent jim turadi.',
  'account.vocab.title': 'Lugʻat toʻplami',
  'account.vocab.lede':
    'Format oldindan bila olmaydigan soʻzlar. Nazorat raqami belgilarni cheklaydi; Maersk soʻzi haqida esa hech narsa bilmaydi.',
  'account.consent.title': 'Rozilik',
  'account.consent.lede':
    'Readback jonli qoʻngʻiroqlar fonida tinglaydi. Bu boʻlim rasmiyatchilik emas va mahsulotning qolganidan oldin oʻqishga arziydigan qismi.',
  'account.usage.title': 'Sarf',
  'account.usage.lede':
    'Tarifga nisbatan tinglash soniyalari va bu ekran halol hisoblab bera oladigan qismi.',

  // ----------------------------------------------------- account: 01 team --

  'account.team.empty':
    'Koʻrsatadigan jamoa yoʻq. Hisobni oʻqib boʻlmadi, shuning uchun roʻyxatlanadigan odam yoʻq. Yuqoridagi Yangilash tugmasini bosing.',
  'account.team.you': 'SIZ',
  'account.team.invitedHere': 'FAQAT SHU YERDA',
  'account.team.roleColumn': 'ROL',
  'account.team.cannotRemoveSelf': 'Oʻzingizni oʻchira olmaysiz.',
  'account.team.remove': '{name}ni oʻchirish',
  'account.team.onlyYou':
    'Hozircha faqat siz. Bu qoʻngʻiroqlarni qabul qiladigan odamlarni taklif qiling, shunda yozuvlar bitta brauzerdan boshqa joyga ham tushadi.',

  'account.role.owner': 'Egasi',
  'account.role.owner.can': 'Hammasi, jumladan toʻlovlar va shu ekran.',
  'account.role.admin': 'Administrator',
  'account.role.admin.can': 'Shu ekran, jamoa va barcha yozuvlar.',
  'account.role.operator': 'Operator',
  'account.role.operator.can': 'Barcha yozuvlar. Formatlar, rozilik va jamoani oʻzgartira olmaydi.',

  'account.invite.title': 'Odam taklif qilish',
  'account.invite.name': 'Ism',
  'account.invite.nameHint': 'Ixtiyoriy. Boʻlmasa, taklif manzil boʻyicha roʻyxatlanadi.',
  'account.invite.email': 'E-pochta',
  'account.invite.role': 'Rol',
  'account.invite.submit': 'Roʻyxatga qoʻshish',
  'account.invite.duplicate': 'Bu manzildagi odam allaqachon jamoada.',

  'account.email.empty': 'E-pochta manzilini kiriting.',
  'account.email.space': 'E-pochta manzilida boʻsh joy boʻlmaydi.',
  'account.email.at': 'Bitta @ kerak va uning oldida nom boʻlishi shart.',
  'account.email.domain': '@ dan keyingi qism domenga oʻxshamaydi.',

  'account.pending.team':
    'Takliflar, rol oʻzgarishlari va oʻchirishlar shu brauzer ichida qoladi. Jamoa endpointlari paydo boʻlmaguncha hech narsa yuborilmaydi va saqlanmaydi:',

  // -------------------------------------------------- account: 02 formats --

  'account.formats.prose1':
    'Readback ostidagi tanigichdan yaxshiroq eshitmaydi. U qanday javob toʻgʻri boʻlishi mumkinligini biladi. Shuning uchun nazorat raqami mikrofondan muhimroq va shuning uchun quyidagi har bir qatorda arifmetikaning kuchi yozib qoʻyilgan.',
  'account.formats.prose2.lead':
    'Har bir qatordagi rang standartga qoʻyilgan baho emas. U agent sizni qanchalik tez-tez boʻlishini bashorat qiladi:',
  'account.formats.prose2.mid':
    'degani — arifmetika xato eshitishlarning koʻpini hech kimdan soʻramay yutadi;',
  'account.formats.prose2.tail':
    'degani — agent tez-tez gapiradi. Bular yozuv rafi ishlatadigan xuddi oʻsha ikki soʻz va xuddi oʻsha ikki rang.',

  'account.formats.shape': 'Koʻrinishi',
  'account.formats.length': 'Uzunligi',
  'account.formats.check': 'Nazorat raqami',
  'account.formats.onRecord': 'Yozuvlarda',
  'account.formats.noCheck': 'Yoʻq. Yechuvchi tekshiradigan hech narsa yoʻq.',
  'account.formats.notCounted': 'Sanalmadi, seanslar mavjud emas',
  'account.formats.noCaptures': 'Hali yozuv yoʻq',
  'account.formats.captures.one': '{n} ta yozuv',
  'account.formats.captures.few': '{n} ta yozuv',
  'account.formats.captures.many': '{n} ta yozuv',
  'account.formats.captures.other': '{n} ta yozuv',
  'account.formats.cannot': 'ARIFMETIKA NIMANI KOʻRA OLMAYDI',
  'account.formats.sensitive.before': 'Bu nimani anglatishini',
  'account.formats.sensitive.after': 'boʻlimidan koʻring.',
  'account.pending.formats':
    'Formatni yoqish yoki oʻchirish faqat shu brauzerga taʼsir qiladi; format endpointi paydo boʻlmaguncha qoʻngʻiroqlaringizdagi agent oʻzgarmaydi:',

  'account.format.iban.name': 'IBAN',
  'account.format.iban.length': '16 dan 34 tagacha belgi, har bir davlat uchun qatʼiy',
  'account.format.iban.check': 'Ikkita nazorat raqami, mod-97-10',
  'account.format.iban.strength':
    'Bu yerdagi eng kuchli arifmetika. Butun satr boʻylab ikkita nazorat raqami.',
  'account.format.iban.measured.1':
    'Xato budjeti: cheklanmaganda 0.0023, cheklanganda 0.0399 — 17.1x, oʻlchangan eng katta yutuq.',
  'account.format.iban.measured.2': 'Sinovdan oʻtgan sakkiz talaffuz orasidagi tarqoqlik: 1.14x.',
  'account.format.iban.note':
    'Davlat kodi arifmetika ishlashidan oldin uzunlikni belgilab qoʻyadi, shuning uchun tushib qolgan belgi nazorat yigʻindisi bilan emas, shakl bilan tutiladi. Tekshiruvchi oʻnta davlat uzunligini biladi; boshqa joydan kelgan IBAN faqat mod-97 bilan tekshiriladi.',

  'account.format.iso6346.name': 'Konteyner',
  'account.format.iso6346.length': '11 ta belgi',
  'account.format.iso6346.check': 'Nazorat raqami: value(c) x 2^i yigʻindisi, mod 11, mod 10',
  'account.format.iso6346.strength':
    'Kuchli, ammo agent har safar qoʻlda soʻraydigan oʻn ikkita maʼlum koʻr nuqtasi bor.',
  'account.format.iso6346.measured.1':
    'Xato budjeti: cheklanmaganda 0.0047, cheklanganda 0.0692 — 14.9x.',
  'account.format.iso6346.measured.2':
    'Bu yerda akustik model 21 punkt sokin tuzatish beradi, aniqlikka esa nol.',
  'account.format.iso6346.note.before':
    'Mod 11 boʻyicha teng qoldiqli belgilar bu nazorat raqamiga matematik jihatdan koʻrinmaydi:',
  'account.format.iso6346.note.after':
    'Shu juftlardan oʻn ikkitasi akustik jihatdan ham chalkashadi — B/V, K/A, F/P va yana toʻqqiztasi; bu oʻlchangan chalkashlik ogʻirligining 5.3% i. Readback ularning oʻn ikkitasini ham har safar soʻraydi. U yerdagi sukut ishonch emas, koʻra olmaydigan arifmetika boʻlar edi.',

  'account.format.nhs.name': 'NHS raqami',
  'account.format.nhs.length': '10 ta raqam',
  'account.format.nhs.check': 'Nazorat raqami, ogʻirliklar 10 dan 2 gacha, mod 11',
  'account.format.nhs.strength':
    'Kuchli, faqat raqamlardan iborat alifbo chalkashlik toʻplamini kichik saqlaydi.',
  'account.format.nhs.measured.1':
    'Bu yerda akustik model 64 punkt sokin tuzatish beradi — oʻlchangan formatlar ichida eng kattasi.',
  'account.format.nhs.note':
    'Oʻnta raqam, harflar yoʻq, shuning uchun chalkashlik jadvalining koʻp qismi bu yerga tegishli emas; 0.50 ogʻirlikdagi 5 va 9 juftligi eng ogʻiri. 10 qoldiqning haqiqiy nazorat raqami yoʻq, shuning uchun bunday raqamlar sokin tuzatilmaydi, balki butunlay rad etiladi.',
  'account.format.nhs.sensitive': 'Yozib olingan NHS raqami bemorni aniqlaydi.',

  'account.format.vin.name': 'VIN',
  'account.format.vin.length': '17 ta belgi, nazorat raqami 9-oʻrinda',
  'account.format.vin.check': '9-oʻrindagi nazorat raqami: transliteratsiya, ogʻirlik, mod 11',
  'account.format.vin.strength':
    'Kuchli, alifboning oʻzi arifmetika ishlashidan oldin eng yomon chalkashlikni olib tashlaydi.',
  'account.format.vin.note':
    'VIN alifbosida I, O va Q yoʻq. Bu oʻlchangan jadvaldagi eng ogʻir chalkash juftlikni — 0.95 ogʻirlikdagi O va 0 ni — nazorat raqamiga yetib borishidan oldin oʻchiradi. 9-oʻrni mos kelmagan VIN sokin tuzatilmaydi; u odamga uzatiladi.',

  'account.format.luhn.name': 'Karta',
  'account.format.luhn.length': '13 dan 19 tagacha raqam',
  'account.format.luhn.check': 'Nazorat raqami, Luhn mod 10, navbatma-navbat ikkilantirish bilan',
  'account.format.luhn.strength':
    'Bu yerdagi eng kuchsiz arifmetika. Agent tez-tez boʻlishini kuting.',
  'account.format.luhn.note':
    'Luhn har qanday bitta raqam almashinuvini va 0 bilan 9 dan tashqari har qanday qoʻshni oʻrin almashinuvini tutadi, ammo oʻz uzunlik qoidasi yoʻq, shuning uchun tushib qolgan raqam yigʻindi hamon qabul qiladigan qisqaroq raqam qoldiradi. Karta raqamlarida savol koʻp boʻlishi — arifmetikaning halolligi, mikrofonning nosozligi emas.',
  'account.format.luhn.sensitive':
    'Yozib olingan karta raqami boshqa har qanday identifikator kabi toʻliq saqlanadi.',

  // ----------------------------------------------- account: 03 vocabulary --

  'account.vocab.of': '/ {max} ta atama',
  'account.vocab.barLabel': 'Lugʻat toʻplami, ishlatilgan atamalar',
  'account.vocab.barValue': '{max} tadan {used} ta atama',
  'account.vocab.prose.a':
    'Oʻz tashuvchi prefikslaringiz, detal raqamlaringiz va obyekt nomlaringiz shu yerga kiritiladi — eng koʻpi bilan',
  'account.vocab.prose.b': 'ta atama, har biri',
  'account.vocab.prose.c':
    'tagacha belgi. Ikkala chegara ham bizniki emas, AssemblyAI niki: seans ochilganda toʻplam tanigichga oʻzgarishsiz uzatiladi va platforma undan uzunini qabul qilmaydi. Readback bu raqamlarning birortasini ham oshira olmaydi, shuning uchun chegarani dizayn qarori qilib koʻrsatish oʻrniga sizga ularga nisbatan hisobni koʻrsatadi.',
  'account.vocab.add': 'Atama qoʻshish',
  'account.vocab.hint': '/ {max} belgi.',
  'account.vocab.addButton': 'Qoʻshish',
  'account.vocab.full': 'Toʻplam {max} ta atama bilan toʻldi. Joy ochish uchun bittasini oʻchiring.',
  'account.vocab.empty':
    'Toʻplam boʻsh. Arifmetika bashorat qila olmaydigan soʻzlarni qoʻshing — avvalo qoʻngʻiroq qiluvchilaringiz eng koʻp aytadigan tashuvchi prefikslari va obyekt nomlarini.',
  'account.vocab.remove': '{term} ni toʻplamdan oʻchirish',
  'account.vocab.error.empty': 'Qoʻshishdan oldin atama yozing.',
  'account.vocab.error.tooLong': 'Bu {n} ta belgi. Platforma chegarasi — {max}.',
  'account.vocab.error.duplicate': 'Bu atama toʻplamda allaqachon bor.',
  'account.vocab.error.full':
    'Toʻplamga {max} ta atama sigʻadi. Joy ochish uchun bittasini oʻchiring.',
  'account.pending.vocab':
    'Toʻplam shu brauzerda yashaydi va hali hech qanday tanish seansiga yuborilmaydi:',

  // -------------------------------------------------- account: 04 consent --

  'account.consent.lead':
    'Qoʻngʻiroqlarni tinglaydigan mahsulot haqidagi tabiiy tashvish — u nimani saqlaydi. Javob: deyarli hech narsani, va bu siyosat emas, arxitektura qarori edi: suhbat hech qachon yozib olinmaydi, shuning uchun keyinchalik ehtiyotsizlik qilinadigan narsaning oʻzi yoʻq.',

  'account.ledger.audio.kicker': 'HECH QACHON SAQLANMAYDI',
  'account.ledger.audio.title': 'Xom audio',
  'account.ledger.audio.body':
    'Kadrlar faqat tanigich ularni belgilarga aylantirishi uchun kerak boʻlgan vaqtgacha ushlab turiladi va hech qayerga yozilmaydi. Readback ichida qoʻngʻirogʻingizning eksport qilinadigan, sud orqali talab qilinadigan yoki sizib chiqadigan yozuvi yoʻq.',
  'account.ledger.talk.kicker': 'HECH QACHON QOLDIRILMAYDI',
  'account.ledger.talk.title': 'Suhbat',
  'account.ledger.talk.body':
    'Readback qoʻngʻiroqni transkripsiya qilmaydi va qisqartirib bermaydi. Raqam atrofida aytilganlar raqam tasdiqlanishi bilan yoʻqoladi. Bu ekranda ham, rafda ham, maʼlumotlar bazasida ham transkript yoʻq va uni koʻrsatadigan biror koʻrinish ataylab tashlab ketilgan emas.',
  'account.ledger.id.kicker': 'SAQLANADI',
  'account.ledger.id.title': 'Yozib olingan identifikator',
  'account.ledger.id.body':
    'Raqamning oʻzi, qaysi format ekani, tasdiqlangani yoki belgilangani, agent necha marta boʻlishga majbur boʻlgani va qachon. Butun yozuv shundan iborat va raf shuni chizadi.',

  'account.consent.seam':
    'Yuqoridagilarning hammasi bu narsa qanday qurilgani bilan belgilangan. Quyidagi ikkita sozlama esa yoʻq — ular sizniki.',
  'account.consent.disclosure.title': 'Qoʻngʻiroq qiluvchilarga qanday aytiladi',
  'account.consent.disclosure.body':
    'Qoʻngʻiroqdagi kimdir yordamchi tinglayotganini bilishi kerak. Buni kim aytishini tanlang.',
  'account.disclosure.announces.label': 'Readback oʻzini eʼlon qiladi',
  'account.disclosure.announces.detail':
    'Qoʻngʻiroq boshida, hech narsa yozib olinmasdan oldin ingliz tilida bitta gap aytiladi: bu qoʻngʻiroqda maʼlumot raqamlarini yozib boradigan yordamchi ishlatiladi.',
  'account.disclosure.yours.label': 'Oʻz ogohlantirishingiz yetarli',
  'account.disclosure.yours.detail':
    'Qoʻngʻiroq qiluvchilarga oʻzingiz aytasiz — yozuv haqidagi eʼlonda yoki allaqachon ishlatayotgan matningizda. Raqam oʻqilmaguncha Readback jim turadi.',

  'account.consent.retention.title': 'Yozib olingan raqam qancha saqlanadi',
  'account.consent.retention.body':
    'Bu identifikator va uning yozuviga tegishli, chunki saqlanadigan boshqa narsaning oʻzi yoʻq. Muddatni qisqartirish yozib olinadigan narsani kamaytirmaydi: audio qisqartirish uchun umuman mavjud emas edi.',
  'account.consent.retention.label': 'Saqlash muddati',
  'account.retention.30': '30 kun',
  'account.retention.90': '90 kun',
  'account.retention.365': '365 kun',
  'account.retention.forever': 'Kimdir oʻchirmaguncha',

  'account.consent.card.before': 'Karta (Luhn)',
  'account.consent.card.after':
    'boʻlimida yoqilgan. Yozib olingan karta raqami boshqa har qanday identifikator kabi toʻliq va yuqoridagi saqlash muddati davomida saqlanadi. Readback PCI qamrovi haqida hech qanday daʼvo qilmaydi; bu formatni yoqiq qoldirishdan oldin karta raqamlari shu yozuvda boʻlishini xohlaysizmi — oʻzingiz hal qiling.',
  'account.consent.scope.before': 'Yozuvlar',
  'account.consent.scope.mid':
    'doirasida cheklangan. Yuqoridagi jamoadagi hamma ularni koʻra oladi;',
  'account.consent.scope.after':
    'bitta tashkilotning yozuvlarini qaytaradi va undan kengrogʻi yoʻq.',
  'account.pending.consent':
    'Yuqoridagi ikki tanlov shu brauzerda saqlanadi. Nima saqlanishi va nima saqlanmasligi ularga bogʻliq emas va u sozlama ham emas; oshkoralik va saqlash muddati endpointlari hali oldinda:',

  // ---------------------------------------------------- account: 05 usage --

  'account.usage.of': '/',
  'account.usage.notReported': 'bildirilmagan',
  'account.usage.barLabel': 'Tarifga nisbatan tinglash soniyalari',
  'account.usage.noReading': 'Koʻrsatkich yoʻq',
  'account.usage.note.none': 'Server bu tarif uchun limitni bildirmagan.',
  'account.usage.note.settled': 'Bu davr limiti ichida.',
  'account.usage.note.asking': 'Bu davr limitiga yaqin.',
  'account.usage.note.flagged': 'Bu davr limitidan oshgan.',
  'account.usage.error': 'Yozuvlarni oʻqib boʻlmadi, shuning uchun quyida hech narsa sanalmagan.',
  'account.usage.empty':
    'Yozuvlar yoʻq. Qoʻngʻiroq Readbackka yetib borib, kimdir raqam oʻqiganda u shu yerda va rafda paydo boʻladi. Shungacha hech narsa sanalmaydi.',
  'account.usage.captures': 'Yozuvlar',
  'account.usage.questions': 'Berilgan savollar',
  'account.usage.silent': 'Sokin tasdiqlangan',
  'account.usage.counts.kicker': 'NIMA SANALADI',
  'account.usage.counts.body':
    'Tinglash soniyalari qoʻngʻiroq Readbackka ulangan paytdan uzilgunicha, agent jim turgan har bir soniya bilan birga hisoblanadi. Sukut — mexanizmning oʻzi, shuning uchun faqat gapirgan soniyalarni hisoblash ishni bajarmaydigan qism uchun toʻlov olish boʻlar edi. Qoʻngʻiroq ulanmagan paytda hech narsa sanalmaydi; belgilangan yozuv ham sanaladi, chunki tinglash baribir boʻlgan.',
  'account.usage.derived.before': 'Yozuvlar, savollar va sokin tasdiqlar',
  'account.usage.derived.after':
    'dan sanaladi. Yuqoridagi soniyalar oʻsha yozuvlarning tasdiqlanish vaqtlaridan olingan, yaʼni ular tinglash vaqtining butuni emas, quyi chegarasi. Ikkala yarmini ham biror endpoint bildirmaguncha oʻlchagich nol emas, KOʻRSATKICH YOʻQ deb turadi, chunki nol — daʼvo, orqasida esa hech narsa yoʻq.',
  'account.pending.usage': 'Tarif limiti va haqiqiy tinglash jami hali shartnomada yoʻq:',

  'account.usage.secs': '{s} s',
  'account.usage.mins': '{m} daq {s} s',
  'account.usage.hrs': '{h} soat {m} daq',

  // ------------------------------------------------------- account: parts --

  'parts.toggle.on': 'Yoniq',
  'parts.toggle.off': 'Oʻchiq',
  'parts.bar.noReading': 'KOʻRSATKICH YOʻQ',

  // --------------------------------------------------------------- record --

  'record.eyebrow': 'Yozuv',
  'record.title': 'Nima yozib olindi',
  'record.lede':
    'Bu ekrandagi har bir raqam quvurdan chiqqan. Bu yerda hech narsa oʻylab topilmagan, taqlid qilingani esa buni oʻzi aytadi.',

  'record.headline.definition': 'hech kimdan hech narsa soʻramasdan yozilgan identifikator',
  'record.headline.window': 'Soʻnggi 30 kun',
  'record.headline.retention': 'Yozuvlar 30 kundan keyin oʻchiriladi.',
  'record.headline.replay': 'qayta ijro fixturalari',
  'record.headline.smallN':
    '20 tadan kam yozuv, shuning uchun foiz koʻrsatilmaydi: bunchalik kam qatorga qoʻyilgan foiz — oʻsha qatorlarning surati, xolos.',
  'record.headline.empty.title': 'Hali birorta identifikator olinmadi.',
  'record.headline.empty.body':
    'Olinganda, bu raqam agent hech kimdan hech narsa soʻramasdan nechtasini yozganini koʻrsatadi.',
  'record.headline.perId': 'har bir identifikatorga {v} savol',
  'record.headline.triple': '{asked} soʻraldi, {answered} javob oldi, {timedOut} javobsiz qoldi',
  'record.headline.pair': '{asked} soʻraldi, {spoken} ovoz chiqarib aytildi',
  'record.headline.asked': '{asked} soʻraldi',
  'record.headline.sr':
    '{total} identifikatordan {silent} tasi agent hech kimdan hech narsa soʻramasdan yozilgan.',

  'record.held.rest': 'Tinglayapti. Hali hech narsa aytilmadi.',
  'record.held.holding': 'Ushlab turibdi — {gate}.',
  'record.held.count': '{n}× ushlab turildi',
  'record.held.caption': 'Har bir belgi — agent gapirmaslikka qaror qilgan lahza.',
  'record.held.summary.caption':
    'oʻrinlar yozuv vaqtlaridan olingan; qaror-ma-qaror tarix saqlanmaydi.',
  'record.held.summary.count': '{captures} yozildi · {spoken} aytildi',
  'record.held.summary.say': 'Bu seans tugagan. U lahzama-lahza nima qaror qilgani saqlanmagan.',
  'record.held.sr.live':
    'Sukut koʻrsatkichi. {held} marta ushlab turildi. {spoke} marta gapirdi. Hozir ushlab turibdi: {gate}',
  'record.held.sr.rest': 'Sukut koʻrsatkichi. Hali hech narsa ushlanmadi va hech narsa aytilmadi.',
  'record.held.sr.summary':
    'Sukut koʻrsatkichi, umumiy shakl. {captures} identifikator yozildi, {spoken} tasi haqida gapirildi. Belgilar oʻrni yozuv vaqtlaridan olingan; qaror-ma-qaror tarix saqlanmagan.',

  'record.held.gate.1': 'aniq emas, lekin xato ham emas',
  'record.held.gate.2': 'gap navbati hali tugamadi',
  'record.held.gate.3': 'buni keyingi bosqich soʻramayapti',
  'record.held.gate.4': 'liniya jim emas',
  'record.held.gate.5': '1,5 s xushmuomalalik pauzasi ichida',
  'record.held.gate.6': 'bu identifikator haqida bir marta aytilgan',
  'record.held.gate.7': 'juda kech — oxirgi soʻzdan keyin 10 s dan oshdi',
  'record.held.gate.unknown': 'bu qurilma nomini bilmaydigan darvoza',

  'record.row.settledIn': '{s} s',
  'record.row.expand': 'Buni nima hal qilgan',
  'record.row.none': 'Birorta identifikator aytilmadi.',
  'record.row.none.note': 'Agent tingladi va hech narsa yozmadi.',
  'record.row.lengths':
    'Tanigich bergan satr yozilganidan boshqa uzunlikda, shuning uchun belgilar bir-biriga qatʼiy moslanmagan.',

  'record.detail.validatedBy': 'Tekshirgan',
  'record.detail.secondSignal': 'Ikkinchi signal',
  'record.detail.rung': 'Pogʻona',
  'record.detail.handover': 'Topshirish sababi',
  'record.detail.flagReason': 'Belgilash sababi',
  'record.detail.positionCorrected': 'Tuzatilgan oʻrin',
  'record.detail.ruledOut': 'Nimalarni chetga surgan',
  'record.detail.ruledOut.absent': 'roʻyxatda berilmagan',
  'record.detail.questions': 'Savollar',
  'record.detail.questions.unretained': 'tafsilot endi saqlanmaydi',
  'record.detail.question.line': '{position}-oʻrin, taklif qilingani {offered}',
  'record.detail.question.answered': 'javob {char}',
  'record.detail.question.unanswered': 'javob yoʻq',
  'record.detail.question.spoken': 'ovoz chiqarib soʻralgan',
  'record.detail.question.silent': 'ovoz chiqarilmagan',
  'record.detail.captureId': 'Yozuv ID',
  'record.detail.sessionId': 'Seans ID',
  'record.detail.copy': 'Nusxalash',
  'record.detail.copied': 'Nusxalandi',
  'record.detail.none': 'qayd etilmagan',
  'record.detail.loading': 'Seans oʻqilyapti…',
  'record.detail.unavailable':
    'Seans yozuvini oʻqib boʻlmadi, shuning uchun bu yerda hech narsa koʻrsatilmaydi.',

  'record.session.title': 'Seans',
  'record.session.open': 'ochiq',
  'record.session.regime': 'Ishonch rejimi',
  'record.session.regime.unknown': 'hali aniqlanmagan',
  'record.session.none': 'Birorta identifikator aytilmadi.',
  'record.session.none.note': 'Agent tingladi va hech narsa yozmadi. Bu — natija, boʻsh joy emas.',

  'record.replay.banner':
    'Qayta ijro — bu yozuvlar jonli qoʻngʻiroqdan emas, yozib olingan fixturalardan olingan.',
  'record.stamp.replay': 'qayta ijro',
  'record.stamp.demo': 'demo',

  'record.empty.chip': 'Namuna — sizning qoʻngʻiroqlaringizdan emas, tayyor fixturadan.',
  'record.empty.exampleTitle': 'Bitta ishlangan namuna',
  'record.empty.run': 'Demo qoʻngʻiroqni ishga tushirish',
  'record.empty.running': 'Fixtura ishlayapti',
  'record.empty.explain': 'Yozuv qanday hal qilinadi',
  'record.empty.failed':
    'Namunani serverdan olib boʻlmadi, shuning uchun uning oʻrnida hech narsa koʻrsatilmaydi.',

  'record.list.title': 'Identifikatorlar',
  'record.loading': 'Yozuv oʻqilyapti…',
  'record.error.noEndpoint':
    'Bu serverda hali yozuvlar roʻyxati yoʻq. Oʻylab topilgan narsa oʻrniga hech narsa koʻrsatilmaydi.',
  'record.retry': 'Qayta urinish',
  'record.export': 'CSV eksport',
  'record.export.window': 'Readback yozuvi. Oyna: soʻnggi {days} kun. Qatorlar: {rows}.',
  'record.export.replay.all':
    'Har bir qator jonli qoʻngʻiroqdan emas, yozib olingan fixturadan olingan.',
  'record.export.replay.mixed':
    'Ayrim qatorlar yozib olingan fixturalardan; qaysi biri ekanini manba ustuni aytadi.',
} as const;

export const uz: Messages = catalog satisfies Translated<typeof en, typeof catalog>;
