// The visitor's preferences on this device, as one plain JSON object in localStorage ("prefs"), so
// they work without an account. Signed in, lib/profile.svelte.ts keeps them in step with the
// profile's preferences (setLang, loadProfile).

export type Lang = 'sk' | 'en'
export const LANGS: Lang[] = ['sk', 'en']

export interface Prefs {
  lang: Lang
}

const KEY = 'prefs'

/** The known keys with valid values from untrusted data (localStorage, a profile). */
function valid(p: unknown): Partial<Prefs> {
  const lang = (p as Partial<Prefs> | null)?.lang
  return lang && LANGS.includes(lang) ? { lang } : {}
}

function stored(): Prefs {
  try {
    return { lang: 'sk', ...valid(JSON.parse(localStorage.getItem(KEY) ?? 'null')) }
  } catch {
    return { lang: 'sk' }
  }
}

export const prefs: Prefs = $state(stored())

export function setPrefs(p: Partial<Prefs>): void {
  Object.assign(prefs, valid(p))
  try {
    localStorage.setItem(KEY, JSON.stringify($state.snapshot(prefs)))
  } catch {
    // Private mode: the choice lasts until the page closes.
  }
}
