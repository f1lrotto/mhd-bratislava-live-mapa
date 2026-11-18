import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { test } from 'node:test'
import { createAuth } from './server.js'

const dir = mkdtempSync(join(tmpdir(), 'mhd-auth-'))
process.env.MHD_AUTH_HOSTS = 'localhost:8000'
const auth = await createAuth(dir)
const ORIGIN = 'http://localhost:8000'

// Emails go to Resend's API: capture them instead.
const mails = []
const realFetch = globalThis.fetch
process.env.RESEND_API_KEY = 'test'
delete process.env.MHD_MAIL // it would log the links instead of sending them here
globalThis.fetch = async (url, init) => {
  if (String(url) !== 'https://api.resend.com/emails') return realFetch(url, init)
  const m = JSON.parse(init.body)
  mails.push({ to: m.to[0], subject: m.subject, url: /https?:\/\/\S+/.exec(m.text)[0] })
  return new Response('{}', { status: 200 })
}
/** The link in the last email to an address (sending may finish just after the response). */
async function link(to) {
  for (let i = 0; i < 50 && !mails.some((m) => m.to === to); i++) await new Promise((r) => setTimeout(r, 10))
  const m = mails.findLast((x) => x.to === to)
  assert.ok(m, `no email to ${to}`)
  return m.url
}

/** A browser session: keeps the session cookie between calls, as the app's fetches do. */
function browser(ip, headers = {}) {
  let cookie = ''
  return async (path, body) => {
    const url = path.startsWith('http') ? path : `${ORIGIN}/api/auth${path}`
    const res = await auth.handler(
      new Request(url, {
        method: body ? 'POST' : 'GET',
        headers: { origin: ORIGIN, 'content-type': 'application/json', cookie, 'x-forwarded-for': ip, 'user-agent': 'Test/1', ...headers },
        body: body && JSON.stringify(body),
      }),
    )
    for (const c of res.headers.getSetCookie()) {
      const [kv] = c.split(';')
      const name = kv.split('=')[0]
      const jar = cookie ? cookie.split('; ').filter((x) => x.split('=')[0] !== name) : []
      if (!/Max-Age=0/i.test(c)) jar.push(kv)
      cookie = jar.join('; ')
    }
    const text = await res.text()
    const json = (res.headers.get('content-type') ?? '').includes('json')
    return { status: res.status, location: res.headers.get('location'), body: json && text ? JSON.parse(text) : text || null }
  }
}

test('favourites belong to their user and go with the account', async () => {
  const anna = browser('10.0.0.1')
  const ben = browser('10.0.0.2')
  assert.equal((await anna('/sign-up/email', { email: 'anna@example.sk', password: 'heslo-anna', name: '' })).status, 200)
  assert.equal((await ben('/sign-up/email', { email: 'ben@example.sk', password: 'heslo-ben1', name: '' })).status, 200)

  await anna('/profile/favorites', { kind: 'station', ref: '93' })
  await anna('/profile/favorites', { kind: 'route', ref: 'here>48.14520,17.10385', names: { to: 'Domov' } })
  await ben('/profile/favorites', { kind: 'line', ref: '83' })
  await anna('/profile/preferences', { lang: 'en', start: 'map', theme: 'dark' })
  await anna('/profile/preferences', { start: null })

  const a = (await anna('/profile')).body
  assert.equal(a.user.email, 'anna@example.sk')
  assert.deepEqual(a.preferences, { lang: 'en', theme: 'dark' })
  assert.deepEqual(
    a.favorites.map((f) => [f.kind, f.ref, f.names]),
    [
      ['station', '93', null],
      ['route', 'here>48.14520,17.10385', { to: 'Domov' }],
    ],
  )
  assert.deepEqual((await ben('/profile')).body.favorites.map((f) => f.ref), ['83'])

  // Removing Anna's station leaves Ben's favourites alone.
  await ben('/profile/favorites/remove', { kind: 'station', ref: '93' })
  assert.equal((await anna('/profile')).body.favorites.length, 2)
  await anna('/profile/favorites/remove', { kind: 'station', ref: '93' })
  assert.deepEqual((await anna('/profile')).body.favorites.map((f) => f.kind), ['route'])

  // Deleting the account (with its password) deletes its favourites and signs it out.
  assert.equal((await anna('/delete-user', { password: 'heslo-anna' })).status, 200)
  assert.equal((await anna('/profile')).body.user, null)
  const db = new DatabaseSync(join(dir, 'auth.db'))
  assert.deepEqual(db.prepare('select ref from favorite').all().map((r) => r.ref), ['83'])
  // Sessions keep no IP address or browser.
  assert.deepEqual(db.prepare('select ipAddress, userAgent from session').all().map((r) => ({ ...r })), [
    { ipAddress: null, userAgent: null },
  ])
})

