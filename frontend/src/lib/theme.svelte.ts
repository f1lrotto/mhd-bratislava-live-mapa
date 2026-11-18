// Light or dark: the theme chosen on this device or in the profile (prefs.theme), else the device's
// setting. index.html applies it before the app loads, so a dark page doesn't flash light; app.css
// has the colours of both, keyed on <html data-theme>.
import { prefs } from './prefs.svelte'

const media = matchMedia('(prefers-color-scheme: dark)')
let system = $state(media.matches)
media.addEventListener('change', (e) => (system = e.matches))

export const isDark = (): boolean => (prefs.theme ?? (system ? 'dark' : 'light')) === 'dark'

$effect.root(() => {
  $effect(() => {
    const dark = isDark()
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    // The browser's and the installed app's bars, the top bar's colour (--surface in app.css).
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#1b1f24' : '#ffffff')
  })
})
