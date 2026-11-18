import { contours } from 'd3-contour'
import type { Reach } from './types'

/** Time limits on offer (minutes), and the bands each is shaded in. */
export const REACH_LIMITS = [30, 45, 60] as const
export function reachBands(limitMin: number): number[] {
  return limitMin === 30 ? [10, 20, 30] : [15, 30, 45, 60].filter((b) => b <= limitMin)
}
/** Nearest band first. The bands are drawn nested, so the inner ones also get the outer ones' tint. */
export const REACH_COLORS = ['#3a2ea8', '#5b4fd6', '#8b7ff0', '#b3abf7']

/** Grids up to about this many cells: 50 m cells across the city, coarser for a wide hour. */
const MAX_CELLS = 250_000

export interface ReachShapes {
  /** One feature per band, widest first, plus the origin point. */
  features: GeoJSON.Feature[]
  /** Square kilometres reachable within each band. */
  areas: number[]
  bounds: [[number, number], [number, number]] | null
}

/** Shade where one can be within each band: on foot from the origin, or from any stop reached
 * before the band's end, as far as the rest of the band allows (and at most walk.maxM). Per band,
 * a grid of the distance to the nearest such walk's end, relative to its length, is contoured at 1:
 * the walks' discs merged, with round edges also where the longest walk caps them. */
export function reachShapes(r: Reach, bands: number[]): ReachShapes {
  // The panel and the map ask for the same shapes.
  const key = bands.join()
  if (last?.r === r && last.key === key) return last.shapes
  const shapes = compute(r, bands)
  last = { r, key, shapes }
  return shapes
}
let last: { r: Reach; key: string; shapes: ReachShapes } | null = null

function compute(r: Reach, bands: number[]): ReachShapes {
  const lat0 = r.origin.lat
  const mx = 111_320 * Math.cos((lat0 * Math.PI) / 180) // metres per degree of longitude
  const my = 110_574
  const v = r.walk.speed / r.walk.detour // crow-fly metres per second
  const walkM = (t: number, limit: number) => Math.min(r.walk.maxM, (limit - t) * v)
  const limit = bands.at(-1)! * 60
  const pts: [number, number, number][] = [] // x, y, seconds
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity]
  for (const [lon, lat, t] of [[r.origin.lon, r.origin.lat, 0] as const, ...r.stops]) {
    if (t >= limit) continue
    const [x, y, m] = [lon * mx, lat * my, walkM(t, limit)]
    pts.push([x, y, t])
    x0 = Math.min(x0, x - m)
    y0 = Math.min(y0, y - m)
    x1 = Math.max(x1, x + m)
    y1 = Math.max(y1, y + m)
  }
  const bounds: ReachShapes['bounds'] = [[x0 / mx, y0 / my], [x1 / mx, y1 / my]]
  const cell = Math.max(50, Math.sqrt(((x1 - x0) * (y1 - y0)) / MAX_CELLS))
  // Two border cells on every side keep the shapes closed.
  x0 -= 2 * cell
  y1 += 2 * cell
  const w = Math.ceil((x1 - x0) / cell) + 3
  const h = Math.ceil((y1 - y0) / cell) + 3
  const gen = contours().size([w, h]).smooth(true)
  // Row 0 is the north edge; d3-contour puts sample i at i + 0.5.
  const toLonLat = ([gx, gy]: number[]) => [(x0 + (gx - 0.5) * cell) / mx, (y1 - (gy - 0.5) * cell) / my]
  const grid = new Float64Array(w * h)
  const features: GeoJSON.Feature[] = []
  const areas: number[] = []
  for (let b = bands.length - 1; b >= 0; b--) {
    grid.fill(2) // nobody walks here
    for (const [x, y, t] of pts) {
      const m = walkM(t, bands[b] * 60)
      if (m <= 0) continue
      const reach = m + 2 * cell
      const ci0 = Math.max(0, Math.floor((x - reach - x0) / cell))
      const ci1 = Math.min(w - 1, Math.ceil((x + reach - x0) / cell))
      const cj0 = Math.max(0, Math.floor((y1 - y - reach) / cell))
      const cj1 = Math.min(h - 1, Math.ceil((y1 - y + reach) / cell))
      for (let j = cj0; j <= cj1; j++) {
        const dy = y1 - j * cell - y
        for (let i = ci0; i <= ci1; i++) {
          const dx = x0 + i * cell - x
          const f = Math.sqrt(dx * dx + dy * dy) / m
          const k = j * w + i
          if (f < grid[k]) grid[k] = f
        }
      }
    }
    let n = 0
    for (const f of grid) if (f <= 1) n++
    areas[b] = (n * cell * cell) / 1e6
    // Contours enclose values at or above a threshold: negated, they enclose the walks.
    const mp = gen.contour(grid.map((f) => -f) as unknown as number[], -1)
    features.push({
      type: 'Feature',
      geometry: { type: 'MultiPolygon', coordinates: mp.coordinates.map((poly) => poly.map((ring) => ring.map(toLonLat))) },
      properties: { band: bands[b], color: REACH_COLORS[b] },
    })
  }
  features.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [r.origin.lon, r.origin.lat] }, properties: { origin: true } })
  return { features, areas, bounds }
}
