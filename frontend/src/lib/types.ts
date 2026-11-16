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
  service: ServiceState
  trip: string | null
}

export type ServiceState = 'running' | 'layover' | 'depot' | 'parked' | 'unknown'

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
  station: string
}

export interface StationInfo {
  name: string
  lat: number
  lon: number
  stops: string[]
  lines: string[]
}

export interface Departure {
  line: string
  type: VehicleType
  color: string
  textColor: string
  headsign: string
  platform: string | null
  stopId: string
  scheduled: string
  predicted: string | null
  minutes: number
  live: boolean
  uncertain: boolean
  vehicle: string | null
  trip: string | null
}

export interface StationBoard {
  code: string
  name: string
  lat: number
  lon: number
  lines: string[]
  platforms: { stopId: string; platform: string | null; lat: number; lon: number; lines: string[] }[]
  departures: Departure[]
  feed: Feed
}

export interface TripStop {
  stopId: string
  index: number
  name: string | null
  station: string | null
  platform: string | null
  lat: number
  lon: number
  scheduled: string
  predicted: string | null
  arrival: boolean
}

export interface VehicleDetail {
  vehicle: LiveVehicle
  trip: null | {
    id: string
    line: string
    dir: string
    headsign: string
    start: string
    delay: number | null
    uncertain: boolean
    waiting: boolean
    stopCount: number
    stops: TripStop[]
  }
  feed: Feed
}

export interface PlanPlace {
  name: string
  lat: number
  lon: number
  stop: string | null
  station: string | null
  platform: string | null
}

export interface WalkLeg {
  kind: 'walk'
  from: PlanPlace
  to: PlanPlace
  start: string
  end: string
  m: number
  coords: [number, number][]
}

export interface RideLeg {
  kind: 'ride'
  line: string
  type: VehicleType
  color: string
  textColor: string
  dir: string
  headsign: string
  trip: string
  vehicle: string | null
  from: PlanPlace
  to: PlanPlace
  start: string
  end: string
  delay: number | null
  stops: { stop: string; name: string; lat: number; lon: number; time: string }[]
  coords: [number, number][]
}

export interface PlanOption {
  depart: string
  arrive: string
  duration: number
  transfers: number
  walkM: number
  legs: (WalkLeg | RideLeg)[]
}

export interface Plan {
  live: boolean
  options: PlanOption[]
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
