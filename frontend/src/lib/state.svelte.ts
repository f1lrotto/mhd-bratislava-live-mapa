import type { CityStatus, LineInfo, LineView, Live, StopInfo, VehicleType } from './types'

// What the side panel / bottom sheet shows. Each view has a URL so it can be shared:
//   /linka/83?smer=1   /vozidlo/1843   /zastavka/<stop id>   /stav   /linky   /filtre
export type View =
  | { kind: 'none' }
  | { kind: 'line'; line: string; dir: string | null }
  | { kind: 'vehicle'; key: string }
  | { kind: 'stop'; id: string }
  | { kind: 'status' }
  | { kind: 'lines' }
  | { kind: 'filters' }

export interface Filters {
  types: VehicleType[] // empty = all
  lines: string[] // empty = all
  late: boolean // 3+ min late only
}

export const POLL_MS = 30_000
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
  view = $state.raw<View>({ kind: 'none' })
  filters = $state.raw<Filters>({ types: [], lines: [], late: false })
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
  else if (parts[0] === 'zastavka' && parts[1]) view = { kind: 'stop', id: parts[1] }
  else if (parts[0] === 'stav') view = { kind: 'status' }
  else if (parts[0] === 'linky') view = { kind: 'lines' }
  else if (parts[0] === 'filtre') view = { kind: 'filters' }
  const list = (k: string) => (q.get(k) ?? '').split(',').map((s) => s.trim()).filter(Boolean)
  return {
    view,
    filters: {
      types: list('typ').map((t) => TYPE_PARAM[t]).filter(Boolean),
      lines: list('linky'),
      late: q.get('meskanie') === '1',
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
    case 'stop':
      path = `/zastavka/${encodeURIComponent(view.id)}`
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
  }
  if (filters.types.length) q.set('typ', filters.types.map((t) => TYPE_NAME[t]).join(','))
  if (filters.lines.length) q.set('linky', filters.lines.join(','))
  if (filters.late) q.set('meskanie', '1')
  const qs = q.toString().replaceAll('%2C', ',')
  return qs ? `${path}?${qs}` : path
}

/** Change the view, recording it in the URL and browser history. */
/** The control that opened the first panel (a nav button, or the map), for returning focus. */
let opener: HTMLElement | null = null

export function navigate(view: View, opts: { replace?: boolean } = {}): void {
  if (app.view.kind === 'none' && view.kind !== 'none') {
    const a = document.activeElement as HTMLElement | null
    opener = a && a !== document.body ? a : (document.querySelector('.maplibregl-canvas') as HTMLElement | null)
  }
  app.view = view
  syncUrl(opts.replace)
}

export function setFilters(f: Partial<Filters>): void {
  app.filters = { ...app.filters, ...f }
  syncUrl(true)
}

function syncUrl(replace = false): void {
  const url = buildUrl(app.view, app.filters)
  if (url === location.pathname + location.search) return
  if (replace) history.replaceState(null, '', url)
  else history.pushState(null, '', url)
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

export function filtersActive(f: Filters = app.filters): number {
  return (f.types.length ? 1 : 0) + (f.lines.length ? 1 : 0) + (f.late ? 1 : 0)
}
