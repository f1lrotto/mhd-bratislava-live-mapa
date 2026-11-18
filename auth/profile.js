// The profile: favourites (stations, lines, planner routes) and preferences of a signed-in user,
// as a Better Auth plugin so it shares the auth database, sessions and rate limits.
//
//   GET  /api/auth/profile                     { user, preferences, favorites, passkeys, mail }; user null when
//                                              signed out; mail: account emails can be sent
//   POST /api/auth/profile/favorites           { kind, ref, names? }  pins it (again: no change)
//   POST /api/auth/profile/favorites/remove    { kind, ref }
//   POST /api/auth/profile/preferences         { lang?, … }  a key set to null is removed
//   POST /api/auth/profile/confirm-password    { password }  for the next 5 minutes, this session may
//                                              add a passkey (asked before the browser's prompt)
//
// A favourite's ref is what the app's URLs use: a station code, a line, or a route
// "<from>><to>" whose ends are planner values (a station code or "lat,lon") or "here",
// the user's location when the route is opened (never stored as coordinates).
import { APIError, createAuthEndpoint, getSessionFromCtx, sessionMiddleware } from 'better-auth/api'
import * as z from 'zod'
import { mailEnabled } from './mail.js'

export const MAX_FAVORITES = 200

const CONFIRM_MS = 5 * 60_000
/** Session token -> when its password was last confirmed (in memory: a restart asks again). */
const confirmed = new Map()

/** Whether this session confirmed its password in the last 5 minutes; `use` spends it. */
export function passwordConfirmed(token, use = false) {
  const at = confirmed.get(token)
  if (use) confirmed.delete(token)
  return at !== undefined && Date.now() - at < CONFIRM_MS
}

const ID = /^[\p{L}\p{N}:._-]{1,60}$/u
const POINT = /^-?\d{1,3}(\.\d{1,6})?,-?\d{1,3}(\.\d{1,6})?$/
const isEnd = (s) => s === 'here' || POINT.test(s) || ID.test(s)

const Favorite = z
  .object({
    kind: z.enum(['station', 'line', 'route']),
    ref: z.string().max(130),
    /** Display names of a route's point ends ("Domov", "Bod na mape"); stations have their own. */
    names: z.object({ from: z.string().max(80).optional(), to: z.string().max(80).optional() }).strict().optional(),
  })
  .refine(
    (f) => (f.kind === 'route' ? f.ref.split('>').length === 2 && f.ref.split('>').every(isEnd) : ID.test(f.ref)),
    { message: 'bad ref' },
  )

/** Every preference the app knows, each optional (unset is the default). A new one is a new key
 * here and in Preferences in frontend/src/lib/profile.svelte.ts. */
const Preferences = z
  .object({
    /** The UI language. */
    lang: z.enum(['sk', 'en']).nullable().optional(),
    /** What the installed app opens to: the favourites (default) or the map. */
    start: z.enum(['favorites', 'map']).nullable().optional(),
    /** The colour theme; unset follows the device's setting. */
    theme: z.enum(['light', 'dark']).nullable().optional(),
  })
  .strict()

const prefsOf = (user) => {
  try {
    return JSON.parse(user.preferences || '{}')
  } catch {
    return {}
  }
}

const out = (f) => ({ kind: f.kind, ref: f.ref, names: f.names ? JSON.parse(f.names) : null, createdAt: f.createdAt })

