// The visitor's preferences on this device, as one plain JSON object in localStorage ("prefs"), so
// they work without an account. Signed in, lib/profile.svelte.ts keeps them in step with the
// profile's preferences (setLang, setTheme, loadProfile). index.html reads the theme too, before the
// app loads.

export type Lang = 'sk' | 'en'
export const LANGS: Lang[] = ['sk', 'en']

export type Theme = 'light' | 'dark'
export const THEMES: Theme[] = ['light', 'dark']

export interface Prefs {
  lang: Lang
  /** Null follows the device's setting (lib/theme.svelte.ts). */
  theme: Theme | null
}

const KEY = 'prefs'

/** The known keys with valid values from untrusted data (localStorage, a profile). */
function valid(p: unknown): Partial<Prefs> {
  const { lang, theme } = (p ?? {}) as Partial<Prefs>
  return {
    ...(lang && LANGS.includes(lang) ? { lang } : {}),
    ...(theme === null || (theme && THEMES.includes(theme)) ? { theme } : {}),
  }
}

function stored(): Prefs {
  try {
    return { lang: 'sk', theme: null, ...valid(JSON.parse(localStorage.getItem(KEY) ?? 'null')) }
  } catch {
    return { lang: 'sk', theme: null }
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
