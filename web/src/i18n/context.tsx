/* The provider, and the typed t().
 *
 * WHY NO LIBRARY.
 * ---------------
 * The wired key set is 38 keys x 3 languages = 114 strings, and all three
 * catalogs together are under 12 kB of source before minification. i18next plus
 * react-i18next is roughly 40 kB minified for that, and -- the part that
 * actually decides it -- its default behaviour on a missing key is to fall back
 * to the English string and carry on. That is precisely the failure this build
 * is supposed to make impossible: with one developer and three languages, a
 * silent fallback is how a half-translated UI ships without anyone noticing.
 * Turning fallback off in i18next makes a missing key render the raw key at
 * RUNTIME. Here it fails at COMPILE time, by name, in `tsc --noEmit`.
 *
 * The whole runtime is this file: a context, a Map lookup and a regex replace.
 */

import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
} from 'react';
import type { ReactNode } from 'react';
import { en } from './en';
import type { Messages, ParamsFor, TranslationKey } from './en';
import { uz } from './uz';
import { ru } from './ru';
import { isLanguage } from './types';
import type { Language } from './types';
import { initialLanguage, writeStoredLanguage } from './storage';
import { LOCALE_TAG, formatCurrency, formatDate, formatNumber, pluralRules } from './format';

const CATALOGS: Readonly<Record<Language, Messages>> = { en, uz, ru };

// ------------------------------------------------------------ interpolation --

/* Substitution is VERBATIM. A parameter is inserted as the string it already is;
 * nothing here touches Intl, changes a digit shape, or reorders anything. That
 * is what makes it safe to pass an identifier character through t() for the
 * screen-reader readout -- see THE IDENTIFIER RULE in components/Rack.tsx.
 *
 * Consequently t() takes only strings. A caller with a number has to decide,
 * visibly at the call site, whether it should be localised (n(), from this
 * context) or left exactly as it is (an identifier). Accepting `number` here
 * would let an unlocalised count slip in looking like it had been handled. */
const PLACEHOLDER = /\{([a-zA-Z0-9_]+)\}/g;

function interpolate(template: string, params: Readonly<Record<string, string>> | undefined): string {
  if (params === undefined) return template;
  return template.replace(PLACEHOLDER, (whole, name: string) => params[name] ?? whole);
}

// ------------------------------------------------------------------ types --

/**
 * Params are derived from the ENGLISH string for the key, so the compiler knows
 * that `rack.readout.repaired` needs {position}, {heard} and {written} and that
 * `rack.empty` needs nothing. A key with no placeholders REFUSES a second
 * argument; a key with placeholders REQUIRES one covering all of them.
 */
export type TFunction = <K extends TranslationKey>(
  key: K,
  ...params: [ParamsFor<K>] extends [never]
    ? []
    : [params: Readonly<Record<ParamsFor<K>, string>>]
) => string;

/**
 * The keys that form a complete CLDR plural set: a base for which all four of
 * `.one`, `.few`, `.many` and `.other` exist in the catalog. Computed from the
 * key set, so `plural()` cannot be handed a base that is missing a form.
 */
export type PluralBase = {
  [K in TranslationKey]: K extends `${infer B}.other`
    ? `${B}.one` extends TranslationKey
      ? `${B}.few` extends TranslationKey
        ? `${B}.many` extends TranslationKey
          ? B
          : never
        : never
      : never
    : never;
}[TranslationKey];

export interface I18n {
  language: Language;
  /** The BCP-47 tag the formatters are pinned to. */
  locale: string;
  setLanguage: (language: Language) => void;
  t: TFunction;
  /** A counted noun. The count is localised and substituted as {n}. */
  plural: (base: PluralBase, count: number) => string;
  /** Number in the selected UI language. Never for identifiers. */
  n: (value: number) => string;
  /** Date in the selected UI language. */
  d: (value: Date | string | number) => string;
  /** Money in the selected UI language. */
  money: (value: number, currency: string) => string;
}

// --------------------------------------------------------------- provider --

const I18nContext = createContext<I18n | null>(null);

export interface I18nProviderProps {
  children: ReactNode;
  /** Test seam. Omit in the app: the language comes from storage or navigator. */
  initial?: Language;
}

export function I18nProvider({ children, initial }: I18nProviderProps) {
  const [language, setLanguageState] = useState<Language>(() => initial ?? initialLanguage());

  /* <html lang> drives the voice a screen reader speaks the page in. Getting it
   * wrong is not cosmetic: NVDA will read Russian with an English synthesiser,
   * which is unintelligible rather than merely accented.
   *
   * useLayoutEffect, not useEffect, so the attribute is correct BEFORE the
   * browser paints the first frame of the new language rather than one frame
   * after it. index.html ships lang="en"; this closes the gap on load. */
  useLayoutEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const setLanguage = useCallback((next: Language) => {
    setLanguageState(next);
    writeStoredLanguage(next);
  }, []);

  const value = useMemo<I18n>(() => {
    const messages = CATALOGS[language];

    const t = ((key: TranslationKey, params?: Readonly<Record<string, string>>) =>
      interpolate(messages[key], params)) as TFunction;

    const n = (input: number) => formatNumber(language, input);

    return {
      language,
      // The pinned tag ('ru-RU'), not the language code ('ru'). A caller that
      // needs to build its own Intl instance must get the same tag format.ts
      // uses, or the pin has a hole in it.
      locale: LOCALE_TAG[language],
      setLanguage,
      t,
      n,
      d: (input) => formatDate(language, input),
      money: (input, currency) => formatCurrency(language, input, currency),
      plural: (base, count) => {
        const category = pluralRules(language).select(count);
        /* PluralBase guarantees `${base}.one|few|many|other` are all real keys.
         * Intl can also return `zero` or `two` for languages that have them;
         * neither en, uz nor ru does, and `other` is the correct CLDR fallback
         * if a fourth language ever brings one. */
        const key = `${base}.${category}` as TranslationKey;
        const template = messages[key] ?? messages[`${base}.other` as TranslationKey];
        return interpolate(template, { n: n(count) });
      },
    };
  }, [language, setLanguage]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

/**
 * Throws when the provider is missing. That is a wiring mistake, not a runtime
 * condition, and it should fail on the first render in development rather than
 * render an English page that looks fine — the same call main.tsx makes about a
 * missing #root.
 */
export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (value === null) {
    throw new Error('useI18n was called outside <I18nProvider>. Mount it in main.tsx.');
  }
  return value;
}

export { isLanguage };
export type { Language, TranslationKey };
