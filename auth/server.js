// User accounts (Better Auth) for MHD naživo: sign-up and sign-in with an email and a password,
// sessions, and the profile (profile.js). The FastAPI server starts this process next to itself
// (mhd/accounts.py) and forwards /api/auth/* to it, so it only listens on 127.0.0.1.
//
// Environment:
//   MHD_DATA_DIR        the data directory; accounts live in <data>/accounts/auth.db (SQLite)
//   AUTH_PORT           the port to listen on (default 8790)
//   BETTER_AUTH_SECRET  signs session cookies; without it one is generated in <data>/accounts/secret
//   MHD_PASSKEY_HOST    the host passkeys belong to (default mhd.filiphupka.com); a passkey only
//                       works on that host, so a dev server sets its own (such as localhost:5173)
//   MHD_AUTH_HOSTS      more hosts the app is opened on, comma-separated, such as localhost:5173 or a
//                       dev portal's host; see baseURL
//   RESEND_API_KEY, MAIL_FROM  account emails (mail.js)
import { randomBytes } from 'node:crypto'
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { passkey } from '@better-auth/passkey'
import { betterAuth } from 'better-auth'
import { APIError, createAuthMiddleware, getSessionFromCtx } from 'better-auth/api'
import { getMigrations } from 'better-auth/db/migration'
import { toNodeHandler } from 'better-auth/node'
import { twoFactor } from 'better-auth/plugins'
import { sendReset, sendVerification } from './mail.js'
import { passwordConfirmed, profile } from './profile.js'

const DAY_S = 86_400
const MAX_PASSKEYS = 20

/** A path in this app, such as /ucet?overene=1: where links in emails may return to. Absolute and
 * protocol-relative URLs (//host, /\\host) are refused, so a link can't hand its token elsewhere. */
const isAppPath = (v) => typeof v !== 'string' || /^\/(?![/\\])/.test(v)

/** Refuses the request unless body.password is the signed-in user's password. */
async function requirePassword(ctx) {
  const session = await getSessionFromCtx(ctx)
  if (!session) throw new APIError('UNAUTHORIZED')
  const account = await ctx.context.internalAdapter.findCredentialAccount(session.user.id)
  const p = ctx.body?.password
  const password = typeof p === 'string' && p.length <= 128 ? p : ''
  if (!password || !account?.password || !(await ctx.context.password.verify({ hash: account.password, password })))
    throw new APIError('BAD_REQUEST', { message: 'Invalid password', code: 'INVALID_PASSWORD' })
  return session
}

/** Rules Better Auth leaves to the app, checked before every endpoint. */
const guard = createAuthMiddleware(async (ctx) => {
  const body = ctx.body ?? {}
  if (![body.callbackURL, body.redirectTo, body.errorCallbackURL, ctx.query?.callbackURL].every(isAppPath))
    throw new APIError('FORBIDDEN', { message: 'Invalid callbackURL' })
  // Better Auth deletes without the password for a recent session; the app always asks for it.
  if (ctx.path === '/delete-user' && !body.password) throw new APIError('BAD_REQUEST', { message: 'Password required' })
  // Better Auth stores a sign-up's name and image as sent, of any size; the app sends no image
  // and an empty name, so nothing else is accepted (a 50 MB name would fill the data volume).
  if (ctx.path === '/sign-up/email' && (body.name ?? '') !== '') throw new APIError('BAD_REQUEST', { message: 'Invalid name' })
  if (ctx.path === '/sign-up/email' && body.image != null) throw new APIError('BAD_REQUEST', { message: 'Invalid image' })
  // Addresses are at most 254 characters (RFC 5321); longer ones would only be stored and logged.
  if (String(body.email ?? body.newEmail ?? '').length > 254) throw new APIError('BAD_REQUEST', { message: 'Invalid email' })
  // Better Auth changes the email with the session alone, and the old address isn't told: a stolen
  // session could move the account to another address and reset its password. Ask for it.
  if (ctx.path === '/change-email') await requirePassword(ctx)
  // A passkey signs in without the password or the second step, and outlives a password change:
  // a stolen session must not add one. The app never names passkeys (a name has no size limit).
  // The password is confirmed (/profile/confirm-password) before the browser's prompt, so a wrong
  // one doesn't leave the device with a passkey the server refuses.
  if (ctx.path === '/passkey/generate-register-options' || ctx.path === '/passkey/verify-registration') {
    if (body.name != null) throw new APIError('BAD_REQUEST', { message: 'Invalid name' })
    const session = await getSessionFromCtx(ctx)
    if (!session || !passwordConfirmed(session.session.token, ctx.path === '/passkey/verify-registration'))
      throw new APIError('FORBIDDEN', { message: 'Confirm the password first', code: 'PASSWORD_NOT_CONFIRMED' })
    const n = await ctx.context.adapter.count({ model: 'passkey', where: [{ field: 'userId', value: session.user.id }] })
    if (n >= MAX_PASSKEYS) throw new APIError('BAD_REQUEST', { message: 'Too many passkeys', code: 'TOO_MANY_PASSKEYS' })
  }
  // Someone may create an account with another person's address and add a second factor; the
  // owner takes it back with a password reset, which must then also drop that person's
  // authenticator app and passkeys. A verified account keeps them: the inbox alone must not
  // get past the second step.
  if (ctx.path === '/reset-password') {
    const token = body.token || ctx.query?.token
    const v = typeof token === 'string' && (await ctx.context.internalAdapter.findVerificationValue(`reset-password:${token}`))
    const user = v && v.expiresAt > new Date() && (await ctx.context.internalAdapter.findUserById(v.value))
    if (user && !user.emailVerified) {
      for (const model of ['twoFactor', 'passkey'])
        await ctx.context.adapter.deleteMany({ model, where: [{ field: 'userId', value: user.id }] })
      if (user.twoFactorEnabled) await ctx.context.internalAdapter.updateUser(user.id, { twoFactorEnabled: false })
    }
  }
  // A link that moves the account to another address dies with a new password: whoever created
  // an account with someone else's address must not take it back with a link asked for before
  // the owner reset the password. (Better Auth still checks the token's signature afterwards.)
  if (ctx.path === '/verify-email' && typeof ctx.query?.token === 'string') {
    let jwt = null
    try {
      jwt = JSON.parse(Buffer.from(ctx.query.token.split('.')[1], 'base64url').toString())
    } catch {}
    if (jwt?.updateTo && typeof jwt.userId === 'string' && typeof jwt.iat === 'number') {
      const account = await ctx.context.internalAdapter.findCredentialAccount(jwt.userId)
      // iat is in whole seconds: a second's slack keeps a link asked for just after signing up.
      if (account && new Date(account.updatedAt).getTime() > (jwt.iat + 1) * 1000) throw ctx.redirect('/ucet?error=INVALID_TOKEN')
    }
  }
})