test('writes need a session and a valid favourite', async () => {
  const anon = browser('10.0.0.3')
  assert.equal((await anon('/profile/favorites', { kind: 'station', ref: '93' })).status, 401)
  assert.deepEqual((await anon('/profile')).body, { user: null, preferences: {}, favorites: [], passkeys: [], mail: true })

  const c = browser('10.0.0.4')
  await c('/sign-up/email', { email: 'cyril@example.sk', password: 'heslo-cyril', name: '' })
  for (const bad of [
    { kind: 'route', ref: '93' }, // a route needs two ends
    { kind: 'route', ref: '93>' },
    { kind: 'station', ref: '93>94' },
    { kind: 'shop', ref: '1' },
  ])
    assert.equal((await c('/profile/favorites', bad)).status, 400, JSON.stringify(bad))
  assert.equal((await c('/profile/preferences', { font: 'large' })).status, 400)
  assert.equal((await c('/profile/preferences', { theme: 'blue' })).status, 400)
  assert.equal((await c('/profile/preferences', { lang: 'de' })).status, 400)
})

test('email verification, password change and reset', async () => {
  const dana = browser('10.0.0.5')
  await dana('/sign-up/email', { email: 'dana@example.sk', password: 'heslo-dana', name: '', callbackURL: '/ucet' })
  assert.equal((await dana('/profile')).body.user.emailVerified, false)

  // The link in the verification email verifies the address and returns to the app.
  const verify = await dana(await link('dana@example.sk'))
  assert.equal(verify.status, 302)
  assert.equal(verify.location, '/ucet')
  assert.equal((await dana('/profile')).body.user.emailVerified, true)

  // Changing the password needs the current one.
  assert.equal((await dana('/change-password', { currentPassword: 'zle-heslo-1', newPassword: 'nove-heslo-1' })).status, 400)
  assert.equal((await dana('/change-password', { currentPassword: 'heslo-dana', newPassword: 'nove-heslo-1' })).status, 200)

  // A forgotten password: the emailed link opens the app with a token, which sets a new password
  // and signs out every device.
  const other = browser('10.0.0.6')
  assert.equal((await other('/request-password-reset', { email: 'dana@example.sk', redirectTo: '/ucet' })).status, 200)
  const open = await other(await link('dana@example.sk'))
  const token = new URL(open.location, ORIGIN).searchParams.get('token')
  assert.ok(token)
  assert.equal((await other('/reset-password', { token, newPassword: 'tretie-heslo' })).status, 200)
  assert.equal((await dana('/profile')).body.user, null)
  await new Promise((r) => setTimeout(r, 100))
  assert.equal(mails.findLast((m) => m.to === 'dana@example.sk').subject, 'Heslo je obnovené')
  assert.equal((await other('/sign-in/email', { email: 'dana@example.sk', password: 'nove-heslo-1' })).status, 401)
  assert.equal((await other('/sign-in/email', { email: 'dana@example.sk', password: 'tretie-heslo' })).status, 200)
})

test('emailed links never point to a host that is not ours', async () => {
  await browser('10.0.0.12')('/sign-up/email', { email: 'hana@example.sk', password: 'heslo-hana', name: '' })
  await link('hana@example.sk')
  const sent = mails.length
  for (const origin of ['https://evil.example', 'https://mhd.filiphupka.com']) {
    const evil = browser('10.0.0.7', { origin, 'x-forwarded-host': 'evil.example', 'x-forwarded-proto': 'https' })
    await evil('/request-password-reset', { email: 'hana@example.sk', redirectTo: '/ucet' })
  }
  await new Promise((r) => setTimeout(r, 100))
  assert.ok(mails.length > sent, 'no reset email was sent')
  for (const m of mails.slice(sent)) assert.ok(m.url.startsWith('https://mhd.filiphupka.com/'), m.url)
})

