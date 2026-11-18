import { fold } from './format'
import { locale, t } from './i18n'
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
  if (POINT.test(v)) return isHere(v) ? t('Moja poloha', 'My location') : t('Bod na mape', 'Point on the map')
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
  hits.sort((a, b) => a.score - b.score || b.lines.length - a.lines.length || a.name.localeCompare(b.name, locale()))
  return hits.slice(0, limit)
}

// Points that are the user's location, known by value: placeLabel names them in the visitor's
// language, and a pinned route stores them as "here", never as coordinates.
const herePoints = new Set<string>()

/** Mark a point as the user's location; returns it. */
export function markHere(v: string): string {
  herePoints.add(v)
  return v
}

export const isHere = (v: string): boolean => herePoints.has(v)

/** Set one end of the open plan (a station code or a point), keeping the other end and the time;
 * in the reachability view, its starting point. */
export function setPlanEnd(end: 'from' | 'to', value: string): void {
  const v = app.view
  if (v.kind === 'plan') navigate({ ...v, [end]: value, opt: null }, { replace: true })
  else if (v.kind === 'reach' && end === 'from') navigate({ ...v, from: value }, { replace: true })
}

/** The option's rides as "trip~from~to,…": identifies it across refreshes, and the planner's track parameter. */
export function rideSig(o: PlanOption | undefined): string | null {
  const rides = o?.legs.flatMap((l) => (l.kind === 'ride' ? [`${l.trip}~${l.from.stop}~${l.to.stop}`] : [])) ?? []
  return rides.length ? rides.join(',') : null
}
