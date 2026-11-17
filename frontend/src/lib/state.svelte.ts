import { track } from './analytics.svelte'
import type { CityStatus, LineInfo, LineView, Live, Plan, StationInfo, StopInfo, VehicleType } from './types'

// What the side panel / bottom sheet shows. Each view has a URL so it can be shared:
//   /linka/83?smer=1   /vozidlo/1843   /zastavka/<station code>?nastupiste=<stop id>   /stav   /linky   /filtre   /sukromie
//   /trasa?z=<code|lat,lon>&do=<code|lat,lon>&cas=<ISO>&moznost=<1-based option>
// Old /zastavka/<stop id> links are mapped to the stop's station by the station panel.
export type View =
  | { kind: 'none' }
  | { kind: 'line'; line: string; dir: string | null }
  | { kind: 'vehicle'; key: string }
  | { kind: 'station'; code: string; stop: string | null }
  | { kind: 'plan'; from: string | null; to: string | null; at: string | null; opt: number | null }
  | { kind: 'status' }
  | { kind: 'lines' }
  | { kind: 'filters' }
  | { kind: 'privacy' }

export interface Filters {
  types: VehicleType[] // empty = all
  lines: string[] // empty = all
  late: boolean // 5+ min late only
  regional: boolean // IDS BK regional buses shown (they don't count as DPB's buses in `types`)
  parked: boolean // parked vehicles shown (see `isParked`)
}

export const POLL_MS = 15_000
/** For views that change slowly (city status, journey plans). */
export const SLOW_POLL_MS = 30_000
export const FEED_DOWN_MS = 3 * 60_000

// Raw state: every value is replaced as a whole, never mutated, so 640 vehicles aren't proxied.
class AppState {
  live = $state.raw<Live | null>(null)
  /** Client time of the last successful /api/live response. */
  lastOk = $state.raw(0)
  /** Server clock minus client clock, so "updated 12 s ago" is right on phones with a wrong clock. */
  skewMs = $state.raw(0)
  fetchError = $state.raw<string | null>(null)
  lines = $state.raw<Record<string, LineInfo>>({})
  stops = $state.raw<Record<string, StopInfo>>({})
  stations = $state.raw<Record<string, StationInfo>>({})
  /** The last plan response, kept while a vehicle opened from it is shown so "back" is instant. */
  plan = $state.raw<{ query: string; data: Plan | null; error: string | null; loading: boolean } | null>(null)
  /** The planner field the next map tap fills, while "Vybrať na mape" is on. */
  pick = $state.raw<'from' | 'to' | null>(null)
  /** Display names of coordinate points ("Moja poloha", "Bod na mape"), keyed by the "lat,lon" value. */
  placeNames = $state.raw<Record<string, string>>({})
  /** The previous history entry is another panel of this app, so the panel shows a back button. */
  canBack = $state.raw(false)
  view = $state.raw<View>({ kind: 'none' })
  filters = $state.raw<Filters>({ types: [], lines: [], late: false, regional: true, parked: true })
  /** The line whose view is wanted now; responses for other lines are dropped. */
  wantLine = $state.raw<string | null>(null)
  lineView = $state.raw<LineView | null>(null)
  lineViewError = $state.raw<string | null>(null)
  status = $state.raw<CityStatus | null>(null)
  /** Set when the user asks to centre the map on something (a ribbon tap, a deep link). */
  focus = $state.raw<{ lon: number; lat: number; zoom?: number; seq: number } | null>(null)
  /** Updated every second so relative times re-render. */
  tick = $state.raw(Date.now())
}

export const app = new AppState()

// --- URL state --------------------------------------------------------------------------------

const TYPE_PARAM: Record<string, VehicleType> = { autobus: 'bus', trolejbus: 'trolleybus', elektricka: 'tram' }
const TYPE_NAME: Record<VehicleType, string> = { bus: 'autobus', trolleybus: 'trolejbus', tram: 'elektricka', other: 'ine' }

export function parseUrl(loc: Location = location): { view: View; filters: Filters } {
  const parts = loc.pathname.split('/').filter(Boolean).map(decodeURIComponent)
  const q = new URLSearchParams(loc.search)
  let view: View = { kind: 'none' }
  if (parts[0] === 'linka' && parts[1]) view = { kind: 'line', line: parts[1], dir: q.get('smer') }
  else if (parts[0] === 'vozidlo' && parts[1]) view = { kind: 'vehicle', key: parts[1] }
  else if (parts[0] === 'zastavka' && parts[1]) view = { kind: 'station', code: parts[1], stop: q.get('nastupiste') }
  else if (parts[0] === 'trasa') {
    const n = parseInt(q.get('moznost') ?? '', 10)
    view = { kind: 'plan', from: q.get('z'), to: q.get('do'), at: q.get('cas'), opt: n >= 1 ? n - 1 : null }
  }
  else if (parts[0] === 'stav') view = { kind: 'status' }
  else if (parts[0] === 'linky') view = { kind: 'lines' }
  else if (parts[0] === 'filtre') view = { kind: 'filters' }
  else if (parts[0] === 'sukromie') view = { kind: 'privacy' }
  const list = (k: string) => (q.get(k) ?? '').split(',').map((s) => s.trim()).filter(Boolean)
  return {
    view,
    filters: {
      types: list('typ').map((t) => TYPE_PARAM[t]).filter(Boolean),
      lines: list('linky'),
      late: q.get('meskanie') === '1',
      regional: q.get('regionalne') !== '0',
      parked: q.get('odstavene') !== '0',
    },
  }
}

