/* The language switcher.
 *
 * A native <select>. That is a deliberate choice over a custom menu: it is
 * keyboard operable, arrow-key navigable, announced as a listbox with its
 * position ("2 of 3") and rendered as the platform's own picker wheel on a
 * phone -- all of it for free, none of it re-implemented, none of it a place to
 * introduce a focus-trap bug the week of a deadline. The only thing given up is
 * control of the option list's appearance, which is not worth a custom widget.
 *
 * The options are ENDONYMS -- English, Oʻzbekcha, Русский -- identical in all
 * three catalogs, so a reader stranded in a language they cannot read can still
 * find their own.
 *
 * HONESTY. Readback's speech pipeline is English-only. A bare language picker
 * in a top bar reads as "this product speaks your language", which would be a
 * false claim. So the control is NAMED "Interface language", it carries the
 * full statement as its accessible description, and it shows a short visible
 * line whenever the interface is not in English -- the exact moment the
 * arrangement could be misread.
 */

import { useId } from 'react';
import { useI18n } from './context';
import { LANGUAGES, isLanguage } from './types';
import type { Language } from './types';
import './LanguageSwitcher.css';

/* Narrowly typed on purpose. `Record<Language, TranslationKey>` would widen the
 * key to the whole union and t() would then demand the union of every
 * placeholder in the catalog; these three keys take none. */
const NAME_KEY = {
  en: 'lang.name.en',
  uz: 'lang.name.uz',
  ru: 'lang.name.ru',
} as const;

export interface LanguageSwitcherProps {
  className?: string;
}

export function LanguageSwitcher({ className }: LanguageSwitcherProps) {
  const { language, setLanguage, t } = useI18n();
  const noteId = useId();

  const handleChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const next = event.target.value;
    // The DOM hands back a string. Nothing else may reach setLanguage.
    if (isLanguage(next)) setLanguage(next);
  };

  return (
    <div className={['lang', className ?? ''].filter(Boolean).join(' ')}>
      <span className="lang__control">
        <select
          className="lang__select"
          aria-label={t('lang.switcher.label')}
          aria-describedby={noteId}
          value={language}
          onChange={handleChange}
        >
          {LANGUAGES.map((code: Language) => (
            <option key={code} value={code}>
              {t(NAME_KEY[code])}
            </option>
          ))}
        </select>
        {/* Decorative: the select still owns the interaction. pointer-events is
            off in CSS so a click on the chevron opens the picker. */}
        <svg
          className="lang__chevron"
          viewBox="0 0 24 24"
          width="16"
          height="16"
          aria-hidden="true"
          focusable="false"
        >
          <path
            d="M6 9l6 6 6-6"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>

      {/* Always present for assistive tech, whatever the language. */}
      <span id={noteId} className="sr-only">
        {t('lang.switcher.note')}
      </span>

      {/* The visible note is gone from the bar on the owner's instruction. The
          spoken one above stays and is still wired through aria-describedby, so
          the control continues to announce that only the interface changes
          language.

          Worth knowing rather than hiding: the landing page still states this in
          its hero, but a signed-in reader who switches to Russian inside the app
          no longer meets it anywhere on screen. docs/DESIGN-BRIEF.md §6 asks the
          interface never to imply multilingual speech recognition, and this
          removes the one visible place it said otherwise. */}
    </div>
  );
}
