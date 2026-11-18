// UI text in the visitor's language (prefs.lang). Each string is written in place as its Slovak and
// English versions, t('Zavrieť', 'Close'), so the two stay side by side. Calls re-run reactively when
// the language changes, so keep them in templates, $derived values or functions, not in constants.
import { prefs } from './prefs.svelte'

export const t = (sk: string, en: string): string => (prefs.lang === 'en' ? en : sk)

/** "1 vozidlo / 2 vozidlá / 5 vozidiel" or "1 vehicle / 2 vehicles". */
export function count(n: number, sk: [one: string, few: string, many: string], en: [one: string, other: string]): string {
  if (prefs.lang === 'en') return `${n} ${n === 1 ? en[0] : en[1]}`
  return `${n} ${n === 1 ? sk[0] : n >= 2 && n <= 4 ? sk[1] : sk[2]}`
}

/** The BCP 47 locale for Intl and localeCompare. */
export const locale = (): string => (prefs.lang === 'en' ? 'en-GB' : 'sk-SK')