export function buildUrl(view: View, filters: Filters): string {
  let path = '/'
  const q = new URLSearchParams()
  switch (view.kind) {
    case 'line':
      path = `/linka/${encodeURIComponent(view.line)}`
      if (view.dir != null) q.set('smer', view.dir)
      break
    case 'vehicle':
      path = `/vozidlo/${encodeURIComponent(view.key)}`
      break
    case 'station':
      path = `/zastavka/${encodeURIComponent(view.code)}`
      if (view.stop) q.set('nastupiste', view.stop)
      break
    case 'plan':
      path = '/trasa'
      if (view.from) q.set('z', view.from)
      if (view.to) q.set('do', view.to)
      if (view.at) q.set('cas', view.at)
      if (view.opt != null) q.set('moznost', String(view.opt + 1))
      break
    case 'status':
      path = '/stav'
      break
    case 'lines':
      path = '/linky'
      break
    case 'filters':
      path = '/filtre'
      break
    case 'privacy':
      path = '/sukromie'
      break
  }
  if (filters.types.length) q.set('typ', filters.types.map((t) => TYPE_NAME[t]).join(','))
  if (filters.lines.length) q.set('linky', filters.lines.join(','))
  if (filters.late) q.set('meskanie', '1')
  if (!filters.regional) q.set('regionalne', '0')
  if (!filters.parked) q.set('odstavene', '0')
  const qs = q.toString().replaceAll('%2C', ',').replaceAll('%3A', ':')
  return qs ? `${path}?${qs}` : path
}

/** The control that opened the first panel (a nav button, or the map), for returning focus. */
let opener: HTMLElement | null = null

/** Change the view, recording it in the URL and browser history. */
export function navigate(view: View, opts: { replace?: boolean } = {}): void {
  if (app.view.kind === 'none' && view.kind !== 'none') {
    const a = document.activeElement as HTMLElement | null
    opener = a && a !== document.body ? a : (document.querySelector('.maplibregl-canvas') as HTMLElement | null)
  }
  const prev = app.view.kind
  app.view = view
  syncUrl(opts.replace, prev)
}

export function setFilters(f: Partial<Filters>): void {
  app.filters = { ...app.filters, ...f }
  syncUrl(true)
  const n = app.filters
  track('filters_changed', { changed: Object.keys(f), types: n.types, lines: n.lines, late: n.late, regional: n.regional, active: filtersActive(n) })
}

function syncUrl(replace = false, prev?: View['kind']): void {
  const url = buildUrl(app.view, app.filters)
  if (url === location.pathname + location.search) return
  if (replace || prev === undefined) history.replaceState(history.state, '', url)
  else {
    history.pushState({ prev }, '', url)
    syncBack()
  }
}

/** Read from history whether "back" returns to another panel. */
export function syncBack(): void {
  const prev = (history.state as { prev?: string } | null)?.prev
  app.canBack = prev != null && prev !== 'none' && app.view.kind !== 'none'
}

export function closePanel(): void {
  navigate({ kind: 'none' })
  const target = opener?.isConnected ? opener : (document.querySelector('.maplibregl-canvas') as HTMLElement | null)
  target?.focus({ preventScroll: true })
  opener = null
}

export function focusOn(lon: number, lat: number, zoom?: number): void {
  app.focus = { lon, lat, zoom, seq: (app.focus?.seq ?? 0) + 1 }
}

/** Seconds since the server last polled the feed successfully, in server time. */
export function feedAgeS(): number | null {
  const polled = app.live?.feed.polledAt
  if (!polled) return null
  return Math.max(0, (app.tick + app.skewMs - Date.parse(polled)) / 1000)
}

/** True when the positions on screen can't be trusted: the feed or our connection to it is down. */
export function feedDown(): boolean {
  if (!app.live) return false
  const age = feedAgeS()
  return app.live.feed.down || (age != null && age * 1000 > FEED_DOWN_MS)
}

/** The same for the regional buses' source (IDS BK). Not down before its first sweep. */
export function regionalDown(): boolean {
  const f = app.live?.regionalFeed
  if (!f?.attemptedAt) return false
  const ageMs = f.polledAt ? app.tick + app.skewMs - Date.parse(f.polledAt) : null
  return f.down || (ageMs != null && ageMs > FEED_DOWN_MS)
}

export const NO_FILTERS: Filters = { types: [], lines: [], late: false, regional: true, parked: true }

export function filtersActive(f: Filters = app.filters): number {
  return (f.types.length ? 1 : 0) + (f.lines.length ? 1 : 0) + (f.late ? 1 : 0) + (f.regional ? 0 : 1) + (f.parked ? 0 : 1)
}
