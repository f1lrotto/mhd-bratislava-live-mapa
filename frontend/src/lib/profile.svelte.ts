// The signed-in user's profile: favourites and preferences, kept by the accounts server
// (auth/, Better Auth) behind /api/auth. Signed out, the profile is empty; pinning asks to sign in
// and pins once signed in.
import { track } from './analytics.svelte'
import { isHere, markHere, pointValue } from './places'
import { app, navigate, type View } from './state.svelte'

export type FavoriteKind = 'station' | 'line' | 'route'

export interface Favorite {
  kind: FavoriteKind
  /** A station code, a line, or a route "<from>><to>" of planner values or HERE. */
  ref: string
  /** Display names of a route's point ends. */
  names: { from?: string; to?: string } | null
  createdAt: string
}

/** Every preference is optional; unset means the app's default. The accounts server checks them
 * (Preferences in auth/profile.js): a new one is a new key in both. */
export interface Preferences {
  /** The UI language. */
  lang?: 'sk' | 'en'
  /** What the installed app opens to; unset is the favourites. */
  start?: 'favorites' | 'map'
}

export interface User {
  email: string
  emailVerified: boolean
  createdAt: string
  /** Signing in also asks for a code from an authenticator app. */
  twoFactorEnabled: boolean
}

export interface Passkey {
  id: string
  name: string | null
  /** "singleDevice", or "multiDevice" for one synced across the user's devices. */
  deviceType: string
  createdAt: string
}

interface ProfileResponse {
  user: User | null
  preferences: Preferences
  favorites: Favorite[]
  passkeys: Passkey[]
  mail: boolean
}

/** A route end that means "where I am when I open it", stored instead of coordinates. */
export const HERE = 'here'
const MY_LOCATION = 'Moja poloha'

class ProfileState {
  /** False until the first /profile answer, so nothing flashes "signed out" while it loads. */
  loaded = $state.raw(false)
  user = $state.raw<User | null>(null)
  /** The last /profile request failed (offline, or the accounts server is down): the user may
   * well be signed in, so the app says so rather than asking them to sign in. */
  failed = $state.raw(false)
  favorites = $state.raw<Favorite[]>([])
  passkeys = $state.raw<Passkey[]>([])
  preferences = $state.raw<Preferences>({})
  /** The server can send account emails (verification, password reset). */
  mail = $state.raw(false)
  /** A favourite to pin once the user signs in (they tapped the star while signed out). */
  pending = $state.raw<Omit<Favorite, 'createdAt'> | null>(null)
}

export const profile = new ProfileState()

/** A call to the accounts server; throws an Error whose message is Better Auth's error code. */
async function call<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api/auth${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  })
  const data = await r.json().catch(() => null)
  if (!r.ok) throw new Error(r.status === 429 ? 'TOO_MANY_REQUESTS' : (data?.code ?? data?.message ?? `HTTP ${r.status}`))
  return data as T
}

/** Load the profile; when it fails (a deploy is starting the accounts server, the network is
 * flaky), try again a few times so a signed-in user isn't left looking signed out. Resolves once
 * an attempt succeeds or the last one failed. */
export async function loadProfile(retries = 4): Promise<void> {
  let p: ProfileResponse
  try {
    p = await call<ProfileResponse>('/profile')
  } catch {
    // Meanwhile Obľúbené and the profile say they can't load, rather than asking to sign in.
    profile.failed = true
    profile.loaded = true
    if (retries > 0) {
      await new Promise((r) => setTimeout(r, 3000))
      await loadProfile(retries - 1)
    }
    return
  }
  profile.user = p.user
  profile.favorites = p.favorites
  profile.passkeys = p.passkeys ?? []
  profile.preferences = p.preferences
  profile.mail = p.mail
  profile.failed = false
  profile.loaded = true
  // A star tapped while signed out (or while the profile couldn't load) pins now.
  const pin = profile.pending
  if (profile.user && pin) {
    profile.pending = null
    await setFavorite(pin.kind, pin.ref, true, pin.names)
  }
}

/** Where the link in a verification email returns to. */
const VERIFIED_URL = '/ucet?overene=1'

/** Run a sign-in step; when it fails, PostHog gets the step and Better Auth's error code (never
 * the email or what was typed). */
async function attempt<T>(event: string, method: string, fn: () => Promise<T>): Promise<T> {
  try {
    return await fn()
  } catch (e) {
    track(event, { method, error: (e as Error).message })
    throw e
  }
}