test('reset and verification links only return to this app', async () => {
  const eve = browser('10.0.0.8')
  await eve('/sign-up/email', { email: 'eve@example.sk', password: 'heslo-eve-1', name: '' })
  // Each from its own address: password resets are rate limited per address.
  for (const [i, target] of ['https://evil.up.railway.app/steal', 'http://localhost:9999/x', '//evil.example/x', '/\\evil.example/x'].entries()) {
    const res = await browser(`10.0.1.${i}`)('/request-password-reset', { email: 'eve@example.sk', redirectTo: target })
    assert.equal(res.status, 403, `redirectTo ${target} was accepted`)
  }
  const res = await eve('/send-verification-email', { email: 'eve@example.sk', callbackURL: 'https://evil.up.railway.app/x' })
  assert.equal(res.status, 403)
})

test('deleting the account needs the password, also without the app', async () => {
  const f = browser('10.0.0.9')
  await f('/sign-up/email', { email: 'fero@example.sk', password: 'heslo-fero', name: '' })
  assert.equal((await f('/delete-user', {})).status, 400)
  assert.ok((await f('/profile')).body.user)
})

test('a verification link verifies the address but signs nobody in', async () => {
  // Someone signs up with another person's address; the owner clicks the link in their inbox.
  await browser('10.0.0.10')('/sign-up/email', { email: 'gita@example.sk', password: 'heslo-utocnika', name: '' })
  const owner = browser('10.0.0.11')
  const res = await owner(await link('gita@example.sk'))
  assert.equal(res.status, 302)
  assert.equal((await owner('/profile')).body.user, null)
})

test('nobody can store a huge name or image, or use the endpoints the app leaves out', async () => {
  const i = browser('10.0.0.13')
  const big = 'x'.repeat(100_000)
  assert.equal((await i('/sign-up/email', { email: 'ivo@example.sk', password: 'heslo-ivo-1', name: big })).status, 400)
  assert.equal((await i('/sign-up/email', { email: 'ivo@example.sk', password: 'heslo-ivo-1', name: '', image: big })).status, 400)
  assert.equal((await i('/sign-up/email', { email: 'ivo@example.sk', password: 'heslo-ivo-1', name: '' })).status, 200)
  assert.equal((await i('/update-user', { image: big })).status, 404)
  assert.equal((await i('/verify-password', { password: 'heslo-ivo-1' })).status, 404)
})

test('one address gets one email of a kind per two minutes, whoever asks', async () => {
  await browser('10.0.0.14')('/sign-up/email', { email: 'jana@example.sk', password: 'heslo-jana', name: '' })
  await link('jana@example.sk')
  const before = mails.filter((m) => m.to === 'jana@example.sk').length
  for (let k = 0; k < 3; k++) await browser(`10.0.2.${k}`)('/send-verification-email', { email: 'jana@example.sk' })
  await new Promise((r) => setTimeout(r, 100))
  assert.equal(mails.filter((m) => m.to === 'jana@example.sk').length, before)
})

test('changing the email needs the password and verifies the new address once confirmed', async () => {
  const k = browser('10.0.0.15')
  const pw = 'karol-' + 'heslo-1'
  await k('/sign-up/email', { email: 'karol@example.sk', password: pw, name: '' })
  // A stolen session alone can't move the account to another address.
  assert.equal((await k('/change-email', { newEmail: 'karol.novy@example.sk', callbackURL: '/ucet' })).status, 400)
  assert.equal((await k('/change-email', { newEmail: 'karol.novy@example.sk', password: pw + 'x', callbackURL: '/ucet' })).status, 400)
  assert.equal((await k('/change-email', { newEmail: 'karol.novy@example.sk', password: pw, callbackURL: '/ucet' })).status, 200)
  assert.equal((await k('/profile')).body.user.email, 'karol@example.sk')
  await k(await link('karol.novy@example.sk'))
  const { user } = (await k('/profile')).body
  assert.equal(user.email, 'karol.novy@example.sk')
  assert.equal(user.emailVerified, true)
})

