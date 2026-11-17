import type { Filters } from './state.svelte'
import type { LiveVehicle } from './types'

/** Odstavené: parked off the route or standing still 10+ min (in a depot, too). Not a vehicle
 * laying over at a terminus or still on its way to the depot. */
const isParked = (v: LiveVehicle) => v.service === 'parked' || v.stale

export function passes(v: LiveVehicle, f: Filters): boolean {
  if (v.regional ? !f.regional : f.types.length && !f.types.includes(v.type)) return false
  if (f.lines.length && (!v.line || !f.lines.includes(v.line))) return false
  if (f.late && !(v.delay != null && v.delay >= 300)) return false
  if (!f.parked && isParked(v)) return false
  return true
}
