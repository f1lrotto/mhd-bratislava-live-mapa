import { track as trackEvent } from './analytics.svelte'
import { app, POLL_MS } from './state.svelte'
import type { CityStatus, LineInfo, LineView, Live, Plan, StationInfo, StopInfo } from './types'

export async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, { signal, headers: { Accept: 'application/json' } })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      msg = (await r.json()).error ?? msg
    } catch {
      /* not JSON */
    }
    throw new Error(msg)
  }
  return r.json()
}

export async function loadStatic(): Promise<void> {
  const [lines, stops, stations] = await Promise.all([
    getJson<Record<string, LineInfo>>('/api/static/lines.json'),
    getJson<Record<string, StopInfo>>('/api/static/stops.json'),
    getJson<Record<string, StationInfo>>('/api/static/stations.json'),
  ])
  app.lines = lines
  app.stops = stops
  app.stations = stations
}

export async function refreshLive(): Promise<void> {
  try {
    const live = await getJson<Live>('/api/live')
    app.skewMs = Date.parse(live.feed.now) - Date.now()
    app.live = live
    app.lastOk = Date.now()
    app.fetchError = null
  } catch (e) {
    app.fetchError = (e as Error).message
  }
}

export async function refreshLine(line: string): Promise<void> {
  try {
    const v = await getJson<LineView>(`/api/line/${encodeURIComponent(line)}`)
    // Ignore a response for a line the user has already left.
    if (app.wantLine === line) {
      app.lineView = v
      app.lineViewError = null
    }
  } catch (e) {
    if (app.wantLine === line) app.lineViewError = (e as Error).message
  }
}

export async function refreshStatus(): Promise<void> {
  try {
    app.status = await getJson<CityStatus>('/api/status')
  } catch {
    /* the panel shows the last data or a loading state */
  }
}

/** The planner query for the current from/to/time, or null while an end is missing. */
export function planQuery(from: string | null, to: string | null, at: string | null): string | null {
  if (!from || !to) return null
  const q = new URLSearchParams({ from, to })
  if (at) q.set('at', at)
  if (app.placeNames[from]) q.set('fromName', app.placeNames[from])
  if (app.placeNames[to]) q.set('toName', app.placeNames[to])
  return `/api/plan?${q}`
}

function planKinds(query: string): Record<string, string> {
  const q = new URLSearchParams(query.split('?')[1])
  const kind = (end: 'from' | 'to') =>
    !/^-?[\d.]+,-?[\d.]+$/.test(q.get(end) ?? '') ? 'stop' : q.get(`${end}Name`) === 'Moja poloha' ? 'my_location' : 'map_point'
  return { from: kind('from'), to: kind('to'), departure: q.has('at') ? 'later' : 'now' }
}

/** Fetch a plan into app.plan; the previous result stays on screen while the same query refreshes.
 * track: the open option's rides (rideSig), kept in the result after it left or lost a connection. */
export async function refreshPlan(query: string, track?: string | null): Promise<void> {
  const same = app.plan?.query === query
  app.plan = { query, data: same ? (app.plan?.data ?? null) : null, error: null, loading: true }
  try {
    const data = await getJson<Plan>(track ? `${query}&track=${encodeURIComponent(track)}` : query)
    if (app.plan?.query === query) app.plan = { query, data, error: null, loading: false }
    // Once per search, not per 30 s refresh. Only the kind of each end, never where it is.
    if (!same) trackEvent('route_planned', { ...planKinds(query), options: data.options.length })
  } catch (e) {
    if (app.plan?.query === query)
      app.plan = { query, data: same ? (app.plan?.data ?? null) : null, error: (e as Error).message, loading: false }
  }
}

/** Run fn now and every POLL_MS while the page is visible, and right away when it becomes visible. */
export function poll(fn: () => void, ms = POLL_MS): () => void {
  let timer: ReturnType<typeof setInterval> | undefined
  const start = () => {
    stop()
    fn()
    timer = setInterval(fn, ms)
  }
  const stop = () => timer && clearInterval(timer)
  const onVis = () => (document.hidden ? stop() : start())
  document.addEventListener('visibilitychange', onVis)
  if (!document.hidden) start()
  return () => {
    stop()
    document.removeEventListener('visibilitychange', onVis)
  }
}
