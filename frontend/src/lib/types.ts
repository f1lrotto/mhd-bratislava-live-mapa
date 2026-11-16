export type VehicleType = 'bus' | 'trolleybus' | 'tram' | 'other'

export interface Feed {
  now: string
  polledAt: string | null
  attemptedAt: string | null
  error: string | null
  down: boolean
}

export interface LiveVehicle {
  key: string
  line: string | null
  dest: string | null
  type: VehicleType
  lat: number
  lon: number
  az: number | null
  delay: number | null
  delayCapped: boolean
  band: 0 | 1 | 2 | 3 | null
  movedAgo: number | null
  stale: boolean
  dir: string | null
}

export interface Live {
  feed: Feed
  vehicles: LiveVehicle[]
}

export interface LineInfo {
  line: string
  type: VehicleType
  color: string
  textColor: string
  directions: Record<string, { headsign: string; from: string; stops: string[] }>
}

export interface StopInfo {
  name: string
  code: string
  platform: string | null
  lat: number
  lon: number
  lines: string[]
}

export interface Gap {
  m: number
  s: number | null
  flag: 'gap' | 'bunched' | null
}

export interface RibbonVehicle {
  key: string
  along: number
  offRoute: boolean
  delay: number | null
  stale: boolean
  dest: string | null
  type: VehicleType
  lastStop: number
  gapAhead?: Gap
}

export interface LineDirection {
  id: string
  headsign: string
  from: string
  length: number
  duration: number | null
  interval: number | null
  coords: [number, number][]
  /** Extra branch geometries that share this direction's ribbon (e.g. line 4 via Nové Mesto). */
  branches?: [number, number][][]
  stops: { id: string; name: string; dist: number; lat: number; lon: number }[]
  vehicles: RibbonVehicle[]
  summary: {
    count: number
    medianDelay: number | null
    gaps: number
    bunched: number
    biggestGap: { s: number; afterStop: string; fromStop?: string } | null
  }
}

export interface LineView {
  line: string
  type: VehicleType
  color: string
  textColor: string
  directions: LineDirection[]
  unmatched: { key: string; dest: string | null; reason: string }[]
  feed: Feed
}

export interface CityStatus {
  vehicles: number
  byType: Partial<Record<VehicleType, number>>
  withDelay: number
  shareLate: number | null
  worst: { line: string; medianDelay: number; vehicles: number; shareLate: number; type: VehicleType | null }[]
  feed: Feed
  history: { bucketS: number; today: Record<string, number>; baseline: Record<string, number> | null } | null
}