test('two-step sign-in asks for an app code or a backup code, once each', async () => {
  const { createOTP } = await import('@better-auth/utils/otp')
  const { base32 } = await import('@better-auth/utils/base32')
  const m = browser('10.0.0.16')
  const pw = 'marek-' + 'heslo-1'
  await m('/sign-up/email', { email: 'marek@example.sk', password: pw, name: '' })
  assert.equal((await m('/two-factor/enable', {})).status, 400) // needs the password
  const { totpURI, backupCodes } = (await m('/two-factor/enable', { password: pw })).body
  const otp = createOTP(new TextDecoder().decode(base32.decode(new URL(totpURI).searchParams.get('secret'))))
  // Not on until a code from the app confirms it.
  assert.equal((await m('/profile')).body.user.twoFactorEnabled, false)
  assert.equal((await m('/two-factor/verify-totp', { code: await otp.totp() })).status, 200)
  assert.equal((await m('/profile')).body.user.twoFactorEnabled, true)

  // The password alone signs nobody in.
  const other = browser('10.0.0.17')
  const signIn = await other('/sign-in/email', { email: 'marek@example.sk', password: pw })
  assert.equal(signIn.body.twoFactorRedirect, true)
  assert.equal((await other('/profile')).body.user, null)
  assert.equal((await other('/two-factor/verify-totp', { code: '000000' })).status, 401)
  assert.equal((await other('/two-factor/verify-backup-code', { code: backupCodes[0] })).status, 200)
  assert.equal((await other('/profile')).body.user.email, 'marek@example.sk')

  // A backup code works once.
  const third = browser('10.0.0.18')
  await third('/sign-in/email', { email: 'marek@example.sk', password: pw })
  assert.notEqual((await third('/two-factor/verify-backup-code', { code: backupCodes[0] })).status, 200)
  assert.equal((await third('/profile')).body.user, null)

  // The secret is never shown again, and email codes aren't offered.
  assert.equal((await m('/two-factor/get-totp-uri', { password: pw })).status, 404)
  assert.equal((await m('/two-factor/send-otp', {})).status, 404)
})

test('a password reset kills a pending link that moves the account to another address', async () => {
  // Someone signs up with the owner's address and asks to move the account to their own.
  const squatter = browser('10.0.0.19')
  const pw = 'olga-' + 'heslo-1'
  await squatter('/sign-up/email', { email: 'olga@example.sk', password: pw, name: '' })
  assert.equal((await squatter('/change-email', { newEmail: 'squatter@example.sk', password: pw, callbackURL: '/ucet' })).status, 200)
  const moveLink = await link('squatter@example.sk')
  // The owner takes the account back with a password reset (seconds later: tokens carry whole seconds).
  await new Promise((r) => setTimeout(r, 2100))
  const owner = browser('10.0.0.20')
  await owner('/request-password-reset', { email: 'olga@example.sk', redirectTo: '/ucet' })
  const token = new URL((await owner(await link('olga@example.sk'))).location, ORIGIN).searchParams.get('token')
  assert.equal((await owner('/reset-password', { token, newPassword: pw + '-nove' })).status, 200)
  // The squatter's old link no longer moves it.
  const res = await browser('10.0.0.21')(moveLink)
  assert.equal(res.location, '/ucet?error=INVALID_TOKEN')
  await owner('/sign-in/email', { email: 'olga@example.sk', password: pw + '-nove' })
  assert.equal((await owner('/profile')).body.user.email, 'olga@example.sk')
})

