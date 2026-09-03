/* Where the chosen language lives between visits.
 *
 * This deliberately mirrors the storage block in lib/session.ts rather than
 * inventing a second pattern: reading window.localStorage THROWS outright in a
 * Safari private window and wherever site data is blocked by policy -- not on
 * write, on the property access itself -- so every touch is guarded and a
 * blocked store degrades to memory. The user keeps their language for the life
 * of the tab instead of the app crashing on boot in a private window.
 *
 * It is a separate file from session.ts only because language is not session
 * state: it survives sign-out, and it has to resolve before any token does.
 */

import { LANGUAGES, isLanguage } from './types';
import type { Language } from './types';

const LANGUAGE_KEY = 'readback.language';

/** The memory copy that takes over when the real store refuses. */
let memoryLanguage: Language | null = null;

function store(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readStoredLanguage(): Language | null {
  try {
    const value = store()?.getItem(LANGUAGE_KEY);
    // A value written by an older build, or edited by hand, is not trusted.
    if (isLanguage(value)) return value;
  } catch {
    /* fall through to the memory copy */
  }
  return memoryLanguage;
}

export function writeStoredLanguage(language: Language): void {
  memoryLanguage = language;
  try {
    store()?.setItem(LANGUAGE_KEY, language);
  } catch {
    /* quota, private mode, blocked site data. The memory copy already took. */
  }
}

/**
 * First visit only: what the browser says the reader prefers.
 *
 * navigator.languages is ordered by preference, so the first supported entry
 * wins rather than the first entry being tested and abandoned. Matching is on
 * the primary subtag: `ru-RU`, `ru-KZ` and `ru` are all Russian to us, and
 * `uz-Cyrl-UZ` maps to our Latin Uzbek -- which is a real compromise and worth
 * naming. We ship one Uzbek script; a Cyrillic-preferring reader gets Latin
 * Uzbek, which is closer to their language than English is.
 */
export function detectLanguage(): Language {
  const offered: readonly string[] =
    typeof navigator === 'undefined'
      ? []
      : (navigator.languages ?? (navigator.language ? [navigator.language] : []));

  for (const tag of offered) {
    const primary = tag.toLowerCase().split('-')[0];
    if (primary !== undefined && isLanguage(primary)) return primary;
  }

  return LANGUAGES[0]; // 'en'
}

/** Stored choice if there is one, otherwise the browser's preference. */
export function initialLanguage(): Language {
  return readStoredLanguage() ?? detectLanguage();
}