const passkeyOrigin = (host) => (/^(localhost|127\.0\.0\.1)(:|$)/.test(host) ? `http://${host}` : `https://${host}`)

/** The Better Auth options for a database file; the secret is kept next to it. */
export function authOptions(dir) {
  mkdirSync(dir, { recursive: true })
  const db = new DatabaseSync(join(dir, 'auth.db'))
  db.exec('PRAGMA journal_mode = WAL')
  const passkeyHost = process.env.MHD_PASSKEY_HOST || 'mhd.filiphupka.com'
  return {
    database: db,
    secret: process.env.BETTER_AUTH_SECRET || fileSecret(join(dir, 'secret')),
    // Only the FastAPI server reaches this process; it forwards the browser's host and scheme, so
    // the base URL (the trusted origin, and the links in emails) is the address the visitor opened,
    // if it is one of ours: links in a password reset email must never point to another host.
    // Exact hosts only: Better Auth also trusts these as origins and redirect targets, so a
    // wildcard such as *.up.railway.app would let anyone's Railway app receive reset tokens.
    baseURL: {
      allowedHosts: [
        'mhd.filiphupka.com',
        'web-production-b357ed31.up.railway.app', // the service's Railway domain
        ...(process.env.MHD_AUTH_HOSTS ?? '').split(',').filter(Boolean),
      ],
      fallback: 'https://mhd.filiphupka.com',
    },
    basePath: '/api/auth',
    advanced: { trustedProxyHeaders: true, ipAddress: { ipAddressHeaders: ['x-forwarded-for'] } },
    hooks: { before: guard },
    // Endpoints the app doesn't use: /update-user stores name and image of any size, and
    // /verify-password would let a stolen session guess the password.
    // Two-step codes by email aren't offered, and the TOTP secret is shown only when turning it on.
    disabledPaths: [
      '/update-user',
      '/verify-password',
      '/two-factor/send-otp',
      '/two-factor/verify-otp',
      '/two-factor/get-totp-uri',
      '/passkey/update-passkey',
    ],
    emailAndPassword: {
      enabled: true,
      minPasswordLength: 8,
      maxPasswordLength: 128,
      // Signing up signs in at once. Better Auth then answers "already exists" for a taken address,
      // which tells anyone that the address has an account; accepted for an app with no private
      // data beyond favourites (sign-ups are rate limited).
      autoSignIn: true,
      // Not awaited: an existing address must not answer slower than an unknown one.
      sendResetPassword: async ({ user, url }) => void sendReset(user.email, url),
      // A new password signs out every device, in case the old one was stolen.
      revokeSessionsOnPasswordReset: true,
    },
    // Verification isn't required to use the account, nor to reset a forgotten password: opening
    // the reset link proves the address too, and it is how the owner takes back an account someone
    // else created with their address.
    emailVerification: {
      sendVerificationEmail: async ({ user, url }) => void sendVerification(user.email, url),
      sendOnSignUp: true,
      // Someone may sign up with another person's address: the owner's click verifies it but
      // must not sign them in to an account whose password someone else knows.
      autoSignInAfterVerification: false,
    },
    user: {
      deleteUser: { enabled: true },
      // The new address always gets a link, and the email changes when it is opened: nobody can
      // take an address they don't own, verified account or not.
      changeEmail: { enabled: true, updateEmailWithoutVerification: false },
    },
    session: { expiresIn: 90 * DAY_S, updateAge: DAY_S },
    // Sessions keep no IP address or browser: the privacy page says so. Rate limits still see the
    // IP, in memory only.
    databaseHooks: {
      session: { create: { before: async (s) => ({ data: { ...s, ipAddress: null, userAgent: null } }) } },
      // Opening the link sent to a new address verifies it, also for an account whose old address
      // was never verified (Better Auth only changes the email then).
      user: {
        update: {
          before: async (u, ctx) => (ctx?.path === '/verify-email' && u.email ? { data: { ...u, emailVerified: true } } : undefined),
        },
        // Email-link tokens and "trust this device" records point to the user without a foreign key.
        delete: { after: async (u) => void db.prepare('DELETE FROM verification WHERE value = ?').run(u.id) },
      },
    },
    // Reset tokens are stored hashed: a copy of the database can't reset passwords.
    verification: { storeIdentifier: 'hashed' },
    // Per IP. Better Auth's defaults (3 per 10 s for sign-up, 3 per 60 s for emails) still let
    // one address send dozens of emails an hour; mail.js also limits each recipient.
    rateLimit: {
      enabled: true,
      storage: 'memory',
      customRules: {
        '/sign-up/email': { window: 3600, max: 10 },
        '/change-email': { window: 3600, max: 5 },
        '/send-verification-email': { window: 3600, max: 5 },
        '/request-password-reset': { window: 3600, max: 5 },
        '/delete-user': { window: 300, max: 10 },
        // Password guesses: Better Auth's default allows 18 a minute.
        '/sign-in/email': { window: 300, max: 10 },
        '/change-password': { window: 300, max: 10 },
        '/two-factor/enable': { window: 300, max: 10 },
        '/two-factor/disable': { window: 300, max: 10 },
        '/two-factor/generate-backup-codes': { window: 300, max: 10 },
        '/profile/confirm-password': { window: 300, max: 10 },
        // Second-factor codes: each sign-in also allows only a few tries (Better Auth counts them).
        '/two-factor/verify-totp': { window: 300, max: 10 },
        '/two-factor/verify-backup-code': { window: 300, max: 10 },
        '/passkey/verify-authentication': { window: 60, max: 10 },
      },
    },
    telemetry: { enabled: false },
    plugins: [
      profile(),
      // Two-step sign-in with an authenticator app (TOTP), and backup codes; both stored
      // encrypted with the secret. Turning it on, off, or getting new codes asks for the password.
      twoFactor({ issuer: 'MHD naživo' }),
      // Passkeys sign in without the password (or the second step: a passkey is two factors).
      passkey({ rpID: passkeyHost.replace(/:\d+$/, ''), rpName: 'MHD naživo', origin: passkeyOrigin(passkeyHost) }),
    ],
  }
}

