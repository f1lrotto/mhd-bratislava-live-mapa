// Analytics (PostHog, EU) on the production site only. Until the visitor agrees, and after they
// refuse, PostHog runs cookieless: nothing is stored in the browser and PostHog's server counts
// visitors by a daily-salted hash it can't reverse. With consent, it keeps an ID in the browser so
// returning visitors count once. The privacy page (PrivacyPanel) describes exactly this.
import type { PostHog } from 'posthog-js'

const TOKEN = 'phc_woSi6RvGuWmZ6FByoucbcaY4v6R9GNYzMqhu8gbntojJ'
const KEY = 'analytics-consent'
/** Visitors with Global Privacy Control or Do Not Track get no analytics at all, not even cookieless. */
export const OPTED_OUT =
  (navigator as { globalPrivacyControl?: boolean }).globalPrivacyControl === true || navigator.doNotTrack === '1'
export const ANALYTICS = location.hostname === 'mhd.filiphupka.com' && !OPTED_OUT

export type Consent = 'granted' | 'denied'

function stored(): Consent | null {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'granted' || v === 'denied' ? v : null
  } catch {
    return null
  }
}

/** The visitor's answer to the banner; null until they answer. */
export const consent = new (class {
  choice = $state.raw<Consent | null>(stored())
})()

export const standalone =
  matchMedia('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true

let posthog: PostHog | null = null
const queue: [string, Record<string, unknown> | undefined][] = []

export function startAnalytics(): void {
  if (!ANALYTICS) return
  import('posthog-js').then(({ default: ph }) => {
    ph.init(TOKEN, {
      api_host: 'https://eu.i.posthog.com',
      defaults: '2026-08-30',
      // Cookieless until opt_in_capturing(); opt-out returns to cookieless.
      cookieless_mode: 'on_reject',
      opt_out_capturing_by_default: true,
      disable_session_recording: true,
      before_send: (event) => {
        if (!event) return event
        // Query strings can hold a planned trip's coordinates ("Moja poloha"): never send them.
        for (const props of [event.properties, event.$set, event.$set_once]) {
          for (const k in props) {
            const v = props[k]
            if (typeof v === 'string' && v.startsWith(location.origin)) props[k] = v.split('?')[0]
          }
        }
        // Opened from the home screen (installed PWA) or in a browser tab.
        event.properties.display_mode = standalone ? 'standalone' : 'browser'
        return event
      },
    })
    posthog = ph
    apply()
    for (const [e, p] of queue.splice(0)) ph.capture(e, p)
  })
}

function apply(): void {
  if (!posthog) return
  const granted = posthog.get_explicit_consent_status() === 'granted'
  if (consent.choice === 'granted' && !granted) posthog.opt_in_capturing()
  else if (consent.choice !== 'granted' && granted) posthog.opt_out_capturing()
}

export function setConsent(c: Consent): void {
  consent.choice = c
  try {
    localStorage.setItem(KEY, c)
  } catch {
    // Private mode: the banner asks again next time.
  }
  apply()
}

/** A feature-usage event. Never pass coordinates, place names or anything else about the visitor. */
export function track(event: string, props?: Record<string, unknown>): void {
  if (!ANALYTICS) return
  if (posthog) posthog.capture(event, props)
  else queue.push([event, props])
}