export const profile = () => ({
  id: 'profile',
  schema: {
    user: {
      fields: {
        // JSON text: SQLite has no JSON column. Only /profile/preferences writes it (input: false).
        preferences: { type: 'string', required: false, input: false, returned: false },
      },
    },
    favorite: {
      fields: {
        userId: { type: 'string', required: true, references: { model: 'user', field: 'id', onDelete: 'cascade' }, index: true },
        kind: { type: 'string', required: true },
        ref: { type: 'string', required: true },
        names: { type: 'string', required: false },
        createdAt: { type: 'date', required: true },
      },
      indexes: [{ fields: ['userId', 'kind', 'ref'], unique: true }],
    },
  },
  endpoints: {
    getProfile: createAuthEndpoint('/profile', { method: 'GET' }, async (ctx) => {
      const session = await getSessionFromCtx(ctx)
      if (!session) return ctx.json({ user: null, preferences: {}, favorites: [], passkeys: [], mail: mailEnabled() })
      const uid = session.user.id
      const [user, favs, keys] = await Promise.all([
        ctx.context.adapter.findOne({ model: 'user', where: [{ field: 'id', value: uid }] }),
        ctx.context.adapter.findMany({
          model: 'favorite',
          where: [{ field: 'userId', value: uid }],
          sortBy: { field: 'createdAt', direction: 'asc' },
          limit: MAX_FAVORITES,
        }),
        ctx.context.adapter.findMany({ model: 'passkey', where: [{ field: 'userId', value: uid }] }),
      ])
      return ctx.json({
        user: {
          email: session.user.email,
          emailVerified: session.user.emailVerified,
          createdAt: session.user.createdAt,
          twoFactorEnabled: !!user?.twoFactorEnabled,
        },
        // What identifies each passkey to the user; the public key stays on the server.
        passkeys: keys.map((k) => ({ id: k.id, name: k.name ?? null, deviceType: k.deviceType, backedUp: !!k.backedUp, createdAt: k.createdAt })),
        preferences: prefsOf(user ?? {}),
        favorites: favs.map(out),
        mail: mailEnabled(),
      })
    }),

    addFavorite: createAuthEndpoint(
      '/profile/favorites',
      { method: 'POST', body: Favorite, use: [sessionMiddleware] },
      async (ctx) => {
        const uid = ctx.context.session.user.id
        const { kind, ref, names } = ctx.body
        const where = [
          { field: 'userId', value: uid },
          { field: 'kind', value: kind },
          { field: 'ref', value: ref },
        ]
        const existing = await ctx.context.adapter.findOne({ model: 'favorite', where })
        if (existing) return ctx.json({ favorite: out(existing) })
        const n = await ctx.context.adapter.count({ model: 'favorite', where: [{ field: 'userId', value: uid }] })
        if (n >= MAX_FAVORITES) throw new APIError('BAD_REQUEST', { message: 'too many favorites' })
        const f = await ctx.context.adapter.create({
          model: 'favorite',
          data: { userId: uid, kind, ref, names: names ? JSON.stringify(names) : null, createdAt: new Date() },
        })
        return ctx.json({ favorite: out(f) })
      },
    ),

    removeFavorite: createAuthEndpoint(
      '/profile/favorites/remove',
      {
        method: 'POST',
        body: z.object({ kind: z.enum(['station', 'line', 'route']), ref: z.string().max(130) }),
        use: [sessionMiddleware],
      },
      async (ctx) => {
        await ctx.context.adapter.deleteMany({
          model: 'favorite',
          where: [
            { field: 'userId', value: ctx.context.session.user.id },
            { field: 'kind', value: ctx.body.kind },
            { field: 'ref', value: ctx.body.ref },
          ],
        })
        return ctx.json({ ok: true })
      },
    ),

    confirmPassword: createAuthEndpoint(
      '/profile/confirm-password',
      { method: 'POST', body: z.object({ password: z.string().max(128) }), use: [sessionMiddleware] },
      async (ctx) => {
        const { session } = ctx.context.session
        const account = await ctx.context.internalAdapter.findCredentialAccount(ctx.context.session.user.id)
        if (!account?.password || !(await ctx.context.password.verify({ hash: account.password, password: ctx.body.password })))
          throw new APIError('BAD_REQUEST', { message: 'Invalid password', code: 'INVALID_PASSWORD' })
        const now = Date.now()
        for (const [k, at] of confirmed) if (now - at >= CONFIRM_MS) confirmed.delete(k)
        confirmed.set(session.token, now)
        return ctx.json({ ok: true })
      },
    ),

    setPreferences: createAuthEndpoint(
      '/profile/preferences',
      { method: 'POST', body: Preferences, use: [sessionMiddleware] },
      async (ctx) => {
        const uid = ctx.context.session.user.id
        const user = await ctx.context.adapter.findOne({ model: 'user', where: [{ field: 'id', value: uid }] })
        const prefs = { ...prefsOf(user ?? {}), ...ctx.body }
        for (const k of Object.keys(prefs)) if (prefs[k] == null) delete prefs[k]
        await ctx.context.internalAdapter.updateUser(uid, { preferences: JSON.stringify(prefs) })
        return ctx.json({ preferences: prefs })
      },
    ),
  },
})
