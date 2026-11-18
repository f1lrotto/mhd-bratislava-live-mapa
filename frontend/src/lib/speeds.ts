import { hm } from './format'
import { t } from './i18n'
import type { SpeedOverlay } from './state.svelte'
import type { PlanOption, SpeedData } from './types'

// The speed overlay's colours: a hop's actual time between two stops over its scheduled time.
// Up to 10 % slower counts as on schedule; timetables round to 15 s or a minute.
export const SPEED_STEPS = [1.1, 1.3, 1.6, 2] as const
export const SPEED_COLORS = ['#1a9850', '#e6b800', '#ef6c28', '#d7263d', '#7a1020'] as const
export const speedLabels = () => [t('načas', 'on time'), ...['+10', '+30', '+60'].map((p) => p + t(' %', '%')), '2×']

export function speedColor(r: number): string {
  const i = SPEED_STEPS.findIndex((s) => r < s)
  return SPEED_COLORS[i < 0 ? SPEED_COLORS.length - 1 : i]
}

/** "45 s", "2:05 min" */
export function duration(s: number): string {
  const t = Math.round(s)
  return t < 60 ? `${t} s` : `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')} min`
}

export const SLOTS = 48 // half hours of the time slider

export function slotTime(slot: number): string {
  return `${String(Math.floor(slot / 2)).padStart(2, '0')}:${slot % 2 ? '30' : '00'}`
}

export function timeSlot(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 2 + (m >= 30 ? 1 : 0)
}

/** The hops ("from>to") an option's rides run, in order. */
export function routeHops(o: PlanOption): string[] {
  return o.legs.flatMap((l) => (l.kind === 'ride' ? l.stops.slice(1).map((s, i) => `${l.stops[i].stop}>${s.stop}`) : []))
}

/** How much longer than scheduled the route's measured hops take, their actual over scheduled
 * time, and how many of its hops have data. */
export function routeExtra(hops: string[], data: SpeedData): { extraS: number; ratio: number; measured: number; total: number } {
  const by = new Map(data.hops.map((h) => [h.k, h]))
  let actual = 0
  let sched = 0
  let measured = 0
  for (const k of hops) {
    const h = by.get(k)
    if (!h) continue
    actual += h.a
    sched += h.s
    measured++
  }
  return { extraS: actual - sched, ratio: sched ? actual / sched : 1, measured, total: hops.length }
}

/** The overlay for an option: typical at the time its first ride leaves, or now when that is soon. */
export function routeOverlay(o: PlanOption, nowMs: number): SpeedOverlay {
  const start = o.legs.find((l) => l.kind === 'ride')?.start ?? o.depart
  return { view: 'typical', at: Math.abs(Date.parse(start) - nowMs) < 30 * 60_000 ? null : slotTime(timeSlot(hm(start))) }
}
