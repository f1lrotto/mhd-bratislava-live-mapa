import type { Map as MlMap } from 'maplibre-gl'
import { BAND_COLORS, NO_DATA_COLOR, STALE_COLOR } from './format'

// Marker images, drawn once on canvases at device resolution:
//   body-<type>-<colour key>   shape by vehicle type, fill by delay band, the line number is a text layer
//   arrow-<colour key>         a pointer just outside the body, rotated to the heading
// Colour keys: 0..3 delay bands, n = no data, s = stale.

const RATIO = Math.min(3, Math.max(2, Math.ceil(globalThis.devicePixelRatio || 1)))
const BODY = 32
const ARROW = 50

export const COLOR_KEYS = ['0', '1', '2', '3', 'n', 's'] as const
const COLORS: Record<string, string> = {
  '0': BAND_COLORS[0],
  '1': BAND_COLORS[1],
  '2': BAND_COLORS[2],
  '3': BAND_COLORS[3],
  n: NO_DATA_COLOR,
  s: STALE_COLOR,
}

function canvas(size: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement('canvas')
  c.width = c.height = size * RATIO
  const ctx = c.getContext('2d')!
  ctx.scale(RATIO, RATIO)
  return [c, ctx]
}

function shapePath(ctx: CanvasRenderingContext2D, type: string): void {
  const c = BODY / 2
  ctx.beginPath()
  if (type === 'tram') {
    // Octagon: the clipped corners read as "tram" next to round buses and square trolleybuses.
    const r = 14.5
    const k = 5.5
    ctx.moveTo(c - r + k, c - r)
    ctx.lineTo(c + r - k, c - r)
    ctx.lineTo(c + r, c - r + k)
    ctx.lineTo(c + r, c + r - k)
    ctx.lineTo(c + r - k, c + r)
    ctx.lineTo(c - r + k, c + r)
    ctx.lineTo(c - r, c + r - k)
    ctx.lineTo(c - r, c - r + k)
    ctx.closePath()
  } else if (type === 'trolleybus') {
    ctx.roundRect(c - 13.5, c - 13.5, 27, 27, 6)
  } else {
    ctx.arc(c, c, 14.5, 0, Math.PI * 2)
  }
}

function body(type: string, color: string): ImageData {
  const [, ctx] = canvas(BODY)
  shapePath(ctx, type)
  ctx.fillStyle = color
  ctx.fill()
  ctx.lineWidth = 2
  ctx.strokeStyle = '#ffffff'
  ctx.stroke()
  return ctx.getImageData(0, 0, BODY * RATIO, BODY * RATIO)
}

function arrow(color: string): ImageData {
  const [, ctx] = canvas(ARROW)
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
    for (const type of ['bus', 'trolleybus', 'tram', 'other']) {
      map.addImage(`body-${type}-${key}`, body(type, COLORS[key]), { pixelRatio: RATIO })
    }
    map.addImage(`arrow-${key}`, arrow(COLORS[key]), { pixelRatio: RATIO })
  }
}

/** A small inline SVG of a marker shape, for the legend and lists. */
export function shapeSvg(type: string, color: string, size = 16): string {
  const s = size
  const shape =
    type === 'tram'
      ? `<polygon points="5,1 11,1 15,5 15,11 11,15 5,15 1,11 1,5" />`
      : type === 'trolleybus'
        ? `<rect x="1.5" y="1.5" width="13" height="13" rx="3.5" />`
        : `<circle cx="8" cy="8" r="7" />`
  return `<svg width="${s}" height="${s}" viewBox="0 0 16 16" fill="${color}" stroke="#fff" stroke-width="1.2" aria-hidden="true">${shape}</svg>`
}
