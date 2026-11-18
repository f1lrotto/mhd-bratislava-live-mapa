import { getJson } from './api'
import { delayBand, isRegional } from './format'
import { app } from './state.svelte'
import type { LiveVehicle, VehicleType } from './types'

// Map replay: the fleet's logged positions (GET /api/replay/<t>, backend mhd/replay.py) in
// 10-minute chunks, interpolated between polls for any instant of the last 30 days.

export const SPEEDS = [1, 10, 60, 300] as const
const HOLD_S = 60 // a vehicle missing from the next polls stays where it was last seen this long
const LERP_MAX_S = 90 // samples further apart are a gap in the log, not a move to slide through
const TELEPORT_M = 1500 // as on the live map: longer jumps (depot moves, GPS resets) don't slide
const PREFETCH_S = 30 // while playing, the chunks of the next 30 s of playback are fetched ahead
const KEEP = 12 // chunks kept in memory (two hours); the browser cache keeps the rest
const LATEST_S = 60 // the newest instant to replay: the last poll is surely logged by then

interface RawTrack {
  key: string
  type: VehicleType
  t: number[]
  lat: number[]
  lon: number[]
  d: (number | null)[]
  az: (number | null)[]
  line: number[]
  dest: number[]
  run?: number[]
}
interface RawChunk {
  start: number
  end: number
  complete: boolean
  strings: string[]
  vehicles: RawTrack[]
}
interface Track {
  key: string
  type: VehicleType
  regional: boolean
  t: Float64Array // Unix seconds
  lat: Float64Array
  lon: Float64Array
  d: Float64Array // NaN: no delay reported
  az: Int16Array // -1: no heading
  line: Uint16Array
  dest: Uint16Array
  run: Uint8Array | null
}
interface Chunk {
  start: number
  complete: boolean
  strings: string[]
  tracks: Track[]
}

export interface ReplayRange {
  /** Unix times of the UTC hours with logged positions, oldest first. */
  hours: number[]
  chunkS: number
  rawDays: number
}

class ReplayState {
  range = $state.raw<ReplayRange | null>(null)
  error = $state.raw<string | null>(null)
  /** The replayed instant, Unix seconds. */
  t = $state.raw(0)
  playing = $state.raw(false)
  speed = $state.raw<number>(60)
  /** The vehicle tapped on the map. */
  sel = $state.raw<string | null>(null)
  /** Bumped when a chunk arrives, so what shows it redraws. */
  loaded = $state.raw(0)
}

export const replay = new ReplayState()

let chunkS = 600
const fetched = new Map<number, Promise<void>>()
const chunks = new Map<number, Chunk>()

const startOf = (t: number) => Math.floor(t / chunkS) * chunkS

/** The newest instant replay offers, in server time. */
export function latest(): number {
  return (Date.now() + app.skewMs) / 1000 - LATEST_S
}

export async function loadRange(): Promise<void> {
  try {
    const r = await getJson<ReplayRange>('/api/replay')
    chunkS = r.chunkS
    replay.range = r
    replay.error = null
  } catch (e) {
    replay.error = (e as Error).message
  }
}

function decode(c: RawChunk): Chunk {
  const tracks = c.vehicles.map((v): Track => {
    const n = v.t.length
    const tr: Track = {
      key: v.key,
      type: v.type,
      regional: isRegional(v.key),
      t: new Float64Array(n),
      lat: new Float64Array(n),
      lon: new Float64Array(n),
      d: new Float64Array(n),
      az: new Int16Array(n),
      line: Uint16Array.from(v.line),
      dest: Uint16Array.from(v.dest),
      run: v.run ? Uint8Array.from(v.run) : null,
    }
    let t = c.start, lat = 0, lon = 0
    for (let i = 0; i < n; i++) {
      t += v.t[i]
      lat += v.lat[i]
      lon += v.lon[i]
      tr.t[i] = t
      tr.lat[i] = lat / 1e5
      tr.lon[i] = lon / 1e5
      tr.d[i] = v.d[i] ?? NaN
      tr.az[i] = v.az[i] ?? -1
    }
    return tr
  })
  return { start: c.start, complete: c.complete, strings: c.strings, tracks }
}

