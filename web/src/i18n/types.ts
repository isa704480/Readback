/* The type machinery that makes a missing translation a BUILD error.
 *
 * Nothing in this file emits code. It exists so that the uz and ru catalogs
 * cannot drift from en without `tsc --noEmit` failing, because the alternative
 * -- a runtime fallback to English -- is invisible. A half-translated UI that
 * silently falls back looks finished in every language until a reader who does
 * not speak English hits the one screen nobody translated.
 *
 * Three separate things are checked, all at compile time:
 *
 *   1. MISSING KEY   the `Messages` annotation on each catalog requires every
 *                    key that exists in en.ts. Omit one and tsc says which.
 *   2. UNKNOWN KEY   a key that is not in en.ts (a typo, or a key deleted from
 *                    en and left behind here) is rejected rather than ignored.
 *   3. PLACEHOLDER   "{n} question." translated as "вопрос." drops the number
 *      PARITY        and no type would normally notice, because both are just
 *                    `string`. ParamNames pulls the {braced} names out of the
 *                    literal type of each string and requires the two sets to
 *                    match exactly.
 *
 * (3) is the one that earns its keep. (1) fails loudly the moment you add a
 * key; (3) fails quietly forever, which is why it is worth the ten lines.
 */

export const LANGUAGES = ['en', 'uz', 'ru'] as const;

export type Language = (typeof LANGUAGES)[number];

export function isLanguage(value: unknown): value is Language {
  return typeof value === 'string' && (LANGUAGES as readonly string[]).includes(value);
}

/** The {braced} placeholder names inside a string literal type. */
export type ParamNames<S extends string> = S extends `${string}{${infer P}}${infer Rest}`
  ? P | ParamNames<Rest>
  : never;

/** Mutual assignability. `A extends B` alone is not enough: `never extends 'n'`
 *  is true, so a translation that dropped every placeholder would pass. */
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;

/* These two show up as the expected type in the compiler error, so the message
 * a contributor reads names the problem instead of dumping a string union. */
type PlaceholderMismatch<K> = ['i18n: placeholders differ from the English string for key', K];
type UnknownCatalogKey<K> = ['i18n: this key is not in the English catalog', K];

/**
 * The shape a non-English catalog has to satisfy.
 *
 * `T extends Record<keyof Reference, string>` is where a missing key is caught;
 * the mapped body is where a placeholder mismatch is caught; the intersected
 * tail is where an unknown key is caught.
 */
export type Translated<
  Reference extends Record<string, string>,
  T extends Record<keyof Reference, string>,
> = {
  [K in keyof Reference]: Same<ParamNames<T[K]>, ParamNames<Reference[K]>> extends true
    ? T[K]
    : PlaceholderMismatch<K>;
} & {
  [K in Exclude<keyof T, keyof Reference>]: UnknownCatalogKey<K>;
};
