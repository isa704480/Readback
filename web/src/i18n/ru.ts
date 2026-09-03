/* Русский.
 *
 * Archivo has no Cyrillic subset -- measured against the Google Fonts CSS,
 * which serves only latin, latin-ext and vietnamese for that family. Every
 * character in this file therefore falls through to the next family in
 * --font-ui, which is why tokens.css now names IBM Plex Sans there. See the
 * comment on --font-ui in styles/tokens.css.
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

  'lang.switcher.label': 'Язык интерфейса',

  'lang.switcher.note':
    'Меняется только язык интерфейса. Readback слушает разговор по-английски и задаёт свой вопрос по-английски.',

  'lang.notice.short': 'Только интерфейс — агент слушает по-английски.',

  // ---------------------------------------------------------------- shell --

  'app.skipToContent': 'Перейти к содержимому',
  'app.routeFailed': 'Этот экран не удалось отрисовать. Перезагрузите страницу, а если это повторяется — сообщите нам.',

  // --------------------------------------------------------------- topbar --

  'topbar.nav.label': 'Основное меню',
  'topbar.signedIn': 'Вы вошли',
  'topbar.account': 'Аккаунт',
  'topbar.signOut': 'Выйти',
  'topbar.logIn': 'Войти',
  'topbar.getKey': 'Получить ключ',

  // ----------------------------------------------------------- navigation --

  /* 'nav.record' — «Запись», the same word as 'record.eyebrow' below, because
   * the rail's label and the screen's own eyebrow name one thing. */
  'nav.sidebar.label': 'Разделы',
  'nav.live': 'Звонок',
  'nav.record': 'Запись',
  'nav.sessions': 'Сеансы',
  'nav.formats': 'Форматы',
  'nav.demo': 'Демо',

  'nav.record.silent': '{silent} из {total} идентификаторов записаны без вопросов',

  'route.pending.eyebrow': 'Ещё не построено',
  'route.pending.live.title': 'Экран живого звонка ещё не построен.',
  'route.pending.live.body':
    'Здесь идентификатор заполняется по одному символу, пока идёт разговор. Вместо него здесь ничего не показано, потому что показывать нечего: живой записи нет, а анимированный макет звонка, которого не происходит, — единственное, чего этому продукту делать нельзя.',
  'route.pending.sessions.title': 'Список сеансов ещё не построен.',
  'route.pending.sessions.body':
    'Сеансы уже есть на экране записи — сгруппированные под идентификаторами, которые они дали. Отдельного списка со своими фильтрами и своим диапазоном дат пока нет.',
  'route.pending.formats.title': 'Справочник форматов ещё не построен.',
  'route.pending.formats.body':
    'Какие форматы включены для вашей организации и что каждый из них проверяет — сегодня это на экране аккаунта. Справочника, объясняющего, как считается каждая контрольная цифра, пока нет.',
  'route.pending.demo.title': 'Экран демонстрации ещё не построен.',
  'route.pending.demo.body':
    'Сама демонстрация настоящая и она работает: пустое состояние записи проигрывает одну записанную фикстуру от начала до конца и помечает её как фикстуру. Отдельного экрана, где выбирают, какую фикстуру запустить, пока нет.',
  'route.pending.toRecord': 'Перейти к записи',

  // ------------------------------------------------------- capture states --

  'capture.state.heard': 'Услышано, не подтверждено',
  'capture.state.repaired': 'Тихо исправлено',
  'capture.state.asking': 'Требуется одно уточнение',
  'capture.state.settled': 'Подтверждено',
  'capture.state.flagged': 'Помечено',

  // ----------------------------------------------------------------- rack --

  'rack.empty': 'Пока пусто. Стойка заполнится, как только кто-нибудь продиктует код.',
  'rack.asked.none': 'ничего не спрошено',
  'rack.asked.count': 'спрошено {n}×',

  // Capitalised: used only at the start of a sentence. See en.ts.
  'rack.readout.position': 'Позиция {n}',
  'rack.readout.blank': 'пусто',
  'rack.readout.repaired': '{position}: услышано {heard}, записано {written}.',
  'rack.readout.asked': '{position} — символ под вопросом.',
  'rack.readout.locked': '{position} вычислена, а не услышана.',

  /* Three real forms, and this is the reason the plural set exists at all:
   * 1 вопрос, 2 вопроса, 5 вопросов, and 21 goes back to вопрос. A `n === 1`
   * check gets 21 wrong, which is the single most visible way a Russian
   * interface announces that nobody localised it. Intl.PluralRules picks. */
  'rack.readout.questions.one': '{n} вопрос.',
  'rack.readout.questions.few': '{n} вопроса.',
  'rack.readout.questions.many': '{n} вопросов.',
  'rack.readout.questions.other': '{n} вопроса.',

  // --------------------------------------------------------------- legend --

  'rack.legend.empty.label': 'Пусто',
  'rack.legend.empty.note': 'Формат знает, что эта позиция будет. Её ещё никто не назвал.',
  'rack.legend.provisional.note': 'То, что выдал распознаватель; ещё может быть отменено.',
  'rack.legend.settled.note': 'Согласовано арифметикой и записано.',
  'rack.legend.repaired.note': 'Формат отменил микрофон. Оба символа остаются в строке.',
  'rack.legend.asked.note': 'Единственный символ, ради которого стоит прервать разговор.',
  'rack.legend.locked.label': 'Заблокировано форматом',
  'rack.legend.locked.note': 'Вычисляется из предыдущих позиций. Звук не может её изменить.',
  // -------------------------------------------------------------- landing --

  /* "is allowed to be" is deontic, and Russian carries it well: "имеет право
   * быть" is the permission sense, not "может быть" (possibility). The
   * contrast the headline lives on -- слышит against знает -- is kept. */
  'landing.hero.title.a': 'Он не слышит лучше.',
  'landing.hero.title.b': 'Он знает, каким ответ вообще имеет право быть.',
  'landing.hero.lede':
    'Readback слушает разговор фоном и записывает справочные номера: номера контейнеров, IBAN, VIN, номера пациентов, номера карт. Он не расшифровывает разговор и не пересказывает его. Чаще всего он молча исправляет то, что расслышал неверно. Когда не может — один раз перебивает, спрашивает про один символ и снова замолкает.',
  'landing.hero.scope':
    'Readback слушает разговор по-английски и задаёт свой единственный вопрос по-английски. Язык меняет только интерфейс.',

  'landing.rack.title': 'Стойка захватов',

  /* Three real forms each: 1 захват, 2 захвата, 5 захватов, and 21
   * returns to the singular. Intl.PluralRules picks; n === 1 would not. */
  'landing.rack.meta.captures.one': '{n} захват',
  'landing.rack.meta.captures.few': '{n} захвата',
  'landing.rack.meta.captures.many': '{n} захватов',
  'landing.rack.meta.captures.other': '{n} захвата',
  'landing.rack.meta.questions.one': '{n} вопрос',
  'landing.rack.meta.questions.few': '{n} вопроса',
  'landing.rack.meta.questions.many': '{n} вопросов',
  'landing.rack.meta.questions.other': '{n} вопроса',

  'landing.row.repaired.note':
    'позиция {position} · услышано {heard} · записано {written} · контрольный разряд {check} сходится',
  'landing.row.asking.note': 'одна из двенадцати слепых пар',

  /* The quoted fragment stays in English and is named as English: it is what
   * the agent says on the call, and the call is not in Russian. */
  'landing.row.asking.question':
    'Позиция {position}. Агент спрашивает по-английски: «{a} for {aWord}, or {b} for {bWord}?» Оба варианта оставляют контрольный разряд {check}, так что арифметика не возразит ни одному.',

  'landing.row.arriving.digits.one': 'ещё {n} разряд впереди',
  'landing.row.arriving.digits.few': 'ещё {n} разряда впереди',
  'landing.row.arriving.digits.many': 'ещё {n} разрядов впереди',
  'landing.row.arriving.digits.other': 'ещё {n} разряда впереди',

  'landing.row.settled.note':
    'контрольный разряд {check} сходится · чинить нечего',

  // ------------------------------------------------------ landing: beats --

  'landing.beats.title': 'Три такта, и продукт — средний',

  'landing.beat1.title': 'Он ослышивается.',
  /* "английские" is added on purpose. Пять and девять do not sound
   * alike; five and nine do. Translating the English sentence faithfully would
   * invent a measurement about Russian that nobody made. */
  'landing.beat1.body':
    'В шуме английские five и nine — один и тот же звук. То же с M и N, S и F, fifteen и fifty. Никакое акустическое моделирование этого не решит: информации нет в самом аудио.',
  'landing.beat1.caption': 'На плохой линии неразличимы, с любым акцентом.',
  'landing.confusable.soundsLike': '{a} звучит как {b}',

  'landing.beat2.title': 'Формат ограничивает ответ.',
  'landing.beat2.body':
    'Номер контейнера — это не одиннадцать свободных символов. Это десять символов и вычисленный из них контрольный разряд: последнюю клетку заполняет арифметика, а не микрофон. У IBAN есть mod-97. У карты есть Luhn. Формат знает то, чего не знает микрофон.',
  'landing.beat2.stripLabel':
    'ISO 6346. {spoken}, затем контрольный разряд {check}, который вычисляется из десяти предыдущих символов.',
  'landing.beat2.caption':
    'Последняя клетка заблокирована: никакое прочтение аудио её не сдвинет.',

  'landing.beat3.title': 'Обычно допустим только один ответ.',
  'landing.beat3.body':
    'Распознаватель поставил {heard} в позицию {position}, а говорящий продиктовал контрольный разряд {check}. Там могли стоять десять символов. Только с одним из них арифметика сходится — его агент и записывает, ничего не сказав.',
  'landing.sweep.groupLabel': 'Контрольный разряд для каждого возможного символа',
  'landing.sweep.caption':
    'Неизвестна позиция {position}. Вот каким становится контрольный разряд для каждого символа, который мог бы там стоять:',
  'landing.sweep.stub.candidate': 'позиция {position}',
  'landing.sweep.stub.check': 'контр. разряд',
  'landing.sweep.sr.heard': 'то, что услышал распознаватель',
  'landing.sweep.sr.legal': 'единственное значение, совпадающее со сказанным',
  'landing.beat3.caption':
    'Девять из десяти противоречат продиктованному контрольному разряду. Десятый и записывается.',

  // ------------------------------------------------------- landing: gain --

  'landing.gain.title':
    'Ограничение ответа увеличивает уровень ошибок, который система выдерживает, в пятнадцать раз.',
  'landing.gain.body.measured':
    'Измерено на восьми акцентах и примерно двенадцати миллионах смоделированных захватов, причём решателю ни разу не сообщали, какой акцент он слышит: {iso}× на ISO 6346, {iban}× на IBAN. По частоте ошибок распознавания акценты различаются не более чем в {spread}×, и бюджет в {budget}× перекрывает это на порядок.',
  'landing.gain.body.noDetection':
    'Поэтому здесь нет ни обучения на акцентах, ни их определения. Знание того, какой акцент вы слушаете, стоит ±{value}.',
  'landing.gain.ratio.unconstrained': 'без ограничения',
  'landing.gain.ratio.constrained': 'с ограничением',

  // ---------------------------------------------------- landing: silence --

  'landing.silence.title': 'Тишина — это и есть продукт.',
  'landing.silence.body':
    'Акустическая модель не добавляет точности вовсе. Контрольная сумма плюс два вопроса и так дают около 100%. Что модель действительно покупает — это тишину: {iso} пунктов молчаливых исправлений на ISO 6346 и {nhs} пунктов на номерах NHS.',
  'landing.silence.pull':
    'Агент, который переспрашивает каждый номер, — это и есть то самое «продиктуйте по буквам», ради удаления которого всё это и сделано.',

  // ------------------------------------------------- landing: blind pairs --

  'landing.blind.title': 'Двенадцать, которых он не видит',
  'landing.blind.body.math':
    'ISO 6346 суммирует {formula}, поэтому два символа с одинаковым значением по модулю 11 для контрольного разряда — один и тот же символ. По акустической таблице {share}% реалистичных ослышек попадает в этот провал, в двенадцати известных парах.',
  'landing.blind.body.rest':
    'И ещё девять. Агент каждый раз спрашивает про все двенадцать, а не делает вид, будто арифметика их видит. Молчание здесь было бы не уверенностью, а слепотой арифметики — поэтому в стойке наверху этой страницы есть строка, которая ждёт один символ номера, с контрольным разрядом которого всё в полном порядке.',
  'landing.blind.pair.chars': '{a} и {b}',
  'landing.blind.pair.math': '{first} и {second}. Оба ≡ {residue} (mod 11).',

  // ------------------------------------------------------ landing: close --

  'landing.close.title': 'Стойка — это и есть весь интерфейс.',
  'landing.close.body':
    'Расшифровку читать негде: разговор нигде не сохраняется. Спорить с оценкой уверенности не с чем: система выражает сомнение вопросом. Обратно возвращаются номер и число случаев, когда пришлось перебить.',
  // ------------------------------------------------------------- transport --

  /* По одному предложению на каждый ApiErrorKind, и виды РАЗДЕЛЕНЫ.
   * Каждое называет причину и говорит, что делать дальше. */
  'error.offline':
    'Не удаётся связаться со службой Readback. Проверьте соединение и попробуйте ещё раз.',
  'error.timeout':
    'Служба Readback не ответила вовремя. Возможно, она запускается — подождите немного и попробуйте снова.',
  'error.badRequest':
    'Часть этих данных не принята. Исправьте поля выше и отправьте ещё раз.',
  'error.unauthorized':
    'Эта почта и пароль не подошли ни к одному аккаунту. Проверьте оба или получите ключ, если аккаунта ещё нет.',
  'error.notFound':
    'Такой страницы нет. Перезагрузите страницу и напишите нам, если это повторится.',
  'error.conflict':
    'Аккаунт с такой почтой уже существует. Войдите вместо регистрации или укажите другой адрес.',
  'error.rateLimited': 'Слишком много попыток. Подождите минуту и попробуйте снова.',
  'error.server':
    'У службы Readback произошёл сбой на её стороне. Ничего не сохранено — попробуйте чуть позже.',
  'error.malformed':
    'Служба Readback вернула ответ, который эта страница не смогла прочитать. Попробуйте ещё раз и напишите нам, если это повторится.',

  'error.rateLimited.wait': 'Слишком много попыток. Попробуйте снова {when}.',
  'wait.moment': 'через несколько секунд',
  'wait.aboutMinute': 'примерно через минуту',
  /* Три формы, а не две: 21 секунду, 22 секунды, 25 секунд. Их выбирает
   * Intl.PluralRules, а не сравнение n === 1. */
  'wait.seconds.one': 'примерно через {n} секунду',
  'wait.seconds.few': 'примерно через {n} секунды',
  'wait.seconds.many': 'примерно через {n} секунд',
  'wait.seconds.other': 'примерно через {n} секунды',
  'wait.minutes.one': 'примерно через {n} минуту',
  'wait.minutes.few': 'примерно через {n} минуты',
  'wait.minutes.many': 'примерно через {n} минут',
  'wait.minutes.other': 'примерно через {n} минуты',

  // ------------------------------------------------------------ form parts --

  'field.required': '(обязательно)',
  'field.reveal.show': 'Показать: {label}',
  'field.reveal.hide': 'Скрыть: {label}',
  'button.busy': 'Выполняется',

  // ----------------------------------------------------------------- auth --

  'auth.login.title': 'Вход',
  'auth.login.blurb': 'Доступ к захватам вашей компании.',
  'auth.login.submit': 'Войти',
  'auth.login.busy': 'Проверяем',
  'auth.login.footLead': 'Ещё нет аккаунта?',
  'auth.login.footLink': 'Получить ключ',

  'auth.signup.title': 'Получить ключ',
  'auth.signup.blurb': 'Один аккаунт на компанию. Остальные присоединяются к нему по приглашению.',
  'auth.signup.submit': 'Создать аккаунт',
  'auth.signup.busy': 'Создаём',
  'auth.signup.footLead': 'Аккаунт уже есть?',
  'auth.signup.footLink': 'Войти',

  'auth.field.name': 'Ваше имя',
  'auth.field.company': 'Компания',
  'auth.field.email': 'Рабочая почта',
  'auth.field.password': 'Пароль',

  'auth.error.name': 'Введите ваше имя.',
  'auth.error.company': 'Введите название компании.',
  'auth.error.email.empty': 'Введите рабочую почту.',
  'auth.error.email.shape':
    'Это не похоже на адрес почты. Нужны имя, знак @ и домен — например maria@company.com.',
  'auth.error.password.choose': 'Придумайте пароль.',
  'auth.error.password.enter': 'Введите пароль.',

  // ------------------------------------------------------------- password --

  /* ПРАВИЛО. После перевода оно должно остаться ИСТИННЫМ: десять символов и
   * хотя бы по одному из трёх классов. Третий класс — широкий: это любой знак,
   * который не буква и не цифра, включая пробел. Поэтому «специальный символ»,
   * а не «знак препинания». */
  'pw.rule': 'Не менее {min} символов, среди них буква, цифра и специальный символ.',
  'pw.class.letter': 'букву',
  'pw.class.number': 'цифру',
  'pw.class.symbol': 'специальный символ',
  'pw.list.and': 'и',

  'pw.problem.shortCount': 'Нужно не менее {min} символов. Здесь их {have}.',
  'pw.problem.add': 'Добавьте {missing}.',

  'pw.problem.short': 'Используйте не менее {min} символов.',
  'pw.problem.long': 'Не длиннее {max} символов.',
  'pw.problem.include': 'Добавьте {missing}.',
  'pw.problem.context.email': 'Не вставляйте в пароль свою почту.',
  'pw.problem.context.name': 'Не вставляйте в пароль своё имя.',
  'pw.problem.context.company': 'Не вставляйте в пароль название своей компании.',
  'pw.problem.commonBolted':
    'Это очень распространённый пароль, к которому просто приписали цифры или символы.',
  'pw.problem.commonPlain': 'Это один из самых частых паролей в мире.',
  'pw.problem.keyboardRun': 'В нём есть подряд идущий ряд клавиш на клавиатуре.',
  'pw.problem.repeats': 'В нём один и тот же символ повторяется три раза или больше.',
  'pw.problem.fewDistinct': 'В нём слишком мало разных символов.',
  'pw.problem.wordNumberSymbol':
    'Слово, затем цифры, затем символ — это первое, что пробует взломщик.',
  'pw.suggestion.length':
    'Длина важнее хитрости — четыре несвязанных слова надёжнее одного слова с заменами букв.',
  'pw.suggestion.addMore': 'Добавьте ещё несколько символов, чтобы он стал уверенно надёжным.',

  /* СЛОВА НАДЁЖНОСТИ. Цвет здесь не носитель смысла — четыре цвета состояний в
   * оттенках серого сливаются в один. Носитель — слово, поэтому четыре уровня
   * названы четырьмя разными словами, а утечка — пятый, отдельный вердикт. */
  'pw.strength.idle': 'Надёжность пароля',
  'pw.strength.weak': 'Слабый',
  'pw.strength.fair': 'Средний',
  'pw.strength.good': 'Хороший',
  'pw.strength.strong': 'Надёжный',
  'pw.strength.breached': 'Найден в утечке',

  'pw.breach.count.one': 'Этот пароль встречается в {n} известной утечке.',
  'pw.breach.count.few': 'Этот пароль встречается в {n} известных утечках.',
  'pw.breach.count.many': 'Этот пароль встречается в {n} известных утечках.',
  'pw.breach.count.other': 'Этот пароль встречается в {n} известных утечках.',
  'pw.breach.advice': 'Взломщики сначала пробуют утёкшие пароли — выберите другой.',
  'pw.breach.clean': 'Ни в одной известной утечке не найден.',
  'pw.breach.unchecked': 'С известными утечками не сверялся — служба не ответила.',

  // -------------------------------------------------------- account: shell --

  'account.eyebrow': 'НАСТРОЙКИ',
  'account.title': 'Аккаунт',
  'account.org.unknown': 'Организация неизвестна',
  'account.org.yours': 'вашей организации',
  'account.loading.session': 'Проверяем вашу сессию',
  'account.loading.team': 'Загружаем вашу команду',
  'account.loading.usage': 'Загружаем расход',
  'account.unreachable':
    'Не удаётся связаться со службой Readback. Всё, что ниже, — последнее известное состояние этого аккаунта, а не текущее, и ничто изменённое здесь до сервера не дойдёт.',
  'account.refresh': 'Обновить',
  'account.refreshing': 'Обновляем',
  'account.index.label': 'Разделы аккаунта',

  'account.profile.title': 'Профиль и команда',
  'account.profile.lede':
    'Все здесь видят одни и те же захваты. Роли решают, кто может менять настройки на этом экране.',
  'account.formats.title': 'Форматы',
  'account.formats.lede':
    'Какие типы идентификаторов слушает Readback. Агент молчит, пока не услышит, что читают один из них.',
  'account.vocab.title': 'Словарь',
  'account.vocab.lede':
    'Слова, которые формат предсказать не может. Контрольная цифра ограничивает символы; о слове Maersk она не знает ничего.',
  'account.consent.title': 'Согласие',
  'account.consent.lede':
    'Readback слушает фоном во время живых звонков. Этот раздел — не формальность, и его стоит прочитать раньше остального.',
  'account.usage.title': 'Расход',
  'account.usage.lede':
    'Секунды прослушивания против тарифа и то, за что этот экран может честно отчитаться.',

  // ----------------------------------------------------- account: 01 team --

  'account.team.empty':
    'Команду показать не удалось. Аккаунт не прочитан, поэтому и перечислять некого. Нажмите «Обновить» выше.',
  'account.team.you': 'ВЫ',
  'account.team.invitedHere': 'ТОЛЬКО ЗДЕСЬ',
  'account.team.roleColumn': 'РОЛЬ',
  'account.team.cannotRemoveSelf': 'Себя удалить нельзя.',
  'account.team.remove': 'Удалить: {name}',
  'account.team.onlyYou':
    'Пока только вы. Пригласите тех, кто принимает эти звонки, чтобы захваты оказывались не в одном браузере.',

  'account.role.owner': 'Владелец',
  'account.role.owner.can': 'Всё, включая оплату и этот экран.',
  'account.role.admin': 'Администратор',
  'account.role.admin.can': 'Этот экран, команда и все захваты.',
  'account.role.operator': 'Оператор',
  'account.role.operator.can': 'Все захваты. Не может менять форматы, согласие и команду.',

  'account.invite.title': 'Пригласить человека',
  'account.invite.name': 'Имя',
  'account.invite.nameHint': 'Необязательно. Без него приглашение будет указано по адресу.',
  'account.invite.email': 'Почта',
  'account.invite.role': 'Роль',
  'account.invite.submit': 'Добавить в список',
  'account.invite.duplicate': 'Человек с этим адресом уже в команде.',

  'account.email.empty': 'Введите адрес почты.',
  'account.email.space': 'В адресе почты не может быть пробела.',
  'account.email.at': 'Нужен один знак @, и перед ним должно быть имя.',
  'account.email.domain': 'Часть после @ не похожа на домен.',

  'account.pending.team':
    'Приглашения, смена ролей и удаления остаются в этой вкладке браузера. Ничего не отправляется письмом и ничего не сохраняется, пока не появятся эндпойнты команды:',

  // -------------------------------------------------- account: 02 formats --

  'account.formats.prose1':
    'Readback не слышит лучше, чем распознаватель под ним. Он знает, каким вообще может быть допустимый ответ. Поэтому контрольная цифра важнее микрофона, и поэтому сила арифметики напечатана в каждой строке ниже.',
  'account.formats.prose2.lead':
    'Цвет в строке — не оценка стандарта. Это прогноз того, как часто вас будут прерывать:',
  'account.formats.prose2.mid':
    '— значит, арифметика поглощает большинство ослышек, ни о чём не спрашивая, а',
  'account.formats.prose2.tail':
    '— значит, агент будет говорить чаще. Это те же два слова и те же два цвета, что и в стойке захвата.',

  'account.formats.shape': 'Вид',
  'account.formats.length': 'Длина',
  'account.formats.check': 'Контрольная цифра',
  'account.formats.onRecord': 'В записях',
  'account.formats.noCheck': 'Нет. Решателю не с чем сверяться.',
  'account.formats.notCounted': 'Не подсчитано, сессии недоступны',
  'account.formats.noCaptures': 'Захватов пока нет',
  'account.formats.captures.one': '{n} захват',
  'account.formats.captures.few': '{n} захвата',
  'account.formats.captures.many': '{n} захватов',
  'account.formats.captures.other': '{n} захвата',
  'account.formats.cannot': 'ЧЕГО АРИФМЕТИКА НЕ ВИДИТ',
  'account.formats.sensitive.before': 'Что это значит — см. раздел',
  'account.formats.sensitive.after': 'ниже.',
  'account.pending.formats':
    'Включение и выключение формата действует только в этой вкладке браузера, и агент на ваших звонках не изменится, пока не появится эндпойнт форматов:',

  'account.format.iban.name': 'IBAN',
  'account.format.iban.length': 'от 16 до 34 символов, фиксировано по стране',
  'account.format.iban.check': 'Две контрольные цифры, mod-97-10',
  'account.format.iban.strength':
    'Самая сильная арифметика здесь. Две контрольные цифры на всю строку.',
  'account.format.iban.measured.1':
    'Бюджет ошибок 0.0023 без ограничения, 0.0399 с ограничением: 17.1x — самый большой измеренный выигрыш.',
  'account.format.iban.measured.2': 'Разброс по восьми проверенным акцентам: 1.14x.',
  'account.format.iban.note':
    'Код страны фиксирует длину ещё до того, как заработает арифметика, поэтому пропавший символ ловится формой, а не контрольной суммой. Валидатору известны длины десяти стран; IBAN из любой другой проверяется только по mod-97.',

  'account.format.iso6346.name': 'Контейнер',
  'account.format.iso6346.length': '11 символов',
  'account.format.iso6346.check': 'Контрольная цифра, сумма value(c) x 2^i, mod 11, mod 10',
  'account.format.iso6346.strength':
    'Сильная, но с двенадцатью известными слепыми зонами, о которых агент спрашивает вручную.',
  'account.format.iso6346.measured.1':
    'Бюджет ошибок 0.0047 без ограничения, 0.0692 с ограничением: 14.9x.',
  'account.format.iso6346.measured.2':
    'Акустическая модель даёт здесь 21 пункт тихого исправления и ноль точности.',
  'account.format.iso6346.note.before':
    'Символы, сравнимые по модулю 11, математически невидимы для этой контрольной цифры:',
  'account.format.iso6346.note.after':
    'Двенадцать из этих пар вдобавок похожи на слух — B/V, K/A, F/P и ещё девять; это 5.3% измеренного веса путаницы. Readback спрашивает про все двенадцать каждый раз. Молчание там было бы не уверенностью, а арифметикой, которая не видит.',

  'account.format.nhs.name': 'Номер NHS',
  'account.format.nhs.length': '10 цифр',
  'account.format.nhs.check': 'Контрольная цифра, веса от 10 до 2, mod 11',
  'account.format.nhs.strength':
    'Сильная, а алфавит только из цифр держит множество путаниц маленьким.',
  'account.format.nhs.measured.1':
    'Акустическая модель даёт здесь 64 пункта тихого исправления — больше всех измеренных форматов.',
  'account.format.nhs.note':
    'Десять цифр и ни одной буквы, поэтому большая часть таблицы путаницы сюда не относится; самая тяжёлая применимая пара — 5 против 9 с весом 0.50. У остатка 10 нет допустимой контрольной цифры, поэтому такие номера не исправляются тихо, а отклоняются целиком.',
  'account.format.nhs.sensitive': 'Захваченный номер NHS идентифицирует пациента.',

  'account.format.vin.name': 'VIN',
  'account.format.vin.length': '17 символов, контрольная цифра на позиции 9',
  'account.format.vin.check': 'Контрольная цифра на позиции 9: транслитерация, веса, mod 11',
  'account.format.vin.strength':
    'Сильная, и сам алфавит убирает худшую путаницу ещё до того, как заработает арифметика.',
  'account.format.vin.note':
    'В алфавите VIN нет I, O и Q. Это удаляет самую тяжёлую пару в измеренной таблице — O против 0 с весом 0.95 — ещё до контрольной цифры. VIN, у которого позиция 9 не сходится, не исправляется тихо; он уходит человеку.',

  'account.format.luhn.name': 'Карта',
  'account.format.luhn.length': 'от 13 до 19 цифр',
  'account.format.luhn.check': 'Контрольная цифра, Luhn mod 10 с удвоением через одну',
  'account.format.luhn.strength':
    'Самая слабая арифметика здесь. Ожидайте, что агент будет прерывать чаще.',
  'account.format.luhn.note':
    'Luhn ловит любую замену одной цифры и любую перестановку соседних, кроме 0 рядом с 9, и не несёт собственного правила длины, поэтому пропавшая цифра оставляет более короткий номер, который сумма всё ещё принимает. Больше вопросов по номерам карт — это честность арифметики, а не отказ микрофона.',
  'account.format.luhn.sensitive':
    'Захваченный номер карты хранится целиком, как и любой другой захваченный идентификатор.',

  // ----------------------------------------------- account: 03 vocabulary --

  'account.vocab.of': 'из {max} терминов',
  'account.vocab.barLabel': 'Словарь, использовано терминов',
  'account.vocab.barValue': '{used} из {max} терминов',
  'account.vocab.prose.a':
    'Ваши собственные префиксы перевозчиков, номера деталей и названия площадок вводятся здесь — до',
  'account.vocab.prose.b': 'терминов по',
  'account.vocab.prose.c':
    'символов каждый. Оба потолка — не наши, а AssemblyAI: словарь передаётся распознавателю дословно при открытии сессии, и платформа не примет более длинный. Readback не может поднять ни одно из этих чисел, поэтому показывает счёт относительно них, а не выдаёт чужой предел за собственное решение.',
  'account.vocab.add': 'Добавить термин',
  'account.vocab.hint': 'из {max} символов.',
  'account.vocab.addButton': 'Добавить',
  'account.vocab.full': 'Словарь заполнен: {max} терминов. Удалите один, чтобы освободить место.',
  'account.vocab.empty':
    'Словарь пуст. Добавьте слова, которые арифметика предсказать не может, начиная с префиксов перевозчиков и названий площадок, которые ваши собеседники называют чаще всего.',
  'account.vocab.remove': 'Удалить из словаря: {term}',
  'account.vocab.error.empty': 'Наберите термин, прежде чем добавлять.',
  'account.vocab.error.tooLong': 'Здесь {n} символов. Предел платформы — {max}.',
  'account.vocab.error.duplicate': 'Такой термин уже есть в словаре.',
  'account.vocab.error.full':
    'Словарь вмещает {max} терминов. Удалите один, чтобы освободить место.',
  'account.pending.vocab':
    'Словарь живёт в этой вкладке браузера и пока не отправляется ни в одну сессию распознавания:',

  // -------------------------------------------------- account: 04 consent --

  'account.consent.lead':
    'Очевидная тревога о продукте, который слушает звонки, — что он сохраняет. Ответ: почти ничего, и это было архитектурное решение, а не политика: разговор нигде не записывается, поэтому с ним потом просто нечего терять по неосторожности.',

  'account.ledger.audio.kicker': 'НИКОГДА НЕ ХРАНИТСЯ',
  'account.ledger.audio.title': 'Сырое аудио',
  'account.ledger.audio.body':
    'Кадры держатся ровно столько, сколько распознавателю нужно, чтобы превратить их в символы, и никуда не записываются. Внутри Readback нет записи вашего звонка, которую можно было бы выгрузить, истребовать по суду или потерять.',
  'account.ledger.talk.kicker': 'НИКОГДА НЕ СОХРАНЯЕТСЯ',
  'account.ledger.talk.title': 'Разговор',
  'account.ledger.talk.body':
    'Readback не расшифровывает звонок и не пересказывает его. Сказанное вокруг номера исчезает в тот момент, когда номер подтверждён. Расшифровки нет ни на этом экране, ни в стойке, ни в базе, и ни один экран, который бы её показал, не был просто «не сделан».',
  'account.ledger.id.kicker': 'ХРАНИТСЯ',
  'account.ledger.id.title': 'Захваченный идентификатор',
  'account.ledger.id.body':
    'Сам номер, какого он формата, подтверждён он или помечен, сколько раз агенту пришлось прервать разговор и когда. Это вся запись целиком, и именно её рисует стойка.',

  'account.consent.seam':
    'Всё выше задано тем, как эта штука устроена. Две настройки ниже — нет, и они ваши.',
  'account.consent.disclosure.title': 'Как об этом узнают собеседники',
  'account.consent.disclosure.body':
    'Кто-то на звонке должен знать, что слушает ассистент. Выберите, кто это скажет.',
  'account.disclosure.announces.label': 'Readback объявляет о себе сам',
  'account.disclosure.announces.detail':
    'Одна произнесённая фраза в начале звонка — по-английски, до того как что-либо захвачено: в этом звонке используется ассистент, который записывает справочные номера.',
  'account.disclosure.yours.label': 'Достаточно вашего собственного уведомления',
  'account.disclosure.yours.detail':
    'Вы говорите собеседникам сами — в объявлении о записи или в скрипте, который уже используете. Readback молчит, пока не прозвучит номер.',

  'account.consent.retention.title': 'Сколько хранится захваченный номер',
  'account.consent.retention.body':
    'Это относится к идентификатору и его записи, потому что больше хранить нечего. Сокращение срока не уменьшает того, что захватывается: аудио и не было, чтобы его сокращать.',
  'account.consent.retention.label': 'Срок хранения',
  'account.retention.30': '30 дней',
  'account.retention.90': '90 дней',
  'account.retention.365': '365 дней',
  'account.retention.forever': 'Пока кто-нибудь не удалит',

  'account.consent.card.before': 'Карта (Luhn) включена в разделе',
  'account.consent.card.after':
    '— захваченный номер карты хранится целиком, точно как любой другой захваченный идентификатор, весь срок хранения выше. Readback ничего не утверждает о зоне PCI; решите, нужны ли номера карт в этой записи, прежде чем оставлять формат включённым.',
  'account.consent.scope.before': 'Захваты ограничены организацией',
  'account.consent.scope.mid': '— их видят все в команде выше;',
  'account.consent.scope.after':
    'возвращает захваты одной организации и более широкой формы не имеет.',
  'account.pending.consent':
    'Два выбора выше держатся в этой вкладке браузера. Что хранится и что не хранится, от них не зависит и настройкой не является; эндпойнты уведомления и срока хранения ещё впереди:',

  // ---------------------------------------------------- account: 05 usage --

  'account.usage.of': 'из',
  'account.usage.notReported': 'не сообщено',
  'account.usage.barLabel': 'Секунды прослушивания против тарифа',
  'account.usage.noReading': 'Нет показания',
  'account.usage.note.none': 'Сервер не сообщил лимит для этого тарифа.',
  'account.usage.note.settled': 'В пределах лимита за период.',
  'account.usage.note.asking': 'Близко к лимиту за период.',
  'account.usage.note.flagged': 'Лимит за период превышен.',
  'account.usage.error': 'Захваты прочитать не удалось, поэтому ниже ничего не подсчитано.',
  'account.usage.empty':
    'Захватов нет. Как только звонок дойдёт до Readback и кто-нибудь прочитает номер, он появится здесь и в стойке. До тех пор ничего не считается.',
  'account.usage.captures': 'Захваты',
  'account.usage.questions': 'Задано вопросов',
  'account.usage.silent': 'Подтверждено молча',
  'account.usage.counts.kicker': 'ЧТО СЧИТАЕТСЯ',
  'account.usage.counts.body':
    'Секунды прослушивания идут с момента подключения звонка к Readback и до отключения, включая каждую секунду, когда агент молчит. Молчание и есть механизм, поэтому брать плату только за секунды речи значило бы платить за ту часть, которая работу не делает. Пока звонок не подключён, не считается ничего, а помеченный захват считается всё равно, потому что прослушивание всё равно было.',
  'account.usage.derived.before': 'Захваты, вопросы и тихие подтверждения считаются из',
  'account.usage.derived.after':
    '— секунды выше выведены из времён подтверждения тех же захватов, а значит они нижняя граница вашего времени прослушивания, а не всё оно. Пока эндпойнт не сообщит обе половины, шкала показывает НЕТ ПОКАЗАНИЯ, а не ноль, потому что ноль был бы утверждением, за которым ничего не стоит.',
  'account.pending.usage':
    'Лимита тарифа и настоящего итога прослушивания в контракте пока нет:',

  'account.usage.secs': '{s} с',
  'account.usage.mins': '{m} мин {s} с',
  'account.usage.hrs': '{h} ч {m} мин',

  // ------------------------------------------------------- account: parts --

  'parts.toggle.on': 'Вкл',
  'parts.toggle.off': 'Выкл',
  'parts.bar.noReading': 'НЕТ ПОКАЗАНИЯ',

  // --------------------------------------------------------------- record --

  'record.eyebrow': 'Запись',
  'record.title': 'Что было записано',
  'record.lede':
    'Каждое число на этом экране пришло из конвейера. Здесь ничего не выдумано, а всё смоделированное само об этом говорит.',

  'record.headline.definition': 'идентификаторов записано, никого ни о чём не спросив',
  'record.headline.window': 'Последние 30 дней',
  'record.headline.retention': 'Записи удаляются через 30 дней.',
  'record.headline.replay': 'записанные фикстуры',
  'record.headline.smallN':
    'Меньше 20 записей, поэтому процента здесь нет: процент по такому числу строк — это картинка этих строк, а не показатель.',
  'record.headline.empty.title': 'Пока не записано ни одного идентификатора.',
  'record.headline.empty.body':
    'Когда они появятся, это число покажет, сколько было записано без единого вопроса к человеку.',
  'record.headline.perId': '{v} вопроса на идентификатор',
  'record.headline.triple': '{asked} задано, {answered} с ответом, {timedOut} без ответа',
  'record.headline.pair': '{asked} задано, {spoken} произнесено вслух',
  'record.headline.asked': '{asked} задано',
  'record.headline.sr':
    '{silent} из {total} идентификаторов записаны без единого вопроса к человеку.',

  'record.held.rest': 'Слушает. Пока ничего не сказано.',
  'record.held.holding': 'Держит паузу — {gate}.',
  'record.held.count': 'пауз: {n}',
  'record.held.caption': 'Каждая отметка — момент, когда агент решил промолчать.',
  'record.held.summary.caption':
    'позиции взяты из времени записей; история отдельных решений не хранится.',
  'record.held.summary.count': '{captures} записано · {spoken} произнесено',
  'record.held.summary.say': 'Сеанс завершён. Что он решал по ходу дела, не сохранено.',
  'record.held.sr.live':
    'Индикатор молчания. Пауз: {held}. Сказано вслух: {spoke}. Сейчас держит паузу: {gate}',
  'record.held.sr.rest': 'Индикатор молчания. Пауз пока нет, вслух ничего не сказано.',
  'record.held.sr.summary':
    'Индикатор молчания, сводная форма. Записано идентификаторов: {captures}, из них произнесено: {spoken}. Позиции отметок взяты из времени записей; история отдельных решений не сохранена.',

  'record.held.gate.1': 'не уверен, но и не ошибся',
  'record.held.gate.2': 'реплика ещё не закончилась',
  'record.held.gate.3': 'дальше это никому не нужно',
  'record.held.gate.4': 'на линии не тихо',
  'record.held.gate.5': 'внутри паузы вежливости в 1,5 с',
  'record.held.gate.6': 'об этом номере уже говорили один раз',
  'record.held.gate.7': 'слишком поздно — больше 10 с с последнего слова',
  'record.held.gate.unknown': 'условие, у которого в этой сборке нет названия',

  'record.row.settledIn': '{s} с',
  'record.row.expand': 'Что это решило',
  'record.row.none': 'Идентификатор не был произнесён.',
  'record.row.none.note': 'Агент слушал и ничего не записал.',
  'record.row.lengths':
    'Строка распознавателя другой длины, чем записанная, поэтому символы не сопоставлены один к одному.',

  'record.detail.validatedBy': 'Проверено',
  'record.detail.secondSignal': 'Второй сигнал',
  'record.detail.rung': 'Ступень',
  'record.detail.handover': 'Передано человеку потому, что',
  'record.detail.flagReason': 'Помечено потому, что',
  'record.detail.positionCorrected': 'Исправленная позиция',
  'record.detail.ruledOut': 'Что было отброшено',
  'record.detail.ruledOut.absent': 'в списке не передаётся',
  'record.detail.questions': 'Вопросы',
  'record.detail.questions.unretained': 'подробности больше не хранятся',
  'record.detail.question.line': 'позиция {position}, предложено {offered}',
  'record.detail.question.answered': 'ответ {char}',
  'record.detail.question.unanswered': 'без ответа',
  'record.detail.question.spoken': 'произнесено вслух',
  'record.detail.question.silent': 'вслух не произносилось',
  'record.detail.captureId': 'ID записи',
  'record.detail.sessionId': 'ID сеанса',
  'record.detail.copy': 'Копировать',
  'record.detail.copied': 'Скопировано',
  'record.detail.none': 'не зафиксировано',
  'record.detail.loading': 'Читаем сеанс…',
  'record.detail.unavailable':
    'Запись сеанса прочитать не удалось, поэтому здесь ничего не показано.',

  'record.session.title': 'Сеанс',
  'record.session.open': 'открыт',
  'record.session.regime': 'Режим уверенности',
  'record.session.regime.unknown': 'пока не определён',
  'record.session.none': 'Идентификатор не был произнесён.',
  'record.session.none.note':
    'Агент слушал и ничего не записал. Это результат, а не пустое место.',

  'record.replay.banner':
    'Повтор — эти записи получены из записанных фикстур, а не из живого звонка.',
  'record.stamp.replay': 'повтор',
  'record.stamp.demo': 'демо',

  'record.empty.chip': 'Пример — из готовой фикстуры, не из ваших звонков.',
  'record.empty.exampleTitle': 'Один разобранный пример',
  'record.empty.run': 'Запустить демо-звонок',
  'record.empty.running': 'Фикстура выполняется',
  'record.empty.explain': 'Как принимается решение по записи',
  'record.empty.failed':
    'Пример не удалось получить с сервера, поэтому вместо него ничего не показано.',

  'record.list.title': 'Идентификаторы',
  'record.loading': 'Читаем запись…',
  'record.error.noEndpoint':
    'На этом сервере ещё нет списка записей. Здесь ничего не показано вместо того, чтобы показать выдуманное.',
  'record.retry': 'Попробовать снова',
  'record.export': 'Экспорт CSV',
  'record.export.window': 'Запись Readback. Окно: последние {days} дн. Строк: {rows}.',
  'record.export.replay.all':
    'Каждая строка получена из записанной фикстуры, а не из живого звонка.',
  'record.export.replay.mixed':
    'Часть строк получена из записанных фикстур; какие именно — сказано в столбце источника.',

  // -------------------------------------------------------------- consent --

  'consent.eyebrow': 'Прежде чем откроется микрофон',
  'consent.title': 'Сначала — согласие',
  'consent.lede':
    'Readback слушает звонок в фоне и записывает номера-идентификаторы. Ничего не откроется, пока все участники звонка не предупреждены и пока вы не прочитали и не приняли это.',
  'consent.what.title': 'Что происходит на этом звонке',
  'consent.what.1':
    'Микрофон этого устройства передаётся на сервер Readback, а сервер пересылает звук распознавателю речи. Сырой звук не сохраняется нигде на этом пути — ни на устройстве, ни на сервере, ни выше.',
  'consent.what.2':
    'Хранятся только идентификаторы: сам номер, его формат, установился ли он и сколько раз агенту пришлось спросить. Разговор вокруг них никогда не записывается.',
  'consent.what.3':
    'Агент слушает на английском. Если он не может установить один символ, он один раз спрашивает именно про этот символ и снова замолкает.',
  'consent.what.4':
    'Сеанс останавливается сам через {seconds} секунд. Вы можете остановить его раньше в любой момент, и остановка немедленно закрывает соединение с распознавателем.',
  'consent.allParty':
    'Каждый участник звонка должен знать, что его слушает ассистент, откуда бы он ни звонил. Настройки, которая это отменяет, нет и не будет.',
  'consent.version': 'Версия текста уведомления',
  'consent.version.loading': 'Версия читается с сервера…',
  'consent.version.unavailable':
    'Сервер недоступен, поэтому версия уведомления неизвестна и сеанс начать нельзя.',
  'consent.replayOnly':
    'На этом сервере нет ключа распознавания или его дневной бюджет исчерпан. Сеанс, начатый здесь, не услышал бы этот микрофон, поэтому начать его нельзя.',
  'consent.accept.label': 'Я прочитал(а) это и принимаю.',
  'consent.played.label': 'Второй стороне звонка сообщено, что её слушает ассистент.',
  'consent.start': 'Начать слушать',
  'consent.starting': 'Открывается',
  'consent.mic.note': 'Браузер запросит микрофон только после нажатия этой кнопки, никогда раньше.',

  // ----------------------------------------------------------------- live --

  'live.eyebrow': 'Эфир',
  'live.title': 'Слушаю этот звонок',
  'live.state.starting': 'Согласие записывается',
  'live.state.connecting': 'Сеанс открывается',
  'live.state.listening': 'Слушаю',
  'live.state.ended': 'Завершён',
  'live.state.failed': 'Остановлен',

  'live.armed': 'Слышно что-то похожее на {format}.',
  'live.idle': 'Пока ничего похожего на идентификатор.',
  'live.elapsed.label': 'слушаю уже',
  'live.elapsed.sr': 'Слушаю уже {time}.',
  'live.cap.remaining': 'осталось около {s} с из лимита {cap} с',
  'live.cap.explain':
    'Каждый сеанс сам останавливается на {cap} секундах. Это бюджетное правило развёртывания, а не сбой.',

  'live.rack.title': 'Панель записи',
  'live.rack.meta': 'эфир',
  'live.row.reason': 'причина: {reason}',
  'live.stop': 'Остановить и завершить сеанс',
  'live.hidden.notice':
    'Пока вкладка была скрыта, звук не отправлялся {s} с. Ничего не буферизовалось и не досылалось; распознаватель просто слышал тишину.',
  'live.noSignal':
    'Микрофон открыт, но передаёт тишину. Проверьте выключатель звука на устройстве или в операционной системе.',

  'live.mic.title': 'Что дал браузер',
  'live.mic.rate': '{rate} Гц с устройства, передискретизировано в 16000 Гц',
  'live.mic.rate.unknown': 'частота устройства не сообщена; контекст {rate} Гц, передискретизировано в 16000 Гц',
  'live.mic.channels': '{n} кан.',
  'live.mic.ec': 'подавление эха',
  'live.mic.ns': 'подавление шума',
  'live.mic.agc': 'автоусиление',
  'live.mic.unknown': 'не сообщено',
  'live.mic.device': 'устройство',
  'live.mic.device.unknown': 'устройство без имени',
  'live.chunks': 'отправлено фрагментов: {n} · по 100 мс',

  'live.q.title': 'Один символ',
  'live.q.position': 'Позиция {n}',
  'live.q.blind':
    'Контрольная цифра не различает эти два символа. Агент спрашивает про эту пару каждый раз; это тщательность, а не сомнение.',
  'live.q.says': 'Агент говорит, по-английски:',
  'live.q.tap': 'Нажмите на символ, который вы услышали.',
  'live.q.voiceNote':
    'В этой сборке ответ берётся из нажатия. Произнесённый в микрофон ответ пока не распознаётся как ответ.',
  'live.q.nobody':
    'Если за несколько секунд никто не ответит, агент засчитает вопрос в свой бюджет и продолжит: он может спросить ещё раз или передать номер человеку.',
  'live.q.choice': 'Ответить {char}',
  'live.q.sent': 'Ответ отправлен',

  'live.ended.title': 'Сеанс завершён.',
  'live.ended.reason.complete': 'Звонок закончился, и агент записал то, что у него было.',
  'live.ended.reason.cap':
    'Достигнут лимит сеанса в {cap} секунд, поэтому соединение с распознавателем закрыто. Этот лимит — бюджетное правило развёртывания, а не сбой.',
  'live.ended.reason.stopped': 'Вы его остановили.',
  'live.ended.reason.error': 'Конвейер остановился с ошибкой.',
  'live.ended.reason.other': 'Завершён: {reason}.',
  'live.ended.tally': 'записано {captures} · без вопросов {silent} · вопросов {questions}',
  'live.ended.waiting': 'Ожидание итога от сервера…',
  'live.again': 'Начать ещё один сеанс',

  'live.fail.consent_absent':
    'Сервер отказался открыть сеанс, потому что вместе с ним не было записано согласие. Микрофон не затронут, ничего не записано.',
  'live.fail.server_unreachable':
    'Сервис Readback недоступен. Сеанс не открыт, микрофон не затронут.',
  'live.fail.server_refused':
    'Сервис Readback отказался открыть сеанс. Его собственная причина приведена ниже.',
  'live.fail.no_live_capture':
    'Сеанс открылся, но у этого сервера нет ключа распознавания или его дневной бюджет исчерпан, поэтому он не смог услышать этот микрофон. Микрофон не открывался.',
  'live.fail.mic_denied':
    'Браузер отказал в доступе к микрофону. Разрешите его для этого сайта в адресной строке и начните снова.',
  'live.fail.mic_missing': 'На этом устройстве не найден микрофон.',
  'live.fail.mic_busy': 'Микрофон занят другим приложением или другой вкладкой.',
  'live.fail.mic_unsupported':
    'Этот браузер не может захватывать звук здесь. Нужны защищённый источник (https или localhost) и поддержка AudioWorklet.',
  'live.fail.audio_refused':
    'Сервер не принял аудиосокет, поэтому звук не отправлялся. Код закрытия приведён ниже.',
  'live.fail.upstream_refused':
    'Распознаватель речи отклонил соединение. Сеанс завершился до того, как что-либо было услышано.',
  'live.fail.connection_lost':
    'Соединение с сервером оборвалось посреди сеанса. Сеанс окончен; всё уже записанное есть в записи.',
  'live.fail.device_lost': 'Микрофон перестал передавать звук посреди сеанса.',
  'live.fail.detail': 'Подробность',
} as const;

export const ru: Messages = catalog satisfies Translated<typeof en, typeof catalog>;