/** Fetch the chunk starting at `start` unless it is here or on its way. */
function ensure(start: number): void {
  if (fetched.has(start) || start > latest()) return
  const p = getJson<RawChunk>(`/api/replay/${start}`)
    .then((raw) => {
      const c = decode(raw)
      chunks.set(start, c)
      // A chunk still being logged is fetched again the next time it is needed after 30 s.
      if (!c.complete) setTimeout(() => fetched.delete(start), 30_000)
      // Drop the chunks furthest from the replayed instant.
      if (chunks.size > KEEP) {
        const far = [...chunks.keys()].sort((a, b) => Math.abs(b - replay.t) - Math.abs(a - replay.t))
        for (const k of far.slice(0, chunks.size - KEEP)) {
          chunks.delete(k)
          fetched.delete(k)
        }
      }
      replay.error = null
      replay.loaded++
    })
    .catch((e) => {
      fetched.delete(start)
      replay.error = (e as Error).message
    })
  fetched.set(start, p)
}

/** The chunk of the replayed instant is here (false while it loads). */
export function ready(t = replay.t): boolean {
  return chunks.has(startOf(t))
}

function metres(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const k = Math.cos((lat1 * Math.PI) / 180)
  return Math.hypot((lon2 - lon1) * k * 111320, (lat2 - lat1) * 110574)
}

let last: LiveVehicle[] = []

/** The fleet at instant t, as live records: interpolated between the polls either side of it.
 * While t's chunk loads, the last frame. */
export function frame(t: number): LiveVehicle[] {
  const c = chunks.get(startOf(t))
  if (!c) {
    ensure(startOf(t))
    return last
  }
  const out: LiveVehicle[] = []
  for (const tr of c.tracks) {
    const n = tr.t.length
    if (!n || t < tr.t[0] || t > tr.t[n - 1] + HOLD_S) continue
    // The last sample at or before t.
    let lo = 0, hi = n - 1
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1
      if (tr.t[mid] <= t) lo = mid
      else hi = mid - 1
    }
    const i = lo
    let lat = tr.lat[i], lon = tr.lon[i]
    let az = tr.az[i] >= 0 ? tr.az[i] : null
    const j = i + 1 < n ? i + 1 : -1
    const gap = j >= 0 ? tr.t[j] - tr.t[i] : Infinity
    if (gap > LERP_MAX_S) {
      if (t - tr.t[i] > HOLD_S) continue
    } else {
      const m = metres(lat, lon, tr.lat[j], tr.lon[j])
      if (m < TELEPORT_M) {
        const f = (t - tr.t[i]) / gap
        lat += (tr.lat[j] - lat) * f
        lon += (tr.lon[j] - lon) * f
        // Headings the feed doesn't report come from the move, as on the live map.
        if (az == null && m > 10) {
          const k = Math.cos((lat * Math.PI) / 180)
          az = Math.round((Math.atan2((tr.lon[j] - tr.lon[i]) * k, tr.lat[j] - tr.lat[i]) * 180) / Math.PI + 360) % 360
        }
      }
    }
    const delay = Number.isNaN(tr.d[i]) ? null : tr.d[i]
    // Only running vehicles show a delay; without stop events in the log, every vehicle does.
    const running = tr.run == null || tr.run[i] === 1
    out.push({
      key: tr.key,
      line: c.strings[tr.line[i]] || null,
      dest: c.strings[tr.dest[i]] || null,
      type: tr.type,
      lat,
      lon,
      az,
      delay,
      delayCapped: !tr.regional && delay != null && delay >= 900,
      band: running ? (delayBand(delay) as LiveVehicle['band']) : null,
      movedAgo: null,
      stale: false,
      dir: null,
      service: running ? 'running' : 'unknown',
      trip: null,
      regional: tr.regional,
      tripNo: null,
    })
  }
  last = out
  return out
}

/** Move the replayed instant (clamped to what replay covers) and fetch what it needs. */
export function seek(t: number): void {
  const first = replay.range?.hours[0] ?? t
  replay.t = Math.max(first, Math.min(latest(), t))
  ensure(startOf(replay.t))
}

let raf = 0
let prev = 0

function step(now: number): void {
  // A frame's time can be a little before the click that started playing.
  const dt = Math.max(0, Math.min(0.25, (now - prev) / 1000))
  prev = now
  // Playback waits where it is until the chunk it moves into is here.
  const next = replay.t + dt * replay.speed
  if (next >= latest()) {
    seek(latest())
    return pause()
  }
  if (ready(next)) replay.t = next
  const ahead = Math.min(3, Math.ceil((replay.speed * PREFETCH_S) / chunkS))
  for (let k = 0; k <= ahead; k++) ensure(startOf(replay.t) + k * chunkS)
  raf = requestAnimationFrame(step)
}

export function play(): void {
  if (replay.playing) return
  if (replay.t >= latest() - 1) return
  replay.playing = true
  prev = performance.now()
  raf = requestAnimationFrame(step)
}

export function pause(): void {
  replay.playing = false
  cancelAnimationFrame(raf)
}
