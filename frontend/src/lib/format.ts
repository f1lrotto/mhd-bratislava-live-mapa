import { prefs } from './prefs.svelte'
import { t } from './i18n'
import type { VehicleType } from './types'

// Delay bands: 0 on time (under 2 min), 1 = 2–5 min, 2 = 5–10 min, 3 = 10+ min, null = no data.
// Kept in step with derive.delay_band in the backend.
export const BAND_COLORS = ['#1a9850', '#e6a700', '#ef6c28', '#d7263d'] as const
export const NO_DATA_COLOR = '#7d8592'
export const STALE_COLOR = '#b4bac3'

export function bandColor(band: number | null | undefined): string {
  return band == null ? NO_DATA_COLOR : BAND_COLORS[band]
}

export const bandLabels = () => [t('načas', 'on time'), '2–5 min', '5–10 min', '10+ min', t('bez údajov', 'no data')]

export function delayBand(delay: number | null): number | null {
  if (delay == null) return null
  if (delay < 120) return 0
  if (delay < 300) return 1
  if (delay < 600) return 2
  return 3
}

/** regional: an IDS BK delay, which has no 15-minute cap. */
export function delayText(delay: number | null, capped = false, regional = false): string {
  if (delay == null) return t('bez údajov', 'no data')
  if (capped || (!regional && delay >= 900)) return '15+ min'
  if (delay < 60) return t('načas', 'on time')
  return `${Math.floor(delay / 60)} min`
}

export function minutes(s: number | null | undefined): string {
  if (s == null) return '–'
  return `${Math.max(1, Math.round(s / 60))} min`
}

export function agoText(s: number | null | undefined): string {
  if (s == null) return '–'
  const d = s < 60 ? `${Math.max(0, Math.round(s))} s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`
  return t(`pred ${d}`, `${d} ago`)
}

/** "12 %" in Slovak, "12%" in English. */
export function percent(share: number | null | undefined): string {
  return share == null ? '–' : `${Math.round(share * 100)}${t(' %', '%')}`
}

export function typeLabel(type: VehicleType): string {
  return { tram: t('električka', 'tram'), trolleybus: t('trolejbus', 'trolleybus'), bus: t('autobus', 'bus'), other: t('vozidlo', 'vehicle') }[type]
}

export function typePlural(type: VehicleType): string {
  return { tram: t('Električky', 'Trams'), trolleybus: t('Trolejbusy', 'Trolleybuses'), bus: t('Autobusy', 'Buses'), other: t('Ostatné', 'Other') }[type]
}

/** IDS BK's vehicle keys, stop ids and station codes; DPB's are fleet numbers and DPB's ids. */
export function isRegional(id: string): boolean {
  return id.startsWith('idsbk:')
}

/** How a vehicle is called: DPB's fleet number, or a regional bus's trip number (it has no fleet number). */
export function vehicleName(key: string, tripNo: number | null | undefined): string {
  if (!isRegional(key)) return t(`č. ${key}`, `no. ${key}`)
  return tripNo != null ? t(`spoj č. ${tripNo}`, `trip no. ${tripNo}`) : t('regionálny spoj', 'regional bus')
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

// --- times: the timetable is Bratislava time, whatever the phone's zone ----------------------------

export const TZ = 'Europe/Bratislava'
const HM = new Intl.DateTimeFormat('sk-SK', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false })
const DAY = {
  sk: new Intl.DateTimeFormat('sk-SK', { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'numeric' }),
  en: new Intl.DateTimeFormat('en-GB', { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'numeric' }),
}

/** "08:02" in Bratislava time, 24-hour in both languages. */
export function hm(iso: string | null | undefined): string {
  if (!iso) return '–'
  return HM.format(new Date(iso))
}

/** "ut 17. 11." / "Tue 17/11" in Bratislava time. */
export function dayText(iso: string): string {
  return DAY[prefs.lang].format(new Date(iso))
}

/** Bratislava's UTC offset in minutes at a given instant. */
function tzOffsetMin(ms: number): number {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone: TZ, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
      .formatToParts(new Date(ms))
      .map((x) => [x.type, x.value]),
  )
  const wall = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second)
  return Math.round((wall - Math.floor(ms / 1000) * 1000) / 60000)
}

/** An ISO instant as the value of a datetime-local input, in Bratislava wall time. */
export function toLocalInput(iso: string): string {
  const ms = Date.parse(iso)
  const d = new Date(ms + tzOffsetMin(ms) * 60000)
  return d.toISOString().slice(0, 16)
}

/** A datetime-local value (Bratislava wall time) as ISO with the offset, e.g. 2026-11-17T08:00:00+01:00. */
export function fromLocalInput(v: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(v)
  if (!m) return null
  const wall = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
  // The offset at the wall time read as UTC is right except within an hour of a DST switch.
  let off = tzOffsetMin(wall - tzOffsetMin(wall) * 60000)
  const sign = off < 0 ? '-' : '+'
  off = Math.abs(off)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:00${sign}${pad(Math.floor(off / 60))}:${pad(off % 60)}`
}

/** Minutes from now (server clock) until an ISO time, rounded down, never negative. */
export function minsUntil(iso: string, nowMs: number): number {
  return Math.max(0, Math.floor((Date.parse(iso) - nowMs) / 60000))
}

/** "12 min" / "1 h 05 min" for a duration in seconds. */
export function durationText(s: number): string {
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min`
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`
}

/** Slovak text search: case- and diacritics-insensitive ("hlavna" matches "Hlavná"). */
export function fold(s: string): string {
  return s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
}
