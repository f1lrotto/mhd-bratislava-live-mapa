import type { Filters } from './state.svelte'
import type { LiveVehicle } from './types'

export function passes(v: LiveVehicle, f: Filters): boolean {
  if (f.types.length && !f.types.includes(v.type)) return false
  if (f.lines.length && (!v.line || !f.lines.includes(v.line))) return false
  if (f.late && !(v.delay != null && v.delay >= 180)) return false
  return true
}
