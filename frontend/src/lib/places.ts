import { fold } from './format'
import { app, navigate } from './state.svelte'
import type { PlanOption } from './types'

// A planner end is a station code ("93") or a point ("48.14520,17.10385", lat first as in the API).

const POINT = /^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/

export function pointValue(lat: number, lon: number): string {
  return `${lat.toFixed(5)},${lon.toFixed(5)}`
}

export function placeCoords(v: string | null): [number, number] | null {
  if (!v) return null
  const m = POINT.exec(v)
  if (m) return [+m[2], +m[1]]
  const st = app.stations[v]
  return st ? [st.lon, st.lat] : null
}

export function placeLabel(v: string | null): string {
  if (!v) return ''
  if (POINT.test(v)) return app.placeNames[v] ?? 'Bod na mape'
  return app.stations[v]?.name ?? v
}

/** Stations whose name matches the query: name prefix first, then word prefix, then anywhere. */
export function searchStations(query: string, limit = 8): { code: string; name: string; lines: string[] }[] {
  const q = fold(query.trim())
  if (!q) return []
  const hits: { code: string; name: string; lines: string[]; score: number }[] = []
  for (const [code, st] of Object.entries(app.stations)) {
    const n = fold(st.name)
    const i = n.indexOf(q)
    if (i < 0) continue
    const score = i === 0 ? 0 : /[\s,.\-/(]/.test(n[i - 1]) ? 1 : 2
    hits.push({ code, name: st.name, lines: st.lines, score })
  }
  hits.sort((a, b) => a.score - b.score || b.lines.length - a.lines.length || a.name.localeCompare(b.name, 'sk'))
  return hits.slice(0, limit)
}

/** Set one end of the open plan (a station code or a point), keeping the other end and the time. */
export function setPlanEnd(end: 'from' | 'to', value: string, name?: string): void {
  if (name) app.placeNames = { ...app.placeNames, [value]: name }
  const v = app.view
  if (v.kind !== 'plan') return
  navigate({ ...v, [end]: value, opt: null }, { replace: true })
}

/** First ride's trip: identifies an option across refreshes of the plan. */
export function firstTrip(o: PlanOption | undefined): string | null {
  return o?.legs.find((l) => l.kind === 'ride')?.trip ?? null
}
