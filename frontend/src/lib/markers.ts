import type { Map as MlMap } from 'maplibre-gl'
import { BAND_COLORS, NO_DATA_COLOR, STALE_COLOR } from './format'

// Marker images, drawn once on canvases at device resolution:
//   body-<type>-<colour key>   a silhouette by vehicle type, fill by delay band; the line number is a
//                              text layer. Tram: a long capsule. Trolleybus: a square with two poles.
//                              Bus: a circle. Type "regional" is an IDS BK bus: a dark circle with a
//                              ring in the delay colour.
//   arrow-<colour key>         a pointer just outside a bus body, rotated to the heading; arrowOffset
//                              pushes it out past the wider silhouettes
// Colour keys: 0..3 delay bands, n = no data, s = stale.

const RATIO = Math.min(3, Math.max(2, Math.ceil(globalThis.devicePixelRatio || 1)))
const ARROW = 50

export const COLOR_KEYS = ['0', '1', '2', '3', 'n', 's'] as const
const REGIONAL_FILL = '#1d232b'
const COLORS: Record<string, string> = {
  '0': BAND_COLORS[0],
  '1': BAND_COLORS[1],
  '2': BAND_COLORS[2],
  '3': BAND_COLORS[3],
  n: NO_DATA_COLOR,
  s: STALE_COLOR,
}

type Rect = [x: number, y: number, w: number, h: number, r: number]
type Shape = { w: number; h: number; body: Rect; poles?: [number, number][][] }

// Every body is a rounded rectangle around the marker's centre (a circle has r = w / 2), drawn on
// a w × h canvas centred on it.
const BUS: Shape = { w: 32, h: 32, body: [-14.5, -14.5, 29, 29, 14.5] }
const SHAPES: Record<string, Shape> = {
  tram: { w: 46, h: 32, body: [-21, -11, 42, 22, 11] },
  trolleybus: {
    w: 32,
    h: 46,
    body: [-13.5, -11.5, 27, 25, 6],
    poles: [
      [[-6, -11], [-10, -20]],
      [[3, -11], [-1, -20]],
    ],
  },
  bus: BUS,
  other: BUS,
  regional: { w: 32, h: 32, body: [-12.5, -12.5, 25, 25, 12.5] },
}
const shapeOf = (type: string) => SHAPES[type] ?? BUS

function rectPath([x, y, w, h, r]: Rect): string {
  return (
    `M${x + r} ${y}H${x + w - r}A${r} ${r} 0 0 1 ${x + w} ${y + r}V${y + h - r}` +
    `A${r} ${r} 0 0 1 ${x + w - r} ${y + h}H${x + r}A${r} ${r} 0 0 1 ${x} ${y + h - r}V${y + r}` +
    `A${r} ${r} 0 0 1 ${x + r} ${y}Z`
  )
}
const polesPath = (s: Shape) => (s.poles ?? []).map(([[x1, y1], [x2, y2]]) => `M${x1} ${y1}L${x2} ${y2}`).join('')

// How far a body reaches from its centre towards the heading, including its outline.
function reach(s: Shape, az: number): number {
  const a = (az * Math.PI) / 180
  const dot = ([x, y]: [number, number]) => x * Math.sin(a) - y * Math.cos(a)
  const [x, y, w, h, r] = s.body
  const corners: [number, number][] = [[x + r, y + r], [x + w - r, y + r], [x + w - r, y + h - r], [x + r, y + h - r]]
  const tips = (s.poles ?? []).map(([, tip]) => dot(tip) + 2)
  return Math.max(Math.max(...corners.map(dot)) + r + 1, ...tips)
}

/** Pixels to push the heading arrow out, beyond where it sits around a bus. */
export function arrowOffset(type: string, az: number): number {
  return Math.max(0, reach(shapeOf(type), az) - reach(BUS, az))
}

function canvas(w: number, h: number): CanvasRenderingContext2D {
  const c = document.createElement('canvas')
  c.width = w * RATIO
  c.height = h * RATIO
  const ctx = c.getContext('2d')!
  ctx.scale(RATIO, RATIO)
  return ctx
}

