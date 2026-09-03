/* Numbers, dates and money.
 *
 * THE LOCALE PIN.
 * ---------------
 * Every Intl constructor in this app is called from this file, and every one of
 * them is handed an EXPLICIT tag derived from the language the operator chose in
 * the switcher. None of them is ever called with `undefined`, which is the
 * signature of the bug this file exists to prevent: `Intl.NumberFormat()` with
 * no locale silently adopts the SYSTEM locale, so an English interface on a
 * Russian desktop renders a price as "63 $" while every word around it is in
 * English. The number and the words have to come from the same decision, and
 * the decision is the UI language, not the OS.
 *
 * Audited at the time of writing: there was no Intl call anywhere in web/src,
 * so this is the pin being established rather than an existing one moved. If a
 * later screen needs a formatter, it belongs here -- a second `new Intl.*` call
 * site elsewhere is the bug coming back.
 *
 * NOT FOR IDENTIFIERS. A container number, an IBAN or a check digit never comes
 * through this file. See THE IDENTIFIER RULE in components/Rack.tsx.
 */

import type { Language } from './types';

/**
 * The BCP-47 tag each UI language formats as.
 *
 * Verified against Node's full ICU: all three resolve to themselves rather than
 * falling back to root, and all three produce Latin digits.
 *   en-GB       1,234,567.89   1 Sept 2026    US$63.00
 *   uz-Latn-UZ  1 234 567,89   1-sen, 2026    63,00 US$
 *   ru-RU       1 234 567,89   1 сент. 2026   63,00 $
 *
 * uz is pinned to the Latn script explicitly. Bare `uz` resolves to Latin today,
 * but the catalog is Latin by decision, not by default, and the tag should say
 * so rather than rely on CLDR keeping that default.
 */
export const LOCALE_TAG: Readonly<Record<Language, string>> = {
  en: 'en-GB',
  uz: 'uz-Latn-UZ',
  ru: 'ru-RU',
};

/* `numberingSystem: 'latn'` is belt and braces. All three tags already resolve
 * to Latin digits, so this changes no output today; it is here so that a fourth
 * language whose CLDR default is not Latin cannot quietly turn a count into
 * glyphs the rest of the interface does not use. */
const LATIN = { numberingSystem: 'latn' } as const;

/* Intl constructors are expensive enough that building one per render is
 * measurable in a rack of forty rows. One per language, built on first use. */
const numberCache = new Map<Language, Intl.NumberFormat>();
const dateCache = new Map<Language, Intl.DateTimeFormat>();
const pluralCache = new Map<Language, Intl.PluralRules>();
const currencyCache = new Map<string, Intl.NumberFormat>();

export function numberFormatter(language: Language): Intl.NumberFormat {
  let formatter = numberCache.get(language);
  if (!formatter) {
    formatter = new Intl.NumberFormat(LOCALE_TAG[language], LATIN);
    numberCache.set(language, formatter);
  }
  return formatter;
}

export function dateFormatter(language: Language): Intl.DateTimeFormat {
  let formatter = dateCache.get(language);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(LOCALE_TAG[language], {
      dateStyle: 'medium',
      timeStyle: 'short',
      ...LATIN,
    });
    dateCache.set(language, formatter);
  }
  return formatter;
}

export function pluralRules(language: Language): Intl.PluralRules {
  let rules = pluralCache.get(language);
  if (!rules) {
    rules = new Intl.PluralRules(LOCALE_TAG[language]);
    pluralCache.set(language, rules);
  }
  return rules;
}

export function formatNumber(language: Language, value: number): string {
  return numberFormatter(language).format(value);
}

export function formatDate(language: Language, value: Date | string | number): string {
  const date = value instanceof Date ? value : new Date(value);
  // An unparseable created_at must not put "Invalid Date" on screen.
  if (Number.isNaN(date.getTime())) return '';
  return dateFormatter(language).format(date);
}

/**
 * Money, in the selected UI language.
 *
 * Russian genuinely writes "63,00 $" with the symbol trailing -- that is
 * correct ru-RU, not the bug. The bug was an ENGLISH interface rendering
 * "63 $" because Intl was reading the operating system instead of the page.
 * Following the selected language means the symbol lands wherever that
 * language puts it, and the words around it agree.
 */
export function formatCurrency(language: Language, value: number, currency: string): string {
  const key = `${language}:${currency}`;
  let formatter = currencyCache.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat(LOCALE_TAG[language], {
      style: 'currency',
      currency,
      currencyDisplay: 'narrowSymbol',
      ...LATIN,
    });
    currencyCache.set(key, formatter);
  }
  return formatter.format(value);
}
