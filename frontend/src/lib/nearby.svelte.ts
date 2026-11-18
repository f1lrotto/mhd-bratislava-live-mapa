import { track } from './analytics.svelte'
import { app, navigate } from './state.svelte'

// The user's position for "V okolí" (near me). It stays on this device: the nearby stations and the
// walk to them are worked out here, and the server only gets the codes of the stations whose
// departures are shown. Keep PrivacyPanel true to this.

/** Walking speed and detour, as the planner (backend/mhd/planner.py) assumes. */
const WALK_SPEED = 1.25 // m/s
export const DETOUR = 1.3 // walking metres per metre crow-fly

const NEAR_M = 500 // stations this close (crow-fly) are nearby…
const NEAR_MAX = 5 // …at most this many;
const FAR_M = 1500 // with fewer than FAR_COUNT that close, the nearest FAR_COUNT up to this far
const FAR_COUNT = 2
const MOVE_M = 40 // the nearby stations are picked again after moving this far

export interface Fix {
  lat: number
  lon: number
  /** Accuracy radius in metres. */
  acc: number
}

export interface NearStation {
  code: string
  name: string
  lat: number
  lon: number
  lines: string[]
  /** The station's platforms, where people actually walk to. */
  pts: { lat: number; lon: number }[]
}

export type GeoStatus = 'off' | 'waiting' | 'on' | 'denied' | 'unavailable' | 'unsupported'

type LatLon = { lat: number; lon: number }

export function crowM(a: LatLon, b: LatLon): number {
  const k = Math.cos((a.lat * Math.PI) / 180)
  return Math.hypot((b.lon - a.lon) * k * 111320, (b.lat - a.lat) * 110574)
}

/** Crow-fly metres to the closest of the points. */
export function nearestM(at: LatLon, pts: LatLon[]): number {
  return Math.min(...pts.map((p) => crowM(at, p)))
}

/** Seconds to walk a crow-fly distance. */
export function walkS(crow: number): number {
  return Math.ceil((crow * DETOUR) / WALK_SPEED)
}

function pickNearby(at: Fix | null): NearStation[] {
  if (!at) return []
  const all: (NearStation & { m: number })[] = []
  for (const [code, st] of Object.entries(app.stations)) {
    if (Math.abs(st.lat - at.lat) > 0.03 || Math.abs(st.lon - at.lon) > 0.045) continue // over ~3 km
    const pts = st.stops.flatMap((id) => (app.stops[id] ? [{ lat: app.stops[id].lat, lon: app.stops[id].lon }] : []))
    if (!pts.length) pts.push({ lat: st.lat, lon: st.lon })
    const m = nearestM(at, pts)
    if (m <= FAR_M) all.push({ code, name: st.name, lat: st.lat, lon: st.lon, lines: st.lines, pts, m })
  }
  all.sort((a, b) => a.m - b.m)
  const near = all.filter((s) => s.m <= NEAR_M).slice(0, NEAR_MAX)
  return (near.length >= FAR_COUNT ? near : all.slice(0, FAR_COUNT)).map(({ m: _, ...s }) => s)
}

class Here {
  status = $state.raw<GeoStatus>('off')
  pos = $state.raw<Fix | null>(null)
  /** Where the nearby stations were picked, so GPS jitter doesn't swap them (and refetch boards). */
  anchor = $state.raw<Fix | null>(null)
  /** Bumped by the locate button: the map fits you and the nearby stations again. */
  fitSeq = $state.raw(0)
  nearby = $derived(pickNearby(this.anchor))
}

export const here = new Here()

let watchId: number | null = null
let wanted = false

/** Start following the user's position (asks for permission the first time), and fit the map to
 * it once it is known. */
export function locate(): void {
  if (!('geolocation' in navigator)) {
    here.status = 'unsupported'
    return
  }
  wanted = true
  here.fitSeq++
  if (here.status === 'on') return
  here.status = 'waiting'
  stopWatch()
  startWatch()
}

/** The map's locate button: locate (in the tap, so iOS asks for permission) and open "V okolí". */
export function openNearby(): void {
  locate()
  if (app.view.kind !== 'nearby') {
    track('nearby_opened')
    navigate({ kind: 'nearby' })
  }
}

export function stopLocating(): void {
  wanted = false
  stopWatch()
  here.status = 'off'
  here.pos = null
  here.anchor = null
}

function startWatch(): void {
  if (watchId != null || document.hidden) return
  watchId = navigator.geolocation.watchPosition(
    (p) => {
      const fix = { lat: p.coords.latitude, lon: p.coords.longitude, acc: p.coords.accuracy }
      here.pos = fix
      here.status = 'on'
      if (!here.anchor || crowM(here.anchor, fix) > MOVE_M) here.anchor = fix
    },
    (e) => {
      if (e.code === e.PERMISSION_DENIED) {
        wanted = false
        stopWatch()
        here.status = 'denied'
      } else if (!here.pos) here.status = 'unavailable' // the watch goes on and may still get a fix
    },
    { enableHighAccuracy: true, maximumAge: 10_000 },
  )
}

function stopWatch(): void {
  if (watchId != null) navigator.geolocation.clearWatch(watchId)
  watchId = null
}

// No GPS while the app is in the background.
document.addEventListener('visibilitychange', () => {
  if (!wanted) return
  if (document.hidden) stopWatch()
  else startWatch()
})