function body(type: string, color: string): ImageData {
  const s = shapeOf(type)
  const ctx = canvas(s.w, s.h)
  ctx.translate(s.w / 2, s.h / 2)
  const outline = new Path2D(rectPath(s.body))
  if (s.poles) {
    const poles = new Path2D(polesPath(s))
    ctx.lineCap = 'round'
    ctx.lineWidth = 4.5
    ctx.strokeStyle = '#ffffff'
    ctx.stroke(poles)
    ctx.lineWidth = 2
    ctx.strokeStyle = REGIONAL_FILL
    ctx.stroke(poles)
  }
  if (type === 'regional') {
    ctx.lineWidth = 6.5
    ctx.strokeStyle = '#ffffff'
    ctx.stroke(outline)
    ctx.fillStyle = REGIONAL_FILL
    ctx.fill(outline)
    ctx.lineWidth = 3.5
    ctx.strokeStyle = color
    ctx.stroke(outline)
  } else {
    ctx.fillStyle = color
    ctx.fill(outline)
    ctx.lineWidth = 2
    ctx.strokeStyle = '#ffffff'
    ctx.stroke(outline)
  }
  return ctx.getImageData(0, 0, s.w * RATIO, s.h * RATIO)
}

function arrow(color: string): ImageData {
  const ctx = canvas(ARROW, ARROW)
  const c = ARROW / 2
  ctx.beginPath()
  ctx.moveTo(c, 1.5)
  ctx.lineTo(c + 6.5, 11)
  ctx.lineTo(c - 6.5, 11)
  ctx.closePath()
  ctx.fillStyle = color
  ctx.fill()
  ctx.lineWidth = 1.5
  ctx.strokeStyle = '#ffffff'
  ctx.stroke()
  return ctx.getImageData(0, 0, ARROW * RATIO, ARROW * RATIO)
}

export function addMarkerImages(map: MlMap): void {
  for (const key of COLOR_KEYS) {
    for (const type of Object.keys(SHAPES)) {
      map.addImage(`body-${type}-${key}`, body(type, COLORS[key]), { pixelRatio: RATIO })
    }
    map.addImage(`arrow-${key}`, arrow(COLORS[key]), { pixelRatio: RATIO })
  }
}

/** A small inline SVG of a marker silhouette, for the legend and lists; size is a bus's width. */
export function shapeSvg(type: string, color: string, size = 16): string {
  const s = shapeOf(type)
  const k = size / BUS.w
  const d = rectPath(s.body)
  const shape =
    type === 'regional'
      ? `<path d="${d}" fill="${REGIONAL_FILL}" stroke="${color}" stroke-width="4" />`
      : `<path d="${d}" fill="${color}" stroke="#fff" stroke-width="2" />`
  const poles = s.poles
    ? `<path d="${polesPath(s)}" fill="none" stroke="${REGIONAL_FILL}" stroke-width="2.4" stroke-linecap="round" />`
    : ''
  return `<svg width="${s.w * k}" height="${s.h * k}" viewBox="${-s.w / 2} ${-s.h / 2} ${s.w} ${s.h}" aria-hidden="true">${poles}${shape}</svg>`
}

/** The planner's destination pin (anchor at the bottom tip) and the picked-point pin. */
export function addPinImages(map: MlMap): void {
  for (const [id, color] of [['pin-to', '#d7263d'], ['pin-pick', '#146eff']] as const) {
    const W = 30
    const H = 40
    const c = document.createElement('canvas')
    c.width = W * RATIO
    c.height = H * RATIO
    const ctx = c.getContext('2d')!
    ctx.scale(RATIO, RATIO)
    ctx.beginPath()
    ctx.moveTo(W / 2, H - 1.5)
    ctx.bezierCurveTo(W / 2 - 3, H - 12, 2, H - 20, 2, 14)
    ctx.arc(W / 2, 14, W / 2 - 2, Math.PI, 0)
    ctx.bezierCurveTo(W - 2, H - 20, W / 2 + 3, H - 12, W / 2, H - 1.5)
    ctx.closePath()
    ctx.fillStyle = color
    ctx.fill()
    ctx.lineWidth = 2
    ctx.strokeStyle = '#ffffff'
    ctx.stroke()
    ctx.beginPath()
    ctx.arc(W / 2, 14, 5, 0, Math.PI * 2)
    ctx.fillStyle = '#ffffff'
    ctx.fill()
    map.addImage(id, ctx.getImageData(0, 0, W * RATIO, H * RATIO), { pixelRatio: RATIO })
  }
}