test('a password reset takes an unverified account back from whoever added a second factor', async () => {
  const { createOTP } = await import('@better-auth/utils/otp')
  const { base32 } = await import('@better-auth/utils/base32')
  // Someone signs up with the owner's address and turns on two-step sign-in.
  const squatter = browser('10.0.0.22')
  const pw = 'petra-' + 'heslo-1'
  await squatter('/sign-up/email', { email: 'petra@example.sk', password: pw, name: '' })
  const { totpURI } = (await squatter('/two-factor/enable', { password: pw })).body
  const otp = createOTP(new TextDecoder().decode(base32.decode(new URL(totpURI).searchParams.get('secret'))))
  await squatter('/two-factor/verify-totp', { code: await otp.totp() })
  // Adding a passkey needs the password, confirmed before the browser's prompt.
  assert.equal((await squatter('/passkey/generate-register-options')).status, 403)
  assert.equal((await squatter('/profile/confirm-password', { password: pw + 'x' })).status, 400)
  assert.equal((await squatter('/profile/confirm-password', { password: pw })).status, 200)
  assert.equal((await squatter('/passkey/generate-register-options')).status, 200)
  // The owner resets the password and signs in without anyone's authenticator app.
  const owner = browser('10.0.0.23')
  await owner('/request-password-reset', { email: 'petra@example.sk', redirectTo: '/ucet' })
  const token = new URL((await owner(await link('petra@example.sk'))).location, ORIGIN).searchParams.get('token')
  assert.equal((await owner('/reset-password', { token, newPassword: pw + '-nove' })).status, 200)
  const signIn = await owner('/sign-in/email', { email: 'petra@example.sk', password: pw + '-nove' })
  assert.equal(signIn.body.twoFactorRedirect, undefined)
  assert.equal((await owner('/profile')).body.user.twoFactorEnabled, false)
})

test('a verified address is told about changes on its account; an unverified one is not', async () => {
  const { createOTP } = await import('@better-auth/utils/otp')
  const { base32 } = await import('@better-auth/utils/base32')
  const subjects = (to) => mails.filter((m) => m.to === to).map((m) => m.subject)
  const settle = () => new Promise((r) => setTimeout(r, 100))
  const pw = 'rado-' + 'heslo-1'
  const r = browser('10.0.0.24')
  await r('/sign-up/email', { email: 'rado@example.sk', password: pw, name: '' })
  await r(await link('rado@example.sk'))
  assert.equal((await r('/change-password', { currentPassword: pw, newPassword: pw + '2' })).status, 200)
  const { totpURI } = (await r('/two-factor/enable', { password: pw + '2' })).body
  const otp = createOTP(new TextDecoder().decode(base32.decode(new URL(totpURI).searchParams.get('secret'))))
  await r('/two-factor/verify-totp', { code: await otp.totp() })
  assert.equal((await r('/two-factor/disable', { password: pw + '2' })).status, 200)
  // A wrong password changes nothing and tells nobody.
  assert.equal((await r('/change-password', { currentPassword: 'zle-heslo-1', newPassword: pw + '3' })).status, 400)
  await settle()
  assert.deepEqual(subjects('rado@example.sk').slice(1), ['Heslo je zmenené', 'Dvojstupňové overenie je zapnuté', 'Dvojstupňové overenie je vypnuté'])
  // Moving to a new address tells the old one.
  await r('/change-email', { newEmail: 'rado.novy@example.sk', password: pw + '2', callbackURL: '/ucet' })
  await r(await link('rado.novy@example.sk'))
  await settle()
  assert.equal(subjects('rado@example.sk').at(-1), 'E-mail účtu je zmenený')
  assert.ok(mails.findLast((m) => m.to === 'rado@example.sk').url.endsWith('/ucet'))

  // An unverified account: its address gets the reset link, and nothing about the reset.
  const s = browser('10.0.0.25')
  await s('/sign-up/email', { email: 'sona@example.sk', password: pw, name: '' })
  await link('sona@example.sk')
  await s('/request-password-reset', { email: 'sona@example.sk', redirectTo: '/ucet' })
  const token = new URL((await s(await link('sona@example.sk'))).location, ORIGIN).searchParams.get('token')
  assert.equal((await s('/reset-password', { token, newPassword: pw + '2' })).status, 200)
  await settle()
  assert.deepEqual(subjects('sona@example.sk'), ['Overte svoj e-mail', 'Obnovenie hesla'])
})