/** Sign in or up; false when the account also asks for a code (then call verifyCode). */
export async function signIn(mode: 'sign-in' | 'sign-up', email: string, password: string): Promise<boolean> {
  // Better Auth requires a name; the app doesn't ask for one.
  const r = await attempt(mode === 'sign-up' ? 'sign_up_failed' : 'sign_in_failed', 'password', () =>
    call<{ twoFactorRedirect?: boolean }>(
      `/${mode}/email`,
      mode === 'sign-up' ? { email, password, name: '', callbackURL: VERIFIED_URL } : { email, password },
    ),
  )
  if (r?.twoFactorRedirect) {
    track('two_factor_asked')
    return false
  }
  track(mode === 'sign-up' ? 'account_created' : 'signed_in', mode === 'sign-up' ? undefined : { method: 'password' })
  await loadProfile()
  return true
}

/** The second step of signing in: a code from the authenticator app, or a backup code. A trusted
 * device isn't asked again for 30 days. */
export async function verifyCode(code: string, backup: boolean, trustDevice: boolean): Promise<void> {
  const method = backup ? 'backup_code' : 'authenticator'
  await attempt('sign_in_failed', method, () => call(backup ? '/two-factor/verify-backup-code' : '/two-factor/verify-totp', { code, trustDevice }))
  track('signed_in', { method, trust_device: trustDevice })
  await loadProfile()
}

/** Sign in with a passkey: the browser asks which one, then the device unlocks it. */
export async function signInWithPasskey(): Promise<void> {
  await attempt('sign_in_failed', 'passkey', async () => {
    const { startAuthentication } = await import('@simplewebauthn/browser')
    const optionsJSON = await call<Parameters<typeof startAuthentication>[0]['optionsJSON']>('/passkey/generate-authenticate-options')
    const response = await startAuthentication({ optionsJSON }).catch(webAuthnError)
    await call('/passkey/verify-authentication', { response })
  })
  track('signed_in', { method: 'passkey' })
  await loadProfile()
}

/** Adding a passkey asks for the password: a passkey alone signs in. */
export async function addPasskey(password: string): Promise<void> {
  await attempt('passkey_add_failed', 'passkey', async () => {
    await call('/profile/confirm-password', { password })
    const { startRegistration } = await import('@simplewebauthn/browser')
    const optionsJSON = await call<Parameters<typeof startRegistration>[0]['optionsJSON']>('/passkey/generate-register-options')
    const response = await startRegistration({ optionsJSON }).catch(webAuthnError)
    await call('/passkey/verify-registration', { response })
  })
  track('passkey_added')
  await loadProfile()
}

export async function removePasskey(id: string): Promise<void> {
  await call('/passkey/delete-passkey', { id })
  track('passkey_removed')
  await loadProfile()
}

/** The browser's WebAuthn errors as the app's codes: the user closed the dialog, or the passkey
 * is already on this account. */
function webAuthnError(e: Error & { code?: string }): never {
  if (e.name === 'NotAllowedError' || e.name === 'AbortError') throw new Error('PASSKEY_CANCELLED')
  if (e.code === 'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED') throw new Error('PREVIOUSLY_REGISTERED')
  throw new Error('PASSKEY_FAILED')
}

/** Start turning on two-step sign-in: the secret to add to an authenticator app, and backup codes.
 * It is on once confirmTwoFactor() checks a code from the app. */
export async function enableTwoFactor(password: string): Promise<{ totpURI: string; backupCodes: string[] }> {
  const r = await call<{ totpURI: string; backupCodes: string[] }>('/two-factor/enable', { password })
  track('two_factor_setup_started')
  return r
}

export async function confirmTwoFactor(code: string): Promise<void> {
  await call('/two-factor/verify-totp', { code })
  track('two_factor_enabled')
  await loadProfile()
}

export async function disableTwoFactor(password: string): Promise<void> {
  await call('/two-factor/disable', { password })
  track('two_factor_disabled')
  await loadProfile()
}

/** New backup codes; the old ones stop working. */
export async function newBackupCodes(password: string): Promise<string[]> {
  const { backupCodes } = await call<{ backupCodes: string[] }>('/two-factor/generate-backup-codes', { password })
  track('backup_codes_renewed')
  return backupCodes
}

export async function signOut(): Promise<void> {
  await call('/sign-out', {})
  track('signed_out')
  profile.user = null
  profile.favorites = []
  profile.preferences = {}
}

export async function deleteAccount(password: string): Promise<void> {
  await call('/delete-user', { password })
  track('account_deleted')
  profile.user = null
  profile.favorites = []
  profile.preferences = {}
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  // Other devices are signed out: the old password may be why it changes.
  await call('/change-password', { currentPassword, newPassword, revokeOtherSessions: true })
  track('password_changed')
}

/** The new address gets a link; the email changes when it is opened. The password is asked for
 * so a stolen session can't move the account to another address. */
export async function changeEmail(newEmail: string, password: string): Promise<void> {
  await call('/change-email', { newEmail, password, callbackURL: VERIFIED_URL })
  track('email_change_requested')
  await loadProfile()
}

