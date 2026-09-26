/* The English catalog. This file is the source of truth for the key set: every
 * other catalog is type-checked against it, so adding a key here breaks the
 * build until uz.ts and ru.ts carry it too. That is the intended workflow.
 *
 * WHAT THIS IS NOT.
 * ----------------
 * Readback's speech pipeline is English. The solver, the NATO alphabet, the
 * carrier phrases, the confusion table and the accent measurements are all
 * English-language, and ARCHITECTURE.md pins `"language_codes": ["en"]`. This
 * catalog localises the OPERATOR'S INTERFACE and nothing else. No string in
 * here may imply that the agent listens in any language other than English --
 * see `lang.switcher.note` and `lang.notice.short`, which exist specifically to
 * say so out loud at the moment a reader could be misled.
 *
 * `as const` is load-bearing. Without it every value widens to `string`, and
 * the placeholder-parity check in types.ts has no literal to read.
 */

export const en = {
  // ------------------------------------------------------------ languages --

  /* Endonyms. These are deliberately IDENTICAL in all three catalogs: a reader
   * who has landed in a language they cannot read has to be able to find their
   * own on the list, and "Russian" written in Uzbek does not help them. */
  'lang.name.en': 'English',
  'lang.name.uz': 'Oʻzbekcha',
  'lang.name.ru': 'Русский',

  /* The switcher's accessible name. "Interface" is doing real work here and is
   * not padding -- it is the shortest honest name for what the control changes,
   * and it is the first thing a screen reader announces. */
  'lang.switcher.label': 'Interface language',

  /* The full statement, attached to the switcher with aria-describedby. */
  'lang.switcher.note':
    'This changes the interface language only. Readback listens to the call in English and asks its question in English.',

  /* The visible short form, shown beside the switcher whenever the interface is
   * not in English -- the one moment the arrangement could be misread as
   * multilingual speech recognition. */
  'lang.notice.short': 'Interface only — the agent listens in English.',

  // ---------------------------------------------------------------- shell --

  'app.skipToContent': 'Skip to content',
  /* The route boundary's one sentence (App.tsx RouteFallback). It was
   * referenced before it existed, which tsc -b reported and vite build did
   * not: esbuild strips types and never sees the missing key. */
  'app.routeFailed': 'This screen could not be drawn. Reload the page, and tell us if it keeps happening.',

  // --------------------------------------------------------------- topbar --

  'topbar.nav.label': 'Main',
  'topbar.signedIn': 'Signed in',
  'topbar.account': 'Account',
  'topbar.signOut': 'Sign out',
  'topbar.logIn': 'Log in',
  'topbar.getKey': 'Get a key',

  // ----------------------------------------------------------- navigation --

  /* The signed-in rail (components/Sidebar.tsx). Six destinations, and the
   * seventh string is the rail's own accessible name -- there are two <nav>
   * landmarks on a signed-in page now, so neither may go unnamed.
   *
   * There is deliberately NO 'nav.account': the rail reuses 'topbar.account'.
   * It is the same word for the same link to the same route, and this catalog
   * already carries two identical "{n} captures" plural sets because somebody
   * added a second rather than reusing the first. */
  'nav.sidebar.label': 'Sections',
  'nav.live': 'Live',
  'nav.record': 'Record',
  'nav.sessions': 'Sessions',
  'nav.formats': 'Formats',
  'nav.demo': 'Demo',

  /* The rail's one figure, spelled out. The eye gets "117/146" in mono; a
   * screen reader gets this, because "117 slash 146" is not a sentence. */
  'nav.record.silent': '{silent} of {total} identifiers written without asking',

  /* ROUTES THAT DO NOT EXIST YET.
   *
   * The rail names six destinations and four of them have no screen behind
   * them. The alternatives were both worse: hiding the link makes the rail
   * disagree with itself the moment a screen lands, and letting the link fall
   * through to the catch-all drops a signed-in operator on the marketing page,
   * which reads as a bug rather than as an absence. So the route exists, is
   * reachable, and says plainly that it is not built -- the same rule the
   * record's empty state follows: nothing is shown here rather than something
   * invented. */
  'route.pending.eyebrow': 'Not built yet',
  'route.pending.live.title': 'The live call view is not built yet.',
  'route.pending.live.body':
    'This is where an identifier fills in one character at a time while the call is running. Nothing is shown here in its place, because there is no live capture to show: an animated mock-up of a call that is not happening is the one thing this product may not do.',
  'route.pending.sessions.title': 'The session list is not built yet.',
  'route.pending.sessions.body':
    'Sessions are already on the record, grouped under the identifiers they produced. A separate list of them, with its own filters and its own date range, is not.',
  'route.pending.formats.title': 'The format reference is not built yet.',
  'route.pending.formats.body':
    'Which formats are switched on for your organisation, and what each one checks, is on the account screen today. The reference that explains how each check digit is computed is not.',
  'route.pending.toRecord': 'Go to the record',

  /* The session list (DESIGN-BRIEF 4.4, the team-leader view). Drawn from a
   * session query, so the calls that correctly captured nothing are on it. */
  'sessions.title': 'Sessions',
  'sessions.intro':
    'Every call this organisation ran, newest first — including the ones that correctly captured nothing. Open one to see what the pipeline wrote down, which decisions were silent and which asked, and the audit of how. There is no transcript.',
  'sessions.loading': 'Loading sessions…',
  'sessions.failed': 'The session list could not be loaded. The record runs on the API; check that it is up.',
  'sessions.empty': 'No sessions yet. Run a call or a demo fixture, and it appears here.',
  'sessions.more': 'Older sessions are not shown — this is the latest page.',
  'sessions.loadMore': 'Show older sessions',
  'sessions.source.live': 'live',
  'sessions.source.replay': 'fixture',
  'sessions.source.unknown': 'session',
  'sessions.count.captured': '{n} captured',
  'sessions.count.silent': '{n} silent',
  'sessions.count.asked': '{n} asked',
  'sessions.count.flagged': '{n} flagged',
  'sessions.meta.started': 'Started',
  'sessions.meta.ended': 'Ended',
  'sessions.meta.ongoing': 'Still open',
  'sessions.meta.regime': 'Confidence regime',
  'sessions.section.captures': 'What it captured',
  'sessions.section.questions': 'Questions it asked',
  'sessions.section.audit': 'Decision timeline',
  'sessions.rackTitle': 'What it wrote down',
  'sessions.noCaptures': 'This call captured nothing — the right outcome when there was no identifier to hear.',
  'sessions.noTranscript':
    'No transcript exists. The record keeps what was captured and the audit of how it was reached, and nothing that could reconstruct the conversation.',
  'sessions.q.position': 'Position {n}',
  'sessions.q.answered': 'answered {char}',
  'sessions.q.timedout': 'no answer',
  'sessions.detail.loading': 'Loading the session…',
  'sessions.detail.failed': 'This session could not be loaded.',

  /* The format reference. Per-format copy is reused from account.format.*; these
   * are only the page chrome and the shape-strip labels. */
  'formats.title': 'Formats',
  'formats.intro':
    'The identifier formats Readback can hear, and how each one proves itself. Every format carries a check that catches a misheard character before it is written — the reason a captured number can be trusted, or a doubt raised out loud.',
  'formats.legend.letter': 'letter',
  'formats.legend.digit': 'digit',
  'formats.legend.check': 'check',
  'formats.example': 'A valid example',
  'formats.method': 'How the check works',
  'formats.advantage': 'What the check buys',
  'formats.sensitive': 'Identifies a person',
  /* Who says this out loud, on a call, today. A format reference that shows
   * only arithmetic leaves a visitor to work out whether the product is for
   * them; this line answers it before they have to. */
  'formats.who': 'Who reads it aloud',
  'formats.who.iso6346':
    'Shipping lines, freight forwarders, port and depot desks. Read out on booking, gate-in and damage-claim calls, usually from a yard on a phone in the wind.',
  'formats.who.iban':
    'Bank and payment operations. Dictated when a transfer is set up or a mandate is corrected, where one wrong character is a returned payment and a call back.',
  'formats.who.vin':
    'Insurers, dealers and roadside assistance. Read off a windscreen at the kerb: seventeen characters, outdoors, once.',
  'formats.who.nhs':
    'Clinics, surgeries and patient-facing scheduling. Spoken by the patient, who may be in pain, and where the wrong record is the wrong person.',
  'formats.who.luhn':
    'Card operations. Luhn catches a single wrong digit but cannot say which one, so a card is never repaired here: it is read back, or handed to a person.',
  /* "Try one": the solver's own arithmetic on whatever is typed. Nothing typed
   * here is kept. */
  'formats.try.title': 'Try one',
  'formats.try.format': 'Format',
  'formats.try.value': 'Identifier',
  'formats.try.placeholder': 'Type or paste one',
  'formats.try.button': 'Check',
  'formats.try.valid': 'Valid. The check agrees.',
  'formats.try.length': 'Wrong length: {expected} characters expected, {got} given.',
  'formats.try.badChar': 'Position {n} cannot hold “{char}”.',
  'formats.try.checkFails': 'Every character is legal here, and the check still does not agree — one of them was misheard or mistyped.',
  'formats.try.failed': 'The server did not answer.',

  /* The demo screen. Every rack on it is the answer to POST /api/demo/replay;
   * the fixture copy describes the INPUT and never the outcome, because the
   * screen does not know the right answer and must not pretend to. */
  'demo.title': 'Run a fixture through the pipeline.',
  'demo.intro':
    'Eight fixtures in the socket’s own wire format, each pushed through the same runner a live call goes through — the tape, the detector, the solver, the decider. Four contain a container number. Four contain no identifier at all, and the right answer for those is silence.',
  'demo.group.captures': 'Four that contain an identifier',
  'demo.group.refusals': 'Four that must stay silent',
  'demo.run': 'Run',
  'demo.runAgain': 'Run again',
  'demo.running': 'Running the fixture',
  'demo.failed': 'The server did not answer. The demo runs on the API; check that it is up.',
  'demo.nothing': 'Nothing was captured.',
  'demo.nothingRight': 'Nothing was captured — the right answer for this one.',
  'demo.unexpected': 'Something was captured. That is a false capture, and it is shown rather than hidden.',
  'demo.rackTitle': 'What the pipeline wrote down',
  'demo.fx.clean.title': 'A clean container number',
  'demo.fx.clean.body':
    'MSKU 4158005 dictated in the NATO alphabet, in one turn. Four words change across the partials before they settle.',
  'demo.fx.straddle.title': 'The same number over three turns',
  'demo.fx.straddle.body': 'A 1.9-second hesitation inside the code breaks it across turn boundaries.',
  'demo.fx.visible.title': 'M heard as N',
  'demo.fx.visible.body':
    'One letter substituted at position 1. Different residue classes, so the ISO 6346 check digit fails.',
  'demo.fx.blind.title': 'K heard as A — and the check digit still passes',
  'demo.fx.blind.body':
    'Position 3 substituted with a letter in the same residue class mod 11. The wrong number is arithmetically valid.',
  'demo.fx.conversation.title': '126 seconds of talk, no identifier',
  'demo.fx.conversation.body':
    'A shipping-desk conversation seeded with the words that normalise to characters anyway.',
  'demo.fx.dates.title': 'Two dates in one breath',
  'demo.fx.dates.body':
    'A collection window. “to” reads as the digit 2 and welds the dates into one thirteen-digit run.',
  'demo.fx.meter.title': 'A sixteen-digit meter reading',
  'demo.fx.meter.body':
    'Dictated at a utilities desk. No carrier phrase, no identifier — sixteen digits that look like a card number.',
  'demo.fx.phone.title': 'A phone number in the middle of a call',
  'demo.fx.phone.body': 'An eleven-digit UK mobile, given in passing. No carrier phrase, no identifier.',

  // ------------------------------------------------------- capture states --

  /* The state vocabulary. One meaning per colour, and the word is never
   * optional: the five state colours sit between 8.0 and 9.3 greyscale
   * luminance and are one grey to a monochrome display. Paired with tokens and
   * icons in lib/api.ts. */
  'capture.state.heard': 'Heard, not settled',
  'capture.state.repaired': 'Quietly repaired',
  'capture.state.asking': 'Needs one thing from you',
  'capture.state.settled': 'Settled',
  'capture.state.flagged': 'Flagged',

  // ----------------------------------------------------------------- rack --

  'rack.empty': 'Nothing yet. The rack fills the moment somebody reads out a code.',
  'rack.asked.none': 'asked nothing',
  'rack.asked.count': 'asked {n}×',

  /* The spoken readout. A screen reader gets the whole identifier, its state and
   * its repairs as one utterance rather than as thirty fragments the listener
   * has to reassemble. {heard} and {written} are identifier characters and are
   * substituted verbatim -- see THE IDENTIFIER RULE in Rack.tsx. */
  /* Capitalised because it is only ever used sentence-initially, and the
   * readout joins its parts with ". ". The English this replaced read
   * "... Settled. position 8 heard as 9." -- a lowercase word after a full
   * stop, which a screen reader renders as a run-on. Fixed here rather than
   * translated faithfully into three languages. */
  'rack.readout.position': 'Position {n}',
  'rack.readout.blank': 'blank',
  'rack.readout.repaired': '{position} heard as {heard}, written as {written}.',
  'rack.readout.asked': '{position} is the character in question.',
  'rack.readout.locked': '{position} is computed, not heard.',

  /* Plural set. English needs two of these four; Russian needs three (21 is
   * "one", 22 is "few", 25 is "many"), which is why the count is resolved
   * through Intl.PluralRules rather than by `n === 1`. The categories a
   * language does not use repeat its `other` form, which is correct rather
   * than lazy -- CLDR says those forms are genuinely identical here. */
  'rack.readout.questions.one': '{n} question.',
  'rack.readout.questions.few': '{n} questions.',
  'rack.readout.questions.many': '{n} questions.',
  'rack.readout.questions.other': '{n} questions.',

  // --------------------------------------------------------------- legend --

  'rack.legend.empty.label': 'Empty',
  'rack.legend.empty.note': 'The format knows this position is coming. Nobody has said it yet.',
  'rack.legend.provisional.note': 'What the recogniser delivered, still open to being overruled.',
  'rack.legend.settled.note': 'Agreed by the arithmetic and written down.',
  'rack.legend.repaired.note':
    'The format overruled the microphone. Both characters stay on the row.',
  'rack.legend.asked.note': 'The one character worth interrupting a call for.',
  'rack.legend.locked.label': 'Locked by the format',
  'rack.legend.locked.note': 'Computed from the positions before it. Audio cannot move it.',

  // ------------------------------------------------------------- transport --

  /* One sentence per ApiErrorKind, and the kinds stay APART.
   *
   * lib/session.ts already distinguishes offline from timeout from unauthorized
   * -- three different things that a single "Something went wrong" would throw
   * away. Each of these names the cause and says what to do next, because an
   * error that only names the cause leaves the reader holding it.
   *
   * These replace `ApiFailure.message` on the screens that render them. That
   * message is written by the server, in English, and cannot be localised from
   * here; the kind can be, and the kind is what the reader needs. Screens key
   * off `failure.kind`, never `failure.message`. */
  'error.offline': 'Cannot reach the Readback service. Check your connection, then try again.',
  'error.timeout':
    'The Readback service did not answer in time. It may be starting up — wait a moment and try again.',
  'error.badRequest':
    'Some of those details were not accepted. Correct the fields above and send it again.',
  'error.unauthorized':
    'That email and password did not match an account. Check both, or get a key if you do not have an account yet.',
  'error.notFound': 'That is not there. Reload the page, and tell us if it keeps happening.',
  'error.conflict':
    'An account already exists for that email. Log in instead, or use another address.',
  'error.rateLimited': 'Too many attempts. Wait a minute, then try again.',
  'error.server':
    'The Readback service had a problem at its end. Nothing was saved — try again shortly.',
  'error.malformed':
    'The Readback service answered with something this page could not read. Try again, and tell us if it keeps happening.',

  /* The rate limit with a figure from the body. Vague past a minute on purpose:
   * a wait printed to the second is a wait somebody sits and watches. */
  'error.rateLimited.wait': 'Too many attempts. Try again {when}.',
  'wait.moment': 'in a few seconds',
  'wait.aboutMinute': 'in about a minute',
  'wait.seconds.one': 'in about {n} second',
  'wait.seconds.few': 'in about {n} seconds',
  'wait.seconds.many': 'in about {n} seconds',
  'wait.seconds.other': 'in about {n} seconds',
  'wait.minutes.one': 'in about {n} minute',
  'wait.minutes.few': 'in about {n} minutes',
  'wait.minutes.many': 'in about {n} minutes',
  'wait.minutes.other': 'in about {n} minutes',

  // ------------------------------------------------------------ form parts --

  /* SPACING RULE for every key split into .before/.mid/.after around a link, a
   * mono figure or a <strong>: the parts are joined with EXACTLY ONE SPACE by
   * the component, and each translation is written so that reads correctly. No
   * catalog value carries a leading or trailing space -- an invisible space is
   * the kind of thing that survives review and then goes missing in an edit. */
  'field.required': '(required)',
  'field.reveal.show': 'Show {label}',
  'field.reveal.hide': 'Hide {label}',
  'button.busy': 'Working',

  // ----------------------------------------------------------------- auth --

  'auth.login.title': 'Log in',
  'auth.login.blurb': 'Reach the captures for your company.',
  'auth.login.submit': 'Log in',
  'auth.login.busy': 'Checking',
  'auth.login.footLead': 'No account yet?',
  'auth.login.footLink': 'Get a key',

  'auth.signup.title': 'Get a key',
  'auth.signup.blurb': 'One account per company. Everyone else joins it by invitation.',
  'auth.signup.submit': 'Create account',
  'auth.signup.busy': 'Creating',
  'auth.signup.footLead': 'Already have one?',
  'auth.signup.footLink': 'Log in',

  'auth.field.name': 'Your name',
  'auth.field.company': 'Company',
  'auth.field.email': 'Work email',
  'auth.field.password': 'Password',

  /* Cause and remedy in one line, in every language. "Invalid input" is not an
   * acceptable translation of any of these. */
  'auth.error.name': 'Enter your name.',
  'auth.error.company': 'Enter your company.',
  'auth.error.email.empty': 'Enter your work email.',
  'auth.error.email.shape':
    'That does not look like an email address. It needs a name, an @ and a domain, like maria@company.com.',
  'auth.error.password.choose': 'Choose a password.',
  'auth.error.password.enter': 'Enter your password.',

  // ------------------------------------------------------------- password --

  /* THE RULE. It has to stay TRUE once translated, not merely fluent: ten
   * characters, and at least one of each of three classes. HAS_SYMBOL in
   * Auth.tsx is "neither a letter nor a number", so a space counts -- which is
   * why the third class must stay broad in every language. Do not translate
   * this into a different rule. */
  'pw.rule': 'At least {min} characters, with a letter, a number and a symbol.',
  'pw.class.letter': 'a letter',
  'pw.class.number': 'a number',
  'pw.class.symbol': 'a symbol',
  /* The joiner for the class list. Deliberately not Intl.ListFormat: format.ts
   * is the only place allowed to build an Intl object, and a three-item list
   * does not justify reopening the pin. */
  'pw.list.and': 'and',

  'pw.problem.shortCount': 'Use at least {min} characters. This one has {have}.',
  'pw.problem.add': 'Add {missing}.',

  /* The local scorer's own wording (lib/password.ts, held in step with
   * server/password.py by tests/test_password_parity.py). Both of those produce
   * English; PasswordStrength matches what they produce and renders these
   * instead. An unrecognised line falls through as the English it already was,
   * which is visible rather than silent. */
  'pw.problem.short': 'Use at least {min} characters.',
  'pw.problem.long': 'Keep it under {max} characters.',
  'pw.problem.include': 'Include {missing}.',
  'pw.problem.context.email': 'Do not put your email in your password.',
  'pw.problem.context.name': 'Do not put your name in your password.',
  'pw.problem.context.company': 'Do not put your company in your password.',
  'pw.problem.commonBolted': 'It is a very common password with numbers or symbols bolted on.',
  'pw.problem.commonPlain': 'It is one of the most common passwords in use.',
  'pw.problem.keyboardRun': 'It contains a straight run across the keyboard.',
  'pw.problem.repeats': 'It repeats the same character three or more times.',
  'pw.problem.fewDistinct': 'It uses too few distinct characters.',
  'pw.problem.wordNumberSymbol':
    'Word-then-number-then-symbol is the first thing an attacker tries.',
  'pw.suggestion.length':
    'Length beats cleverness — four unrelated words are stronger than one word with substitutions.',
  'pw.suggestion.addMore': 'Add a few more characters to make it comfortably strong.',

  /* THE STRENGTH WORDS.
   *
   * strengthOf() in lib/api.ts gives each level a colour, and those colours
   * measure 8.0 to 12.7 greyscale luminance -- one grey to a monochrome
   * display. The word is therefore the carrier, not the decoration, and a
   * translation that blurs two levels into one word breaks the meter. Four
   * distinct words, plus a fifth for the breach verdict, which is a different
   * claim from "weak" and must not be folded into it. */
  'pw.strength.idle': 'Password strength',
  'pw.strength.weak': 'Weak',
  'pw.strength.fair': 'Fair',
  'pw.strength.good': 'Good',
  'pw.strength.strong': 'Strong',
  'pw.strength.breached': 'Found in a breach',

  'pw.breach.count.one': 'This password appears in {n} known breach.',
  'pw.breach.count.few': 'This password appears in {n} known breaches.',
  'pw.breach.count.many': 'This password appears in {n} known breaches.',
  'pw.breach.count.other': 'This password appears in {n} known breaches.',
  'pw.breach.advice': 'Attackers try leaked passwords first — pick a different one.',
  'pw.breach.clean': 'Not in any known breach.',
  'pw.breach.unchecked': 'Not compared against known breaches — the service did not answer.',

  // -------------------------------------------------------- account: shell --

  'account.eyebrow': 'SETTINGS',
  'account.title': 'Account',
  'account.org.unknown': 'Organisation unknown',
  'account.org.yours': 'your organisation',
  'account.loading.session': 'Checking your session',
  'account.loading.team': 'Loading your team',
  'account.loading.usage': 'Loading usage',
  'account.unreachable':
    'Cannot reach the Readback service. Everything below is the last thing known about this account rather than the current state of it, and nothing you change here will reach the server.',
  'account.refresh': 'Refresh',
  'account.refreshing': 'Refreshing',
  'account.index.label': 'Account sections',

  'account.profile.title': 'Profile and team',
  'account.profile.lede':
    'Everybody here sees the same captures. Roles decide who can change the settings on this screen.',
  'account.formats.title': 'Formats',
  'account.formats.lede':
    'Which identifier types Readback listens for. The agent stays silent until it hears one of these being read out.',
  'account.vocab.title': 'Vocabulary pack',
  'account.vocab.lede':
    'The words the format cannot predict. A check digit constrains characters; it knows nothing about the word Maersk.',
  'account.consent.title': 'Consent',
  'account.consent.lede':
    'Readback listens in the background of live calls. This section is not boilerplate, and it is the part of the product worth reading before the rest.',
  'account.usage.title': 'Usage',
  'account.usage.lede':
    'Listening seconds against the plan, and what this screen can honestly account for.',

  // ----------------------------------------------------- account: 01 team --

  'account.team.empty':
    'No team to show. The account could not be read, so there is nobody to list. Try Refresh above.',
  'account.team.you': 'YOU',
  'account.team.invitedHere': 'INVITED HERE ONLY',
  'account.team.roleColumn': 'ROLE',
  'account.team.cannotRemoveSelf': 'You cannot remove yourself.',
  'account.team.remove': 'Remove {name}',
  'account.team.onlyYou':
    'Only you so far. Invite the people who take these calls, so the captures land somewhere other than one browser.',

  'account.role.owner': 'Owner',
  'account.role.owner.can': 'Everything, including billing and this screen.',
  'account.role.admin': 'Admin',
  'account.role.admin.can': 'This screen, the team, and every capture.',
  'account.role.operator': 'Operator',
  'account.role.operator.can': 'Every capture. Cannot change formats, consent or the team.',

  'account.invite.title': 'Invite somebody',
  'account.invite.name': 'Name',
  'account.invite.nameHint': 'Optional. Without it the invitation is listed by address.',
  'account.invite.email': 'Email',
  'account.invite.role': 'Role',
  'account.invite.submit': 'Add to the list',
  'account.invite.duplicate': 'Somebody with that address is already on the team.',

  /* emailProblem() in lib/account.ts returns English prose with no code beside
   * it. These are matched against what it returns; an unmatched string is shown
   * as the English it already was. */
  'account.email.empty': 'Enter an email address.',
  'account.email.space': 'An email address cannot contain a space.',
  'account.email.at': 'That needs one @ with a name in front of it.',
  'account.email.domain': 'The part after the @ does not look like a domain.',

  'account.pending.team':
    'Invitations, role changes and removals stay in this browser tab. Nothing is emailed and nothing is saved until the team endpoints land:',

  // -------------------------------------------------- account: 02 formats --

  'account.formats.prose1':
    'Readback does not hear better than the recogniser underneath it. It knows what a valid answer is allowed to be. That is why the check digit matters more than the microphone, and why the strength of the arithmetic is printed on every row below.',
  /* Three parts, because the two phrases between them are the capture
   * vocabulary itself and are rendered from capture.state.* rather than
   * respelled here. */
  'account.formats.prose2.lead':
    'The colour on each row is not a grade for the standard. It is a prediction about how often you will be interrupted:',
  'account.formats.prose2.mid':
    'means the arithmetic absorbs most mishearings without anyone being asked, and',
  'account.formats.prose2.tail':
    'means the agent will speak more often. Those are the same two words, and the same two colours, the capture rack uses.',

  'account.formats.shape': 'Shape',
  'account.formats.length': 'Length',
  'account.formats.check': 'Check digit',
  'account.formats.onRecord': 'On record',
  'account.formats.noCheck': 'None. Nothing for the solver to check against.',
  'account.formats.notCounted': 'Not counted, sessions unavailable',
  'account.formats.noCaptures': 'No captures yet',
  'account.formats.captures.one': '{n} capture',
  'account.formats.captures.few': '{n} captures',
  'account.formats.captures.many': '{n} captures',
  'account.formats.captures.other': '{n} captures',
  'account.formats.cannot': 'WHAT THE ARITHMETIC CANNOT DO',
  'account.formats.sensitive.before': 'See',
  'account.formats.sensitive.after': 'for what that means.',
  'account.pending.formats':
    'Switching a format on or off applies to this browser tab only, and the agent on your calls is unaffected until the format endpoint lands:',

  /* The five format rows. `standard` and `shape` are deliberately absent: one is
   * the name a standards body gave itself and the other is a machine pattern,
   * and translating either would make it wrong. */
  'account.format.iban.name': 'IBAN',
  'account.format.iban.length': '16 to 34 characters, fixed per country',
  'account.format.iban.check': 'Two check digits, mod-97-10',
  'account.format.iban.strength':
    'The strongest arithmetic here. Two check digits over the whole string.',
  'account.format.iban.measured.1':
    'Error budget 0.0023 unconstrained, 0.0399 constrained: 17.1x, the largest gain measured.',
  'account.format.iban.measured.2': 'Spread across the eight accents tested: 1.14x.',
  'account.format.iban.note':
    'The country code fixes the length before the arithmetic runs, so a dropped character is caught by the shape rather than by the checksum. Ten country lengths are known to the validator; an IBAN from anywhere else is checked by mod-97 alone.',

  'account.format.iso6346.name': 'Container',
  'account.format.iso6346.length': '11 characters',
  'account.format.iso6346.check': 'Check digit, sum of value(c) x 2^i, mod 11, mod 10',
  'account.format.iso6346.strength':
    'Strong, with twelve known blind spots the agent asks about by hand.',
  'account.format.iso6346.measured.1':
    'Error budget 0.0047 unconstrained, 0.0692 constrained: 14.9x.',
  'account.format.iso6346.measured.2':
    'The acoustic model is worth 21 points of silent repair here, and zero accuracy.',
  /* Split around the congruence classes, which are arithmetic and are rendered
   * as mono data rather than as prose. They also cannot live inside a catalog
   * string: `{A K U}` reads as a placeholder to ParamNames in types.ts, which
   * would make t() demand parameters no caller has. */
  'account.format.iso6346.note.before':
    'Characters congruent mod 11 are mathematically invisible to this check digit:',
  'account.format.iso6346.note.after':
    'Twelve of those pairs are also acoustically confusable, B/V, K/A, F/P and nine more, which is 5.3% of measured confusion weight. Readback asks about all twelve whenever the recogniser marks the character doubtful — under per-character confidence that caught 22 of 23 such mishears in a 400-number bench. Under block-level confidence (one number for a whole welded word, the common case on the live socket) it cannot see which character to doubt, and a mishear the arithmetic accepts is written as heard: 13 of 400 in the same bench. Silence there is not confidence; it is arithmetic that cannot see, and it is measured.',

  'account.format.nhs.name': 'NHS number',
  'account.format.nhs.length': '10 digits',
  'account.format.nhs.check': 'Check digit, weights 10 down to 2, mod 11',
  'account.format.nhs.strength':
    'Strong, and the digits-only alphabet keeps the confusion set small.',
  'account.format.nhs.measured.1':
    'The acoustic model is worth 64 points of silent repair here, the largest of the formats measured.',
  'account.format.nhs.note':
    'Ten digits and no letters, so most of the confusion table does not apply; 5 against 9 at weight 0.50 is the heaviest pair that does. A remainder of 10 has no valid check digit, so those numbers are rejected outright rather than repaired quietly.',
  'account.format.nhs.sensitive': 'A captured NHS number identifies a patient.',

  'account.format.vin.name': 'VIN',
  'account.format.vin.length': '17 characters, check digit at position 9',
  'account.format.vin.check': 'Check digit at position 9, transliterated, weighted, mod 11',
  'account.format.vin.strength':
    'Strong, and the alphabet itself removes the worst confusion before the arithmetic runs.',
  'account.format.vin.note':
    'The VIN alphabet excludes I, O and Q. That deletes the heaviest confusable pair in the measured table, O against 0 at weight 0.95, before the check digit is ever reached. A VIN whose position 9 does not agree is not repaired quietly; it goes to a person.',

  'account.format.luhn.name': 'Card',
  'account.format.luhn.length': '13 to 19 digits',
  'account.format.luhn.check': 'Check digit, Luhn mod 10 with alternate doubling',
  'account.format.luhn.strength':
    'The weakest arithmetic here. Expect the agent to interrupt more often.',
  'account.format.luhn.note':
    'Luhn catches every single-digit substitution and every adjacent transposition except 0 next to 9, and it carries no length rule of its own, so a dropped digit leaves a shorter number the sum can still accept. More questions on card numbers is the arithmetic being honest, not the microphone failing.',
  'account.format.luhn.sensitive':
    'A captured card number is stored in full, like every other captured identifier.',

  // ----------------------------------------------- account: 03 vocabulary --

  'account.vocab.of': 'of {max} terms',
  'account.vocab.barLabel': 'Vocabulary pack, terms used',
  'account.vocab.barValue': '{used} of {max} terms',
  'account.vocab.prose.a': 'Your own carrier prefixes, part numbers and site names go here, up to',
  'account.vocab.prose.b': 'terms of',
  'account.vocab.prose.c':
    "characters each. Both ceilings are AssemblyAI's, not ours: the pack is handed to the recogniser verbatim when the session opens, and the platform will not take a longer one. Readback cannot raise either number, so it shows you the count against them instead of pretending the limit is a design choice.",
  'account.vocab.add': 'Add a term',
  'account.vocab.hint': 'of {max} characters.',
  'account.vocab.addButton': 'Add term',
  'account.vocab.full': 'The pack is full at {max} terms. Remove one to make room.',
  'account.vocab.empty':
    'The pack is empty. Add the words the arithmetic cannot predict, starting with the carrier prefixes and site names your callers say most.',
  'account.vocab.remove': 'Remove {term} from the pack',
  'account.vocab.error.empty': 'Type a term before adding it.',
  'account.vocab.error.tooLong': 'That is {n} characters. The platform limit is {max}.',
  'account.vocab.error.duplicate': 'That term is already in the pack.',
  'account.vocab.error.full': 'The pack holds {max} terms. Remove one to make room.',
  'account.pending.vocab':
    'The pack lives in this browser tab and is not sent to any recognising session yet:',

  // -------------------------------------------------- account: 04 consent --

  'account.consent.lead':
    'The obvious worry about a product that listens to calls is what it keeps. The answer is almost nothing, and that was an architecture decision rather than a policy one: the conversation is never written down, so there is nothing to be careless with later.',

  'account.ledger.audio.kicker': 'NEVER STORED',
  'account.ledger.audio.title': 'Raw audio',
  'account.ledger.audio.body':
    'Frames are held only for as long as the recogniser needs to turn them into characters, and are written nowhere. There is no recording of your call inside Readback to export, subpoena or leak.',
  'account.ledger.talk.kicker': 'NEVER PERSISTED',
  'account.ledger.talk.title': 'The conversation',
  'account.ledger.talk.body':
    'Readback does not transcribe the call and does not summarise it. What was said around the number is gone the moment the number is settled. There is no transcript on this screen, in the rack, or in the database, and no view was left out that would show you one.',
  'account.ledger.id.kicker': 'STORED',
  'account.ledger.id.title': 'The captured identifier',
  'account.ledger.id.body':
    'The number itself, which format it was, whether it settled or was flagged, how many times the agent had to interrupt, and when. That is the whole record, and it is what the rack is drawing.',

  'account.consent.seam':
    'Everything above is fixed by how the thing is built. The two settings below are not, and they are yours.',
  'account.consent.disclosure.title': 'How callers are told',
  'account.consent.disclosure.body':
    'Somebody on the call has to know an assistant is listening. Choose who says so.',
  'account.disclosure.announces.label': 'Readback announces itself',
  'account.disclosure.announces.detail':
    'One spoken line at the start of the call, in English, before anything is captured: this call uses an assistant that writes down reference numbers.',
  'account.disclosure.yours.label': 'Your own notice covers it',
  'account.disclosure.yours.detail':
    'You tell callers yourself, in the recording announcement or the script you already use. Readback stays silent until a number is read out.',

  'account.consent.retention.title': 'How long a captured number is kept',
  'account.consent.retention.body':
    'This applies to the identifier and its record, because that is the only thing there is to keep. Shortening it does not reduce what is captured: the audio was never there to shorten.',
  'account.consent.retention.label': 'Retention',
  'account.retention.30': '30 days',
  'account.retention.90': '90 days',
  'account.retention.365': '365 days',
  'account.retention.forever': 'Until someone deletes it',

  'account.consent.card.before': 'Card (Luhn) is switched on in',
  'account.consent.card.after':
    '— a captured card number is stored in full, exactly like every other captured identifier, for as long as the retention above. Readback makes no claim about PCI scope; decide whether you want card numbers in this record before you leave that format on.',
  'account.consent.scope.before': 'Captures are scoped to',
  'account.consent.scope.mid': '— everybody on the team above can see them;',
  'account.consent.scope.after':
    'returns the captures for one organisation and has no wider form.',
  'account.pending.consent':
    'The two choices above are held in this browser tab. What is and is not stored does not depend on them, and is not a setting; the disclosure and retention endpoints are still to come:',

  // ---------------------------------------------------- account: 05 usage --

  'account.usage.of': 'of',
  'account.usage.notReported': 'not reported',
  'account.usage.barLabel': 'Listening seconds against the plan',
  'account.usage.noReading': 'No reading',
  'account.usage.note.none': 'The server has not reported an allowance for this plan.',
  'account.usage.note.settled': 'Inside the allowance for this period.',
  'account.usage.note.asking': 'Close to the allowance for this period.',
  'account.usage.note.flagged': 'Over the allowance for this period.',
  'account.usage.error': 'Captures could not be read, so nothing below is counted.',
  'account.usage.empty':
    'No captures on record. Once a call reaches Readback and somebody reads out a number, it appears here and in the rack. Nothing is counted until then.',
  'account.usage.captures': 'Captures',
  'account.usage.questions': 'Questions asked',
  'account.usage.silent': 'Settled in silence',
  'account.usage.counts.kicker': 'WHAT COUNTS',
  'account.usage.counts.body':
    'Listening seconds run from the moment a call is connected to Readback until it disconnects, including every second the agent says nothing. The silence is the mechanism, so billing only the seconds it spoke would be billing for the part that does not do the work. Nothing is counted while no call is connected, and a capture that ends up flagged still counts, because the listening happened either way.',
  'account.usage.derived.before': 'Captures, questions and silent settles are counted from',
  'account.usage.derived.after':
    '— the seconds above are derived from the settle timings on those same captures, which makes them a floor on your listening time rather than the whole of it. The meter reads NO READING rather than zero until an endpoint reports both halves, because a zero would be a claim and there is nothing behind it.',
  'account.pending.usage':
    'The plan allowance and the true listening total are not in the contract yet:',

  /* Hours and minutes, never decimal hours: nobody reconciles a bill against
   * 3.47 hours. Each language brings its own unit letters. */
  /* GET /api/usage: the deployment's daily ceiling beside the organisation's
   * own spend. ARCH 3.11's kill switch, made visible. */
  'account.usage.live.kicker': 'TODAY, THIS DEPLOYMENT',
  'account.usage.live.body':
    '{remaining} of {budget} listening time left today across every organisation on this deployment; {spent} spent since midnight UTC.',
  'account.usage.live.alarm': 'Close to the daily ceiling.',
  'account.usage.live.exhausted': 'The daily ceiling is reached: new live calls are refused until midnight UTC.',
  'account.usage.live.replay': 'Live capture is switched off (replay mode); nothing is being billed.',
  /* GET/PUT /api/vocabulary: the pack is stored and reaches the next call. */
  'account.vocab.sync.loading': 'Loading the pack…',
  'account.vocab.sync.saving': 'Saving…',
  'account.vocab.sync.saved': 'Saved. It reaches the recogniser on the next call.',
  'account.vocab.sync.error': 'The pack could not be saved; what you see is this tab’s copy.',
  'account.usage.secs': '{s}s',
  'account.usage.mins': '{m}m {s}s',
  'account.usage.hrs': '{h}h {m}m',

  // ------------------------------------------------------- account: parts --

  'parts.toggle.on': 'On',
  'parts.toggle.off': 'Off',
  'parts.bar.noReading': 'NO READING',
  // -------------------------------------------------------------- landing --

  /* The landing page (screens/Landing.tsx). One argument, told once: the
   * headline, the rack that shows it, three steps, the measured gain, the one
   * limit, and the ask. Every figure is interpolated from a constant with its
   * source in docs/, so no translation can change a claim.
   *
   * hero.title.a and .b are two keys on purpose: the pivot from denial to
   * reversal is a line break, and a translator owns where their sentence turns.
   * landing.rack.meta.* is also read by the record screen. */
  'landing.hero.title.a': 'It does not hear better.',
  'landing.hero.title.b': 'It knows what a valid answer is allowed to be.',
  'landing.hero.lede':
    'Readback listens to a call and writes down reference numbers: containers, IBANs, VINs, patient and card numbers. Most mishearings it repairs in silence. When it cannot, it asks about one character.',
  'landing.hero.scope':
    'It listens and asks in English. The language setting changes only the screen.',
  'landing.hero.demo': 'Run the demo',
  'landing.rack.title': 'Capture rack',
  'landing.rack.meta.captures.one': '{n} capture',
  'landing.rack.meta.captures.few': '{n} captures',
  'landing.rack.meta.captures.many': '{n} captures',
  'landing.rack.meta.captures.other': '{n} captures',
  'landing.rack.meta.questions.one': '{n} question',
  'landing.rack.meta.questions.few': '{n} questions',
  'landing.rack.meta.questions.many': '{n} questions',
  'landing.rack.meta.questions.other': '{n} questions',
  'landing.row.repaired.note':
    'position {position} · heard {heard} · wrote {written} · check digit {check} agrees',
  'landing.row.asking.question':
    'Position {position} — {a} for {aWord}, or {b} for {bWord}? Both leave check digit {check}, so the arithmetic will never object to either.',
  'landing.row.asking.note': 'one of the twelve blind pairs',
  'landing.row.settled.note': 'check digit {check} agrees · nothing to repair',
  'landing.how.title': 'How it works',
  'landing.how.step1.title': 'It mishears.',
  'landing.how.step1.body': 'On a bad line, five and nine are one sound. So are M and N, S and F.',
  'landing.how.step2.title': 'The format constrains the answer.',
  'landing.how.step2.body':
    'A container number carries a check digit computed from the rest. An IBAN carries mod‑97, a card carries Luhn.',
  'landing.how.step3.title': 'Usually one answer is legal.',
  'landing.how.step3.body':
    'Ten digits fit position {position}. One agrees with the check digit, and that one is written.',
  'landing.scene.label':
    'A container number in three dimensions. Position {position} was heard as {heard} and is written as {written}, because only {written} agrees with check digit {check}.',
  'landing.formats.title': 'The formats it reads',
  'landing.formats.label': 'Identifier formats, one per slide',
  'landing.formats.valid': 'A valid example',
  'landing.chart.label':
    'Error rate the system absorbs, unconstrained against constrained: ISO 6346 {isoFrom} to {isoTo}, IBAN {ibanFrom} to {ibanTo}.',
  'landing.chart.axis': 'Error rate absorbed',
  'landing.gain.title': 'The constraint absorbs fifteen times the error.',
  'landing.gain.body':
    'Measured across eight accents and about twelve million simulated captures: {iso}× on ISO 6346, {iban}× on IBAN. Knowing the accent is worth ±{value}, so nothing detects it.',
  'landing.gain.ratio.unconstrained': 'unconstrained',
  'landing.gain.ratio.constrained': 'constrained',
  'landing.limit.title': 'What it cannot see.',
  'landing.limit.body':
    'Twelve letter pairs, B and V among them, are invisible to the ISO 6346 check digit. They carry {share}% of measured mishearings. There the agent asks on any doubt, and a confident mishearing is written as heard. That residue is measured, not zero.',
  'landing.close.title': 'The rack is the whole interface.',
  'landing.close.body':
    'No transcript is kept. What comes back is the number, and how many times it had to interrupt.',

  // --------------------------------------------------------------- record --

  /* THE RECORD (screens/Dashboard.tsx). These keys arrived from a staging table
   * at the bottom of screens/DashboardParts.tsx, which carried all three
   * languages while this file was owned by another agent. They are keyed
   * exactly as they were staged, so the migration was a paste and a rename of
   * dt( to t( -- no string was retyped and no translation was re-derived.
   *
   * What is NOT here on purpose, because the catalog already has it and a
   * second spelling of one word is how two screens start disagreeing:
   *   capture.state.*               the five outcome words
   *   rack.asked.none / .count      "asked nothing" / "asked {n}×"
   *   rack.empty                    an empty rack says so itself
   *   error.*                       every ApiErrorKind
   *   landing.rack.meta.captures.*  the counted noun on the list header */

  'record.eyebrow': 'Record',
  'record.title': 'What was written down',
  'record.lede':
    'Every number on this screen came out of the pipeline. Nothing here is invented, and anything simulated says so.',

  // -- the one number
  'record.headline.definition': 'identifiers written without asking anybody anything',
  'record.headline.window': 'Last 30 days',
  'record.headline.retention': 'Captures are deleted after 30 days.',
  'record.headline.replay': 'replay fixtures',
  'record.headline.smallN':
    'Fewer than 20 captures, so there is no percentage here: a percentage over this few rows is a picture of the rows.',
  'record.headline.empty.title': 'No identifiers captured yet.',
  'record.headline.empty.body':
    'When there are, this number is how many were written without the agent asking anybody anything.',
  'record.headline.perId': '{v} questions per identifier',
  'record.headline.triple': '{asked} asked, {answered} answered, {timedOut} timed out',
  'record.headline.pair': '{asked} asked, {spoken} spoken out loud',
  'record.headline.asked': '{asked} asked',
  'record.headline.sr':
    '{silent} of {total} identifiers were written without the agent asking anybody anything.',

  // -- the silence indicator
  'record.held.rest': 'Listening. Nothing said yet.',
  'record.held.holding': 'Holding — {gate}.',
  'record.held.count': 'held {n}×',
  'record.held.caption': 'Every mark is a moment the agent decided not to speak.',
  'record.held.summary.caption':
    'positions from capture times; per-decision history is not retained.',
  'record.held.summary.count': '{captures} written · {spoken} spoken',
  'record.held.summary.say':
    'This session is finished. What it decided moment to moment was not kept.',
  'record.held.sr.live':
    'Silence indicator. Held {held} times. Spoke {spoke} times. Currently holding: {gate}',
  'record.held.sr.rest': 'Silence indicator. Nothing held yet, and nothing said yet.',
  'record.held.sr.summary':
    'Silence indicator, summary form. {captures} identifiers written, {spoken} spoken about. Mark positions come from capture times; the per-decision history was not retained.',

  /* The seven gates, verbatim from decider.may_speak(). They are the reasons
   * the agent had for not speaking, so they are sentences a person reads, not
   * error codes. */
  'record.held.gate.1': 'uncertain, not wrong',
  'record.held.gate.2': 'the turn has not ended',
  'record.held.gate.3': 'nothing downstream needs it',
  'record.held.gate.4': 'the line is not quiet',
  'record.held.gate.5': 'inside the 1.5 s politeness delay',
  'record.held.gate.6': 'already spoke once about this identifier',
  'record.held.gate.7': 'too late — more than 10 s since the last word',
  'record.held.gate.unknown': 'a gate this build has no name for',

  // -- the row
  'record.row.settledIn': '{s} s',
  'record.row.expand': 'What decided this',
  'record.row.none': 'No identifier read out.',
  'record.row.none.note': 'The agent listened and wrote nothing down.',
  'record.row.lengths':
    'The recogniser’s string is a different length from the written one, so the characters are not lined up one to one.',

  // -- the disclosure
  'record.detail.validatedBy': 'Validated by',
  'record.detail.secondSignal': 'Second signal',
  'record.detail.rung': 'Rung',
  'record.detail.handover': 'Handed over because',
  'record.detail.flagReason': 'Flagged because',
  'record.detail.positionCorrected': 'Position corrected',
  'record.detail.ruledOut': 'What it ruled out',
  'record.detail.ruledOut.absent': 'not carried on the list',
  'record.detail.questions': 'Questions',
  'record.detail.questions.unretained': 'detail no longer retained',
  'record.detail.question.line': 'position {position}, offered {offered}',
  'record.detail.question.answered': 'answered {char}',
  'record.detail.question.unanswered': 'no answer',
  'record.detail.question.spoken': 'spoken out loud',
  'record.detail.question.silent': 'never spoken',
  'record.detail.captureId': 'Capture ID',
  'record.detail.sessionId': 'Session ID',
  'record.detail.copy': 'Copy',
  'record.detail.copied': 'Copied',
  'record.detail.none': 'not recorded',
  'record.detail.loading': 'Reading the session…',
  'record.detail.unavailable':
    'The session record could not be read, so nothing is shown in its place.',

  // -- the session panel
  'record.session.title': 'Session',
  'record.session.open': 'open',
  'record.session.regime': 'Confidence regime',
  'record.session.regime.unknown': 'not yet determined',
  'record.session.none': 'No identifier read out.',
  'record.session.none.note':
    'The agent listened and wrote nothing down. That is a result, not a blank.',

  // -- honesty surfaces
  'record.replay.banner': 'Replay — these captures came from recorded fixtures, not a live call.',
  'record.stamp.replay': 'replay',
  'record.stamp.demo': 'demo',

  // -- the empty state
  'record.empty.chip': 'Example — from a shipped fixture, not from your calls.',
  'record.empty.exampleTitle': 'One worked example',
  'record.empty.run': 'Run the demo call',
  'record.empty.running': 'Running the fixture',
  /* Filters narrow the list and the export, never the headline counters. */
  'record.filter.state': 'Outcome',
  'record.filter.format': 'Format',
  'record.filter.period': 'When',
  'record.filter.any': 'All',
  'record.filter.day': 'Last 24 hours',
  'record.filter.week': 'Last 7 days',
  'record.filter.showing': '{shown} of {total} shown',
  'record.export.filtered': 'Filtered: {filters}.',
  'record.empty.explain': 'How a capture is decided',
  'record.empty.failed':
    'The example could not be fetched from the server, so nothing is shown in its place.',

  // -- list, loading, errors, export
  'record.list.title': 'Identifiers',
  'record.loading': 'Reading the record…',
  'record.error.noEndpoint':
    'This server has no record list yet. Nothing is shown here rather than something invented.',
  'record.retry': 'Try again',
  'record.export': 'Export CSV',
  'record.export.window': 'Readback record. Window: last {days} days. Rows: {rows}.',
  'record.export.replay.all': 'Every row came from a recorded fixture, not a live call.',
  'record.export.replay.mixed':
    'Some rows came from recorded fixtures; the source column says which.',

  // -------------------------------------------------------------- consent --

  /* THE CONSENT STEP (screens/Consent.tsx). ARCHITECTURE 3.12: all-party
   * consent, always, no jurisdiction toggle, and browser permission is not
   * consent. These strings are the disclosure itself, so a translation has to
   * stay TRUE, not merely fluent: what is streamed, what is kept, what is not,
   * in which language the agent listens, and that nothing waives it. */
  'consent.eyebrow': 'Before the microphone opens',
  'consent.title': 'Consent, first',
  'consent.lede':
    'Readback listens to the call in the background and writes reference numbers down. Nothing opens until everybody on the call has been told, and until you have read and accepted this.',
  'consent.what.title': 'What happens on this call',
  'consent.what.1':
    'The microphone on this device is streamed to Readback’s server, which forwards it to the speech recogniser. Raw audio is never stored anywhere along that path — not on this device, not on the server, not upstream.',
  'consent.what.2':
    'Only identifiers are kept: the number, its format, whether it settled, and how many times the agent had to ask. The conversation around them is never written down.',
  'consent.what.3':
    'The agent listens in English. When it cannot settle one character, it asks about that one character, once, and then goes quiet again.',
  'consent.what.4':
    'A session stops itself after {seconds} seconds. You can stop it sooner at any moment, and stopping ends the recogniser connection immediately.',
  'consent.allParty':
    'Every person on the call must know an assistant is listening, wherever they are calling from. There is no setting that waives this, and there will not be one.',
  'consent.version': 'Disclosure version',
  'consent.version.loading': 'Reading the version from the server…',
  'consent.version.unavailable':
    'The server could not be reached, so the disclosure version is unknown and a session cannot start.',
  'consent.replayOnly':
    'This server has no recognition key, or its daily budget is spent. A session started here would not hear this microphone, so none can be started.',
  'consent.accept.label': 'I have read this and I accept it.',
  'consent.played.label': 'The other party on the call has been told that an assistant is listening.',
  'consent.start': 'Start listening',
  'consent.starting': 'Opening',
  'consent.mic.note': 'The browser asks for the microphone only after you press this, never before.',

  // ----------------------------------------------------------------- live --

  /* THE LIVE SCREEN (screens/Live.tsx). DESIGN-BRIEF 4.1-4.3. No transcript,
   * no confidence, and nothing on screen while the agent is silent except the
   * fact that it is listening and has decided to stay quiet. */
  'live.eyebrow': 'Live',
  'live.title': 'Listening on this call',
  'live.state.starting': 'Recording consent',
  'live.state.connecting': 'Opening the session',
  'live.state.listening': 'Listening',
  'live.state.ended': 'Ended',
  'live.state.failed': 'Stopped',

  /* The silence indicator, live. The sentence and the gate come from the
   * record's held-line keys (record.held.*), which the same component reads. */
  'live.armed': 'Hearing something that could be {format}.',
  'live.idle': 'Nothing that looks like an identifier yet.',
  'live.elapsed.label': 'listening for',
  'live.elapsed.sr': 'Listening for {time}.',
  'live.cap.remaining': 'about {s} s left of the {cap} s cap',
  'live.cap.explain':
    'Every session stops itself at {cap} seconds. That is the deployment’s budget rule, not a fault.',

  'live.rack.title': 'Capture rack',
  'live.rack.meta': 'live',
  'live.row.reason': 'reason: {reason}',
  'live.stop': 'Stop and end the session',
  'live.hidden.notice':
    'Audio was not sent for {s} s while this tab was hidden. Nothing was buffered and nothing was replayed; the recogniser simply heard silence.',
  'live.noSignal':
    'The microphone is open but delivering silence. Check the mute switch on the device or in the operating system.',

  /* What the browser actually granted, from track.getSettings(). The request
   * is not what gets printed; the answer is. */
  'live.mic.title': 'What the browser granted',
  'live.mic.rate': '{rate} Hz from the device, resampled to 16000 Hz',
  'live.mic.rate.unknown': 'device rate not reported; context at {rate} Hz, resampled to 16000 Hz',
  'live.mic.channels': '{n} ch',
  'live.mic.ec': 'echo cancellation',
  'live.mic.ns': 'noise suppression',
  'live.mic.agc': 'auto gain',
  'live.mic.unknown': 'not reported',
  'live.mic.device': 'device',
  'live.mic.device.unknown': 'unnamed device',
  'live.chunks': '{n} chunks sent · 100 ms each',

  /* THE QUESTION MOMENT (4.3). Position, alternatives, what happens if nobody
   * answers. The agent's own sentence is English and is quoted as such. */
  'live.q.title': 'One character',
  'live.q.position': 'Position {n}',
  'live.q.blind':
    'The check digit cannot tell these two apart. The agent asks about this pair every time; that is diligence, not doubt.',
  'live.q.says': 'The agent says, in English:',
  'live.q.tap': 'Tap the character you heard.',
  'live.q.voiceNote':
    'In this build the answer is taken from the tap. Saying it into the microphone is not yet read as an answer.',
  'live.q.nobody':
    'If nobody answers within a few seconds, the agent counts the question against its budget and carries on: it may ask once more, or hand the number to a person.',
  'live.q.choice': 'Answer {char}',
  'live.q.sent': 'Answer sent',

  /* The end, in the server's words. `reason` is the pipeline's own label. */
  'live.ended.title': 'The session has ended.',
  'live.ended.reason.complete': 'The call ended and the agent wrote down what it had.',
  'live.ended.reason.cap':
    'The {cap}-second cap on a session was reached, so the recogniser connection was closed. That cap is the deployment’s budget rule, not a fault.',
  'live.ended.reason.stopped': 'You stopped it.',
  'live.ended.reason.error': 'The pipeline stopped with an error.',
  'live.ended.reason.other': 'Ended: {reason}.',
  'live.ended.tally': '{captures} written · {silent} without asking · {questions} asked',
  'live.ended.waiting': 'Waiting for the server’s tally…',
  'live.again': 'Start another session',

  /* FAILURE STATES. Each one is a different thing that happened and names a
   * different next step. Not one of them may be collapsed into another. */
  'live.fail.consent_absent':
    'The server refused to open a session because no consent was recorded with it. The microphone was not touched and nothing was captured.',
  'live.fail.server_unreachable':
    'Cannot reach the Readback service. No session was opened and the microphone was not touched.',
  'live.fail.server_refused':
    'The Readback service declined to open a session. Its own reason is printed below.',
  'live.fail.no_live_capture':
    'The session opened, but this server has no recognition key or its daily budget is spent, so it could not hear this microphone. The microphone was not opened.',
  'live.fail.mic_denied':
    'The browser refused the microphone. Allow it for this site in the address bar, then start again.',
  'live.fail.mic_missing': 'No microphone was found on this device.',
  'live.fail.mic_busy': 'The microphone is held by another application or another tab.',
  'live.fail.mic_unsupported':
    'This browser cannot capture audio here. It needs a secure origin (https, or localhost) and AudioWorklet support.',
  'live.fail.audio_refused':
    'The server did not accept the audio socket, so no audio was sent. The close code is printed below.',
  'live.fail.upstream_refused':
    'The speech recogniser refused the connection. The session ended before anything was heard.',
  'live.fail.connection_lost':
    'The connection to the server dropped mid-session. The session is over; anything already written is on the record.',
  'live.fail.device_lost': 'The microphone stopped delivering audio mid-session.',
  'live.fail.detail': 'Detail',

  // ---------------------------------------------------------------- admin --

  /* The platform admin panel (screens/Admin.tsx). Operators only: the
   * route renders nothing for anyone GET /api/admin/me refuses. */
  'admin.nav': 'Admin',
  'admin.title': 'Admin',
  'admin.intro':
    'The whole deployment, every organisation. Every change made here is written to the audit log.',
  'admin.loading': 'Loading…',
  'admin.failed': 'This could not be loaded: {message}',
  'admin.refresh': 'Refresh',
  'admin.none': '—',
  'admin.on': 'on',
  'admin.off': 'off',
  'admin.seconds': '{n} s',
  'admin.tab.overview': 'Overview',
  'admin.tab.quality': 'AI quality',
  'admin.tab.organisations': 'Organisations',
  'admin.tab.users': 'Users',
  'admin.tab.live': 'Live',
  'admin.tab.audit': 'Audit log',
  'admin.tab.controls': 'Controls',
  'admin.tab.system': 'System',
  'admin.kpi.organisations': 'Organisations',
  'admin.kpi.suspended': '{n} suspended',
  'admin.kpi.users': 'Users',
  'admin.kpi.usersSub': '{active} signed in this week · {disabled} disabled',
  'admin.kpi.sessions': 'Sessions, 24 h',
  'admin.kpi.sessionsSub': '{week} this week',
  'admin.kpi.running': 'Running now',
  'admin.kpi.runningSub': 'of {capacity} slots',
  'admin.kpi.spend': 'Spend today',
  'admin.kpi.spendSub': '{spent} of {budget} socket-seconds',
  'admin.kpi.benchmark': 'Benchmark',
  'admin.kpi.benchmarkSub': '{correct} of {total} correct · {wrong} written wrong silently',
  'admin.kpi.benchmarkNone': 'Not run since the server started',
  'admin.state.alarm': 'Budget alarm',
  'admin.state.exhausted': 'Budget exhausted',
  'admin.state.livePaused': 'Live capture paused',
  'admin.state.signupsPaused': 'Sign-ups paused',
  'admin.state.normal': 'All switches normal',
  'admin.q.window': 'Window',
  'admin.q.days': '{n} days',
  'admin.q.source': 'Source',
  'admin.q.source.all': 'All',
  'admin.q.source.live': 'Live calls',
  'admin.q.source.replay': 'Replays',
  'admin.q.silentCommit': 'Written without asking',
  'admin.q.silentRepair': 'Repaired in silence',
  'admin.q.asked': 'Asked a question',
  'admin.q.handover': 'Handed to a person',
  'admin.q.latency': 'Time to write, median',
  'admin.q.latencySub': 'p95 {p95}',
  'admin.q.necessity.title': 'Were the questions needed?',
  'admin.q.necessity.body':
    'When the agent asks about one character, the person\'s answer is the truth for that position. If it differs from what was heard, the question prevented a wrong write.',
  'admin.q.neededShort': 'Questions needed',
  'admin.q.needed': 'Needed',
  'admin.q.unneeded': 'Not needed',
  'admin.q.judged': '{n} answered questions judged',
  'admin.q.none': 'No captures in this window.',
  'admin.q.byFormat': 'By format',
  'admin.q.byDay': 'By day',
  'admin.bench.title': 'Benchmark against recorded truth',
  'admin.bench.note':
    'Every recorded fixture replayed through the live pipeline, with a person who answers every question correctly. A regression check on a small corpus, not a statistical estimate.',
  'admin.bench.run': 'Run benchmark',
  'admin.bench.running': 'Running…',
  'admin.bench.summary':
    '{correct} of {total} correct · {wrong} written wrong silently · {right} of {expected} questions at the right position',
  'admin.bench.nothing': 'nothing',
  'admin.result.ok': 'Correct',
  'admin.result.bad': 'Wrong',
  'admin.col.format': 'Format',
  'admin.col.captures': 'Captures',
  'admin.col.committed': 'Written',
  'admin.col.silent': 'Silent',
  'admin.col.asked': 'Asked',
  'admin.col.handover': 'Handed over',
  'admin.col.day': 'Day',
  'admin.col.fixture': 'Fixture',
  'admin.col.expected': 'Truth',
  'admin.col.written': 'Written',
  'admin.col.result': 'Result',
  'admin.col.questions': 'Questions',
  'admin.col.name': 'Name',
  'admin.col.status': 'Status',
  'admin.col.users': 'Users',
  'admin.col.sessions7d': 'Sessions, 7 d',
  'admin.col.captures7d': 'Captures, 7 d',
  'admin.col.spendToday': 'Spend today',
  'admin.col.budget': 'Own budget',
  'admin.col.lastActive': 'Last session',
  'admin.col.actions': 'Actions',
  'admin.col.email': 'Email',
  'admin.col.org': 'Organisation',
  'admin.col.role': 'Role',
  'admin.col.lastLogin': 'Last sign-in',
  'admin.col.session': 'Session',
  'admin.col.source': 'Source',
  'admin.col.running': 'Running',
  'admin.col.audio': 'Microphone',
  'admin.col.seq': '#',
  'admin.col.at': 'When',
  'admin.col.action': 'Action',
  'admin.col.actor': 'Actor',
  'admin.col.detail': 'Detail',
  'admin.search': 'Search',
  'admin.status.active': 'Active',
  'admin.status.suspended': 'Suspended',
  'admin.status.disabled': 'Disabled',
  'admin.org.searchPlaceholder': 'Organisation name',
  'admin.org.suspend': 'Suspend',
  'admin.org.reinstate': 'Reinstate',
  'admin.org.setBudget': 'Set budget',
  'admin.org.suspendPrompt': 'Why is {name} being suspended? Its running sessions stop now.',
  'admin.org.budgetPrompt':
    'Daily budget for {name}, in socket-seconds. Leave empty to use the deployment budget.',
  'admin.org.budgetDefault': 'deployment',
  'admin.org.budgetInvalid': 'Enter a whole number of seconds, or leave it empty.',
  'admin.user.searchPlaceholder': 'Email or name',
  'admin.user.admin': 'Operator',
  'admin.user.disable': 'Disable',
  'admin.user.enable': 'Enable',
  'admin.user.disableConfirm': 'Disable {email}? They are signed out on their next request.',
  'admin.live.empty': 'Nothing is running.',
  'admin.live.stop': 'Stop',
  'admin.live.stopConfirm': 'Stop this session now?',
  'admin.audit.all': 'Everything',
  'admin.audit.admin': 'Operator actions',
  'admin.audit.more': 'Load older',
  'admin.audit.empty': 'No events.',
  'admin.ctl.live.title': 'Pause live capture',
  'admin.ctl.live.body':
    'New sessions run recorded fixtures instead of opening an AssemblyAI socket. Running sessions are not affected.',
  'admin.ctl.signups.title': 'Pause sign-ups',
  'admin.ctl.signups.body': 'New accounts are refused. Everyone who already has one keeps working.',
  'admin.sys.environment': 'Environment',
  'admin.sys.python': 'Python',
  'admin.sys.uptime': 'Uptime',
  'admin.sys.database': 'Database',
  'admin.sys.key': 'AssemblyAI key',
  'admin.sys.present': 'present',
  'admin.sys.absent': 'absent',
  'admin.sys.live': 'Live capture',
  'admin.sys.replayMode': 'Replay mode',
  'admin.sys.consent': 'Consent version',
  'admin.sys.cap': 'Session cap',
  'admin.sys.slots': 'Concurrent sessions',
  'admin.sys.budget': 'Daily budget',
  'admin.sys.proxy': 'Trusted proxy hops',
  'admin.sys.docs': 'API docs',
  'admin.sys.cors': 'Allowed origins',
  'admin.sys.fixtures': 'Fixtures',
  'admin.sys.ok': 'ok',
  'admin.sys.down': 'unreachable',

  // ------------------------------------------------------- pitch (/pitch) --
  // The pitch page. Uzbek-first for Pitch Day 3.0 but tri-lingual because it
  // is the same page LabLab judges land on when they follow the video URL.
  // Inline emphasis and links are kept in the JSX so translations stay plain.
  'pitch.kicker': 'Pitch Day 3.0 · Stage 1',
  'pitch.title.before': 'Readback — a voice AI agent that gets the number ',
  'pitch.title.em': 'right',
  'pitch.title.after': '.',
  'pitch.lede':
    'Every call centre, insurer and logistics operator asks "say that again" dozens of times a day. Readback removes that lost time: even in noise, it knows how to check that the number is correct.',
  'pitch.cta.tryDemo': 'Try the prototype',
  'pitch.cta.product': 'Product page',

  'pitch.problem.title': 'The problem and the solution',
  'pitch.problem.h3': 'The problem',
  'pitch.problem.p1':
    'Call centres, logistics dispatchers and bank operators take reference numbers over the phone every day — container IDs, IBANs, VINs, patient codes, cards. In noise, 5 and 9, M and N, S and F sound the same. One wrong character means a container ships to the wrong port, a payment is reversed, or medication reaches the wrong patient.',
  'pitch.problem.p2':
    'People cope by asking "Bravo for B or Delta for D?" for every character. That costs 15–20 seconds per number, frustrates the customer, and drops operator throughput by 30 percent.',
  'pitch.solution.h3': 'The solution',
  'pitch.solution.p1':
    'Readback listens in the background and knows the shape a number must take. Container numbers satisfy the ISO 6346 check digit, IBANs give mod-97, cards give Luhn. This constraint does not improve the microphone — it multiplies the error budget the system can tolerate by 15×.',
  'pitch.solution.p2':
    'Two thirds of the time it silently corrects a misheard character and shows the difference on screen. When it cannot, it asks about one character, once, and goes quiet again. The transcript is not stored. What comes back is the confirmed number and a count of how many times the conversation was interrupted.',

  'pitch.team.title': 'Team',
  'pitch.team.role': 'Solo full-stack and AI engineer',
  'pitch.team.list.python':
    'Python, FastAPI, SQLAlchemy, PostgreSQL — server, session management, audit log',
  'pitch.team.list.typescript':
    'TypeScript, React, Vite — web app, live microphone stream (AudioWorklet → PCM16 → WebSocket)',
  'pitch.team.list.voice':
    'Voice AI: AssemblyAI Universal-3.5 Pro Streaming, turn control, keyterm biasing, LLM Gateway',
  'pitch.team.list.visual':
    'Visual: Three.js, Motion, Chart.js, Swiper — the landing 3D scene and charts',
  'pitch.team.list.infra':
    'Infrastructure: Render, Vercel, GitHub Actions (keep-alive), Neon Postgres',
  'pitch.team.note':
    'Built solo — 30+ commits in 24 days, 180 tests, tri-lingual interface, admin panel, audit log and deploy. That means a team ready to move from MVP to the next stage inside the Pitch Day window.',

  'pitch.reasons.title': 'Why we can solve this',
  'pitch.reasons.constraint.h3': 'We were the first to enforce the constraint',
  'pitch.reasons.constraint.p':
    'Other voice agents chase model quality. We treat the format constraint as the primitive and measured it across 12 million simulated calls in eight accents. Unconstrained error budget 0.0047, constrained 0.0692 — 14.9×. Documented in docs/EXPERIMENT.md and reproducible via the shipped script.',
  'pitch.reasons.engineering.h3': 'Honest engineering practice',
  'pitch.reasons.engineering.p':
    '180 automated tests, security audit (six defects closed), immutable audit log, cross-organisation data isolation. Every claim is measured and every source is cited in docs/. No lying "100%" figures.',
  'pitch.reasons.market.h3': 'We know the Uzbek market',
  'pitch.reasons.market.p':
    'In Uzbekistan, logistics (rail containers, freight companies), insurance and bank call centres all lean on reading numbers over the phone. The interface is Uzbek, Russian and English; the recogniser listens in English (AssemblyAI streaming does not yet support Uzbek and we say so up front).',

  'pitch.roadmap.title': 'Roadmap',
  'pitch.roadmap.idea.label': 'Idea',
  'pitch.roadmap.idea.when': '31 Aug 2026',
  'pitch.roadmap.idea.body':
    'Born for the AssemblyAI Voice Agent Hackathon. Problem clear: numbers mishear in noise. Solution: let the format give up its own check digit.',
  'pitch.roadmap.prototype.label': 'Prototype',
  'pitch.roadmap.prototype.when': '1–10 Sep 2026',
  'pitch.roadmap.prototype.body':
    'Solver (validator + posterior), replay path, ARM/IDLE detector, 8 recorded fixtures. No microphone at all — arithmetic over code. 156 tests.',
  'pitch.roadmap.mvp.label': 'MVP',
  'pitch.roadmap.mvp.when': '11–24 Sep 2026',
  'pitch.roadmap.mvp.body':
    'Live AssemblyAI socket, browser microphone path, multi-tenant admin panel, audit log, security audit, tri-lingual interface. 180 tests. Now in deploy.',
  'pitch.roadmap.launch.label': 'Launch',
  'pitch.roadmap.launch.when': 'Oct 2026',
  'pitch.roadmap.launch.body':
    'Real calls with three pilot customers (logistics, insurance, bank), measured silence rate and accuracy figures. Advance to Pitch Day stages 2 and 3, and top-5 at the AssemblyAI hackathon.',

  'pitch.plan.title': 'How we execute',
  'pitch.plan.stack.h3': 'Technical stack',
  'pitch.plan.stack.voice':
    'Voice: AssemblyAI Universal-3.5 Pro Streaming (WebSocket), keyterm biasing, UpdateConfiguration to refresh the constraint list when ARMED, ForceEndpoint to snap back to silence at the end of a number',
  'pitch.plan.stack.server':
    'Server: FastAPI + uvicorn, SQLAlchemy 2, PostgreSQL. One process per session, one socket, daily budget per ARCH 3.11',
  'pitch.plan.stack.web':
    'Web: React 19, Vite, TypeScript, i18n triangle (en/uz/ru). AudioWorklet takes the mic and sends PCM16 chunks to the server',
  'pitch.plan.stack.security':
    'Security: PBKDF2-SHA256 600k iterations, daily and per-IP rate limits, HttpOnly cookies, per-organisation catalog, immutable audit log',
  'pitch.plan.stages.h3': 'Stages',
  'pitch.plan.stages.sept':
    'September: MVP deploy, Pitch Day 3.0 submission, AssemblyAI hackathon submission',
  'pitch.plan.stages.oct':
    'October: closed beta with three pilot customers. Measure silence share and asked-question count per call. Wire LLM Gateway as a second signal',
  'pitch.plan.stages.novDec':
    'November–December: open beta. Payment integration, user accounts, per-second billing model',
  'pitch.plan.stages.jan2027': 'January 2027: commercial launch, first paying customers',
  'pitch.plan.ai.h3': 'AI tools',
  'pitch.plan.ai.assemblyai': 'AssemblyAI Universal-3.5 Pro — real-time recognition',
  'pitch.plan.ai.gateway': 'AssemblyAI LLM Gateway — second signal for format detection',
  'pitch.plan.ai.claudeCode': 'Claude Code — planning and code-writing assistant',
  'pitch.plan.ai.solver':
    'Our own solver — check-digit arithmetic and posterior. Boundaries measured in docs/EXPERIMENT.md',

  'pitch.demo.title': 'Demo and prototype',
  'pitch.demo.videoTitle': 'Readback demo video',
  'pitch.demo.placeholder':
    'Demo video in production. A 1–5 minute video will land here by 11 October.',
  'pitch.demo.about.h3': 'About the video',
  'pitch.demo.about.p':
    'The video mimics a real phone call: the operator asks for a container number, the caller reads it back over a noisy line. On screen, Readback fills the number character by character, silently corrects one, and shows the difference. In the second half, a case it cannot correct: it asks once and records. Ending: silence share and a one-day money-saved figure.',
  'pitch.demo.prototype.h3': 'Working prototype',
  'pitch.demo.prototype.demoLine': '/demo — 8 recorded fixtures, no account needed',
  'pitch.demo.prototype.liveLine': '/live — live microphone (account required)',
  'pitch.demo.prototype.formatsLine': '/formats — the 5 supported formats',
  'pitch.demo.prototype.open': 'Open',
  'pitch.demo.source.h3': 'Source code',
  'pitch.demo.source.before': 'Full code on ',
  'pitch.demo.source.link': 'GitHub',
  'pitch.demo.source.after':
    '. Server (FastAPI, ~4000 lines), web (React, ~5000 lines), 180 automated tests and docs/ — all in one repository.',

  'pitch.footer.contact': 'For questions or more information:',
} as const;

/** Every key in the catalog. Adding one here is what forces uz and ru to move. */
export type TranslationKey = keyof typeof en;

/** The contract each catalog satisfies. A missing key fails here, by name. */
export type Messages = Readonly<Record<TranslationKey, string>>;

/** The placeholder names a given key expects, read off the English string. */
export type ParamsFor<K extends TranslationKey> =
  import('./types').ParamNames<(typeof en)[K]>;

/**
 * A key whose English string has no placeholders.
 *
 * `t()` is deliberately strict: a key with placeholders REQUIRES the params
 * argument. That strictness is computed from the key's literal type, so it
 * lands badly on a *table* of keys -- `Record<Outcome, TranslationKey>`, a
 * fixture's `title`, a format card's fields. Their values are typed as the
 * whole union, `ParamsFor` over the union is every placeholder in the catalog,
 * and `t(table[k])` is then asked for params no caller could supply. Declare
 * those tables as `PlainKey` instead: it says the thing that is actually true
 * of them -- these keys interpolate nothing -- and a key with a placeholder
 * put in one stops compiling at the table rather than at the call.
 */
export type PlainKey = {
  [K in TranslationKey]: [ParamsFor<K>] extends [never] ? K : never;
}[TranslationKey];