function fileSecret(path) {
  if (!existsSync(path)) {
    writeFileSync(path, randomBytes(32).toString('base64'), { mode: 0o600 })
    chmodSync(path, 0o600)
  }
  return readFileSync(path, 'utf8').trim()
}

/** Create or update the tables, then return the auth instance. */
export async function createAuth(dir) {
  const options = authOptions(dir)
  const { runMigrations } = await getMigrations(options)
  await runMigrations()
  return betterAuth(options)
}

if (import.meta.main) {
  const dir = join(process.env.MHD_DATA_DIR ?? join(import.meta.dirname, '..', 'data'), 'accounts')
  const auth = await createAuth(dir)
  const port = Number(process.env.AUTH_PORT ?? 8790)
  const server = createServer(toNodeHandler(auth)).listen(port, '127.0.0.1', () =>
    console.log(`accounts listening on 127.0.0.1:${port}`),
  )
  process.on('SIGTERM', () => server.close(() => process.exit(0)))
  // Better Auth deletes an expired session only when its cookie comes back: rows of devices that
  // never return, and expired email-link tokens, go once a day (dates are ISO text).
  const db = new DatabaseSync(join(dir, 'auth.db'))
  const purge = () => {
    const now = new Date().toISOString()
    for (const table of ['session', 'verification']) db.prepare(`DELETE FROM ${table} WHERE expiresAt < ?`).run(now)
  }
  purge()
  setInterval(purge, DAY_S * 1000).unref()
}