export async function resendVerification(): Promise<void> {
  if (!profile.user) return
  await call('/send-verification-email', { email: profile.user.email, callbackURL: VERIFIED_URL })
  track('verification_email_resent')
}

/** Emails a link to set a new password; the same answer whether the address has an account or not. */
export async function requestPasswordReset(email: string): Promise<void> {
  await call('/request-password-reset', { email, redirectTo: '/ucet' })
  track('password_reset_requested')
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  await call('/reset-password', { token, newPassword })
  track('password_reset')
}

export async function signOutOthers(): Promise<void> {
  await call('/revoke-other-sessions', {})
  track('other_devices_signed_out')
}

export async function setPreferences(p: { [K in keyof Preferences]: Preferences[K] | null }): Promise<void> {
  profile.preferences = (await call<{ preferences: Preferences }>('/profile/preferences', p)).preferences
  // Values are the app's own choices (such as start: map); null is back to the default.
  for (const [key, value] of Object.entries(p)) track('preference_changed', { key, value: value ?? 'default' })
}

export function isFavorite(kind: FavoriteKind, ref: string | null): boolean {
  return !!ref && profile.favorites.some((f) => f.kind === kind && f.ref === ref)
}

/** Pin or unpin. Signed out, it opens the account panel and pins after sign-in. */
export async function setFavorite(kind: FavoriteKind, ref: string, on: boolean, names: Favorite['names'] = null): Promise<void> {
  if (!profile.user) {
    profile.pending = on ? { kind, ref, names } : null
    navigate({ kind: 'account' })
    return
  }
  const before = profile.favorites
  profile.favorites = on
    ? [...before.filter((f) => !(f.kind === kind && f.ref === ref)), { kind, ref, names, createdAt: new Date().toISOString() }]
    : before.filter((f) => !(f.kind === kind && f.ref === ref))
  try {
    if (on) await call('/profile/favorites', names ? { kind, ref, names } : { kind, ref })
    else await call('/profile/favorites/remove', { kind, ref })
    track(on ? 'favorite_added' : 'favorite_removed', { kind })
  } catch (e) {
    profile.favorites = before
    // The session expired or was signed out on another device: sign in again, then it pins.
    if ((e as Error).message === 'UNAUTHORIZED') {
      profile.user = null
      profile.favorites = []
      await setFavorite(kind, ref, on, names)
    }
  }
}

// --- routes -------------------------------------------------------------------------------------

const isPoint = (v: string) => /^-?[\d.]+,-?[\d.]+$/.test(v)

/** The favourite of a planned route: "Moja poloha" is pinned as HERE, map points with their name. */
export function routeFavorite(from: string | null, to: string | null): { ref: string; names: Favorite['names'] } | null {
  if (!from || !to) return null
  const end = (v: string) => (isHere(v) ? HERE : v)
  const names: { from?: string; to?: string } = {}
  for (const [k, v] of [['from', from], ['to', to]] as const)
    if (isPoint(v) && end(v) !== HERE) names[k] = app.placeNames[v] ?? 'Bod na mape'
  return { ref: `${end(from)}>${end(to)}`, names: Object.keys(names).length ? names : null }
}

export function routeEnds(f: Favorite): { from: string; to: string } {
  const [from, to] = f.ref.split('>')
  return { from, to }
}

/** A route end's label in the favourites list. */
export function endLabel(f: Favorite, end: 'from' | 'to'): string {
  const v = routeEnds(f)[end]
  if (v === HERE) return MY_LOCATION
  if (isPoint(v)) return f.names?.[end] ?? 'Bod na mape'
  return app.stations[v]?.name ?? v
}

function here(): Promise<string | null> {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null)
    navigator.geolocation.getCurrentPosition(
      (p) => resolve(pointValue(p.coords.latitude, p.coords.longitude)),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 },
    )
  })
}

/** The view a favourite opens. A route from or to HERE first asks for the location; without it
 * that end stays empty to fill in. */
export async function favoriteView(f: Favorite): Promise<View> {
  if (f.kind === 'station') return { kind: 'station', code: f.ref, stop: null }
  if (f.kind === 'line') return { kind: 'line', line: f.ref, dir: null }
  const ends = routeEnds(f)
  const names: Record<string, string> = {}
  let loc: string | null | undefined
  const out: Record<'from' | 'to', string | null> = { from: null, to: null }
  for (const end of ['from', 'to'] as const) {
    let v: string | null = ends[end]
    if (v === HERE) {
      loc = loc === undefined ? await here() : loc
      v = loc
      if (v) names[markHere(v)] = MY_LOCATION
    } else if (isPoint(v)) names[v] = f.names?.[end] ?? 'Bod na mape'
    out[end] = v
  }
  app.placeNames = { ...app.placeNames, ...names }
  return { kind: 'plan', from: out.from, to: out.to, at: null, opt: null }
}
