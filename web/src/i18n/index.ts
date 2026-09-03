/* The i18n barrel.
 *
 * Screens import from here. The catalogs are not exported: nothing outside this
 * folder should read a message by hand, because a hand-read message is one that
 * skipped the placeholder substitution and the plural rules.
 */

export { I18nProvider, useI18n } from './context';
export type { I18n, I18nProviderProps, TFunction, PluralBase } from './context';

export { LanguageSwitcher } from './LanguageSwitcher';
export type { LanguageSwitcherProps } from './LanguageSwitcher';

export { LANGUAGES, isLanguage } from './types';
export type { Language } from './types';

export type { TranslationKey, Messages, ParamsFor } from './en';

/* The locale pin. Exported so a future formatter can be added in format.ts
 * against the same tags rather than inventing a second mapping. */
export { LOCALE_TAG } from './format';
