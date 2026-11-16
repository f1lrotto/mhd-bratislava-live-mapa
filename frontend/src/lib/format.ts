import type { VehicleType } from './types'

// Delay bands: 0 on time, 1 = 1–3 min, 2 = 3–10 min, 3 = 10+ min, null = no data.
export const BAND_COLORS = ['#1a9850', '#e6a700', '#ef6c28', '#d7263d'] as const
export const NO_DATA_COLOR = '#7d8592'
export const STALE_COLOR = '#b4bac3'

export function bandColor(band: number | null | undefined): string {
  return band == null ? NO_DATA_COLOR : BAND_COLORS[band]
}

export const BAND_LABELS = ['načas', '1–3 min', '3–10 min', '10+ min', 'bez údajov']

export function delayBand(delay: number | null): number | null {
  if (delay == null) return null
  if (delay < 60) return 0
  if (delay < 180) return 1
  if (delay < 600) return 2
  return 3
}

export function delayText(delay: number | null, capped = false): string {
  if (delay == null) return 'bez údajov'
  if (capped || delay >= 900) return '15+ min'
  if (delay < 60) return 'načas'
  return `${Math.floor(delay / 60)} min`
}

export function minutes(s: number | null | undefined): string {
  if (s == null) return '–'
  return `${Math.max(1, Math.round(s / 60))} min`
}

export function agoText(s: number | null | undefined): string {
  if (s == null) return '–'
  if (s < 60) return `pred ${Math.max(0, Math.round(s))} s`
  if (s < 3600) return `pred ${Math.floor(s / 60)} min`
  return `pred ${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`
}

export const TYPE_LABELS: Record<VehicleType, string> = {
  tram: 'električka',
  trolleybus: 'trolejbus',
  bus: 'autobus',
  other: 'vozidlo',
}

export const TYPE_PLURAL: Record<VehicleType, string> = {
  tram: 'Električky',
  trolleybus: 'Trolejbusy',
  bus: 'Autobusy',
  other: 'Ostatné',
}

/** Slovak plural for counts: 1 vozidlo, 2–4 vozidlá, 5+ vozidiel. */
export function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return `${n} ${one}`
  if (n >= 2 && n <= 4) return `${n} ${few}`
  return `${n} ${many}`
}

export function isNight(line: string): boolean {
  return /^N\d/.test(line)
}

export function lineSortKey(line: string): [number, number, string] {
  if (/^\d+$/.test(line)) return [0, +line, line]
  if (isNight(line)) return [1, +line.slice(1), line]
  return [2, 0, line]
}

export function compareLines(a: string, b: string): number {
  const x = lineSortKey(a)
  const y = lineSortKey(b)
  return x[0] - y[0] || x[1] - y[1] || x[2].localeCompare(y[2])
}
