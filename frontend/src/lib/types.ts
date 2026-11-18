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
  /** An IDS BK regional bus: its key is "idsbk:" + the trip's id, and it has no fleet number. */
  regional: boolean
  /** A regional bus's trip number (spoj č.), null for DPB vehicles. */
  tripNo: number | null
}

export type ServiceState = 'running' | 'layover' | 'depot' | 'parked' | 'unknown'

export interface Live {
  feed: Feed
  /** The IDS BK source of the regional buses. */
  regionalFeed: Feed
  vehicles: LiveVehicle[]
}

export interface LineInfo {
  line: string
  type: VehicleType
  color: string
  textColor: string
  directions: Record<string, { headsign: string; from: string; stops: string[] }>
  /** An IDS BK regional line (ids of its stops and stations start with "idsbk:"). */
  regional?: boolean
  operator?: string | null
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

/** A stop the vehicle has passed: when it did, if recorded live (null when we didn't see it pass). */
export type PassedStop = Omit<TripStop, 'predicted'> & { actual: string | null }

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
    passed: PassedStop[]
  }
  feed: Feed
}

export interface PlanPlace {
  /** Null for a map point or the user's location: placeLabel names it. */
  name: string | null
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
  /** Live: the vehicle's way from the stop behind it to the boarding stop (null once it passed it). */
  approach?: [number, number][] | null
  /** The change onto this ride from the one before it (null on the first ride). */
  transfer: Transfer | null
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
  /** The open option, kept (first) after it left or lost a connection. */
  tracked?: boolean
}

/** Seconds to spare at a change with current delays: "missed" below zero, "tight" when the ride
 * before it is late and little is left; for both, the earliest way on if the change fails. */
export interface Transfer {
  margin: number
  status: 'ok' | 'tight' | 'missed'
  fallback: FallbackOption | null
}

/** A fallback option: legs without their geometry and stop lists. */
export type FallbackOption = Omit<PlanOption, 'legs'> & {
  legs: (Omit<WalkLeg, 'coords'> | Omit<RideLeg, 'coords' | 'stops' | 'transfer' | 'approach'>)[]
}

export type PlanReason = 'same_place' | 'no_stops_near_origin' | 'no_stops_near_destination' | 'no_connection'

export interface Plan {
  live: boolean
  options: PlanOption[]
  reason?: PlanReason | null
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
  tripNo: number | null
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
  /** Shares of stop passes by bucket: `today` and `baseline` 5+ min late, `todayDelayed` 2+ min. */
  history: {
    bucketS: number
    today: Record<string, number>
    todayDelayed: Record<string, number>
    baseline: Record<string, number> | null
  } | null
}

/** /api/reach: the stops public transport gets to within `limit` seconds of leaving `origin` at
 * `depart`, each [lon, lat, seconds of its earliest arrival, stop id]. Walking on from them is at
 * `walk.speed` m/s along `walk.detour` × the crow-fly distance, at most `walk.maxM` crow-fly. */
export interface Reach {
  origin: { lat: number; lon: number; name: string | null; station: string | null }
  depart: string
  limit: number
  live: boolean
  walk: { speed: number; detour: number; maxM: number }
  stops: [number, number, number, string][]
}

/** Delay figures of a line or direction over the kept days: p50/p90 of all stop passes (s) and
 * the share of trips that were 5+ min late at some stop. */
export interface ReliabilitySummary {
  passes: number
  trips: number
  p50: number | null
  p90: number | null
  lateTrips: number | null
}

/** One direction's stops (rows) × hours of the service day (columns; 24+ is after midnight).
 * A cell is null with too few stop passes; `n` always has the count. */
export interface ReliabilityDirection {
  id: string
  headsign: string
  from: string
  stops: string[]
  hours: number[]
  median: (number | null)[][]
  p90: (number | null)[][]
  late: (number | null)[][]
  n: (number | null)[][]
  /** Median delay at each stop over all hours. */
  stopMedian: (number | null)[]
  summary: ReliabilitySummary
}

export interface LineReliability {
  line: string
  kind: 'workdays' | 'weekends'
  days: { count: number; from: string | null; to: string | null }
  summary: ReliabilitySummary
  directions: ReliabilityDirection[]
}

/** A hop between two consecutive stops ("from stop id>to stop id"), timed by the trips that ran it. */
export interface SpeedHop {
  k: string
  /** Runs measured. */
  n: number
  /** Mean actual and scheduled time between the stops, seconds. */
  a: number
  s: number
  /** Actual over scheduled time (above 1: slower than the timetable), damped for few runs. */
  r: number
}

export type SpeedData =
  | { view: 'live'; windowS: number; hops: SpeedHop[] }
  | { view: 'typical'; kind: 'workday' | 'saturday' | 'sunday'; days: number; from: string; to: string; hops: SpeedHop[] }

/** The overlay's map: each hop's length in metres and the lines that run it, and the road split
 * into segments, each with the hops (indices into `hops`) that run it. A street is one segment per
 * direction however many hops use it. */
export interface SpeedGeometry {
  hops: { k: string; m: number; lines: string[] }[]
  /** o: only regional hops run it, along a DPB street that already shows; left out of the network view. */
  segments: { c: [number, number][]; h: number[]; o?: boolean }[]
}
