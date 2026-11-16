import { app, POLL_MS } from './state.svelte'
import type { CityStatus, LineInfo, LineView, Live, StopInfo } from './types'

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
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
  const [lines, stops] = await Promise.all([
    getJson<Record<string, LineInfo>>('/api/static/lines.json'),
    getJson<Record<string, StopInfo>>('/api/static/stops.json'),
  ])
  app.lines = lines
  app.stops = stops
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
