<script lang="ts">
  import * as maplibregl from 'maplibre-gl'
  import type { GeoJSONSource, Map as MlMap, PointLike } from 'maplibre-gl'
  import 'maplibre-gl/dist/maplibre-gl.css'
  import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
  import { onMount, untrack } from 'svelte'
  import { planQuery } from './lib/api'
  import { passes } from './lib/filter'
  import { addMarkerImages, addPinImages } from './lib/markers'
  import { placeCoords, placeLabel, pointValue, setPlanEnd } from './lib/places'
  import { app, closePanel, feedDown, navigate, regionalDown } from './lib/state.svelte'
  import type { LineView, Live, PlanOption } from './lib/types'

  let { activeLine, selectedDir }: { activeLine: string | null; selectedDir: string | null } = $props()

  // The bundler moves MapLibre's worker; tell MapLibre where it ended up.
  maplibregl.setWorkerUrl(workerUrl)

  const STYLE = 'https://tiles.openfreemap.org/styles/positron'
  const ANIM_MS = 1500
  const TELEPORT_M = 1500

  let el: HTMLDivElement
  let map: MlMap | undefined
  let loaded = $state(false)

  // The planner option drawn on the map: the selected one, or the first while the list shows.
  const planOpt = $derived.by((): PlanOption | null => {
    const v = app.view
    if (v.kind !== 'plan' || !app.plan || app.plan.query !== planQuery(v.from, v.to, v.at)) return null
    const opts = app.plan.data?.options ?? []
    return opts.length ? opts[Math.min(v.opt ?? 0, opts.length - 1)] : null
  })
  /** Live vehicles of the drawn option's rides; everything else dims. Null outside the planner. */
  const planKeys = $derived.by(() => {
    if (app.view.kind !== 'plan' || !planOpt) return null
    // Vehicle key -> its ride's order in the trip (the first ride's label wins where they meet).
    const keys = new Map<string, number>()
    planOpt.legs.forEach((l, i) => l.kind === 'ride' && l.vehicle && !keys.has(l.vehicle) && keys.set(l.vehicle, i))
    return keys
  })

  // --- marker animation ------------------------------------------------------------------------
  type LonLat = [number, number]
  const pos = new Map<string, { from: LonLat; to: LonLat }>()
  let animStart = 0
  let raf = 0

  const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2)
  const progress = () => Math.min(1, (performance.now() - animStart) / ANIM_MS)

  function at(key: string, t: number): LonLat | null {
    const p = pos.get(key)
    if (!p) return null
    const e = ease(t)
    return [p.from[0] + (p.to[0] - p.from[0]) * e, p.from[1] + (p.to[1] - p.from[1]) * e]
  }

  function metres(a: LonLat, b: LonLat): number {
    const k = Math.cos((a[1] * Math.PI) / 180)
    return Math.hypot((b[0] - a[0]) * k * 111320, (b[1] - a[1]) * 110574)
  }

  function onLive(live: Live): void {
    const t = progress()
    const seen = new Set<string>()
    for (const v of live.vehicles) {
      const to: LonLat = [v.lon, v.lat]
      const cur = at(v.key, t)
      // New vehicles and long jumps (depot moves, GPS resets) appear in place instead of sliding.
      const from = cur && metres(cur, to) < TELEPORT_M && !document.hidden ? cur : to
      pos.set(v.key, { from, to })
      seen.add(v.key)
    }
    for (const k of pos.keys()) if (!seen.has(k)) pos.delete(k)
    animStart = performance.now()
    cancelAnimationFrame(raf)
    const step = () => {
      const t = progress()
      render(t)
      if (t < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
  }

  function render(t: number): void {
    const src = map?.getSource('vehicles') as GeoJSONSource | undefined
    const live = app.live
    if (!src || !live) return
    const down = feedDown()
    const rDown = regionalDown()
    const view = app.view
    const selKey = view.kind === 'vehicle' ? view.key : null
    const features = []
    for (const v of live.vehicles) {
      const sel = v.key === selKey
      // The planned trip's vehicles: always shown, enlarged and tagged.
      const mine = planKeys?.has(v.key) ?? false
      if (!sel && !mine && !passes(v, app.filters)) continue
      const p = at(v.key, t) ?? [v.lon, v.lat]
      const dim = (activeLine != null && v.line !== activeLine && !sel) || (planKeys != null && !mine && !sel)
      // On the active line, vehicles of the other directions stay visible but softer.
      const other = !dim && !sel && activeLine != null && selectedDir != null && v.dir != null && v.dir !== selectedDir
      // Laying over, going to the depot, parked: grey, smaller and fainter than vehicles in service.
      const idle = v.service != null && v.service !== 'running' && !sel && !mine && !dim
      const hi = (activeLine != null && !dim && !other && !idle) || mine
      features.push({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: p },
        properties: {
          key: v.key,
          line: v.line ?? '',
          type: v.regional ? 'regional' : v.type,
          c: (v.regional ? rDown : down) || v.stale || dim || idle ? 's' : v.band == null ? 'n' : String(v.band),
          az: v.az ?? -1,
          dim,
          other,
          hi,
          sel,
          idle,
          mine,
          order: planKeys?.get(v.key) ?? 0,
          z: sel ? 3 : mine ? 2 : dim ? 0 : idle ? 0.5 : 1,
        },
      })
    }
    src.setData({ type: 'FeatureCollection', features })
  }

  // --- layout helpers ---------------------------------------------------------------------------
  const isMobile = () => innerWidth < 768

  /** Pixels of map covered by the panel, so things we centre on aren't hidden behind it. */
  function covered(): { left: number; bottom: number } {
    const panel = document.querySelector('.panel') as HTMLElement | null
    if (!panel) return { left: 0, bottom: 0 }
    const r = panel.getBoundingClientRect()
    return isMobile() ? { left: 0, bottom: Math.max(0, innerHeight - r.top) } : { left: r.right, bottom: 0 }
  }

  function centreOn(lon: number, lat: number, zoom?: number): void {
    if (!map) return
    const c = covered()
    map.easeTo({ center: [lon, lat], zoom, offset: [c.left / 2, -c.bottom / 2], duration: 700 })
  }

  function fitLine(lv: LineView): void {
    if (!map) return
    const b = new maplibregl.LngLatBounds()
    for (const d of lv.directions) for (const cs of [d.coords, ...(d.branches ?? [])]) for (const c of cs) b.extend(c)
    if (b.isEmpty()) return
    const c = covered()
    const pad = isMobile() ? 24 : 48
    map.fitBounds(b, {
      // The right side clears the zoom and location buttons.
      padding: { top: 72 + pad, bottom: c.bottom + pad, left: c.left + pad, right: 56 + pad },
      maxZoom: 15,
      duration: 700,
    })
  }

  function fitCoords(coords: [number, number][]): void {
    if (!map || !coords.length) return
    const b = new maplibregl.LngLatBounds()
    for (const c of coords) b.extend(c)
    const c = covered()
    const pad = isMobile() ? 36 : 56
    map.fitBounds(b, {
      padding: { top: 72 + pad, bottom: c.bottom + pad, left: c.left + pad, right: 56 + pad },
      maxZoom: 16,
      duration: 700,
    })
  }

  // --- planner overlay --------------------------------------------------------------------------
  function updatePlan(): void {
    if (!map) return
    const v = app.view
    const lines = []
    const stops = []
    const ends = []
    if (v.kind === 'plan') {
      const o = planOpt
      let rides = 0
      for (const [i, l] of (o?.legs ?? []).entries()) {
        lines.push({
          type: 'Feature' as const,
          geometry: { type: 'LineString' as const, coordinates: l.coords },
          properties: { kind: l.kind, color: l.kind === 'ride' ? l.color : '#5b6470' },
        })
        if (l.kind !== 'ride') continue
        const last = i === o!.legs.length - 1
        const pt = (lon: number, lat: number, role: string, name: string, id: string | null) => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [lon, lat] },
          properties: { role, name, color: l.color, id: id ?? '' },
        })
        for (const st of l.stops.slice(1, -1)) stops.push(pt(st.lon, st.lat, 'mid', st.name, st.stop))
        const boardName = l.from.platform ? `${l.from.name} (${l.from.platform})` : l.from.name
        stops.push(pt(l.from.lon, l.from.lat, rides ? 'transfer' : 'board', boardName, l.from.stop))
        // Where a ride ends: a ring, unless the next ride starts there (its transfer ring) or it is
        // the end of the trip (the destination pin).
        if (!last && o!.legs[i + 1]?.kind !== 'ride') stops.push(pt(l.to.lon, l.to.lat, 'alight', l.to.name, l.to.stop))
        rides++
      }
      for (const [role, val] of [['from', v.from], ['to', v.to]] as const) {
        // Before the first result, the destination is where the user put it; after, where the trip ends.
        const end = role === 'from' ? o?.legs[0]?.from : o?.legs.at(-1)?.to
        const c = end ? [end.lon, end.lat] : placeCoords(val)
        if (c) ends.push({ type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: c }, properties: { role, name: placeLabel(val) } })
      }
    }
    ;(map.getSource('plan') as GeoJSONSource).setData({ type: 'FeatureCollection', features: lines })
    ;(map.getSource('plan-stops') as GeoJSONSource).setData({ type: 'FeatureCollection', features: stops })
    ;(map.getSource('plan-ends') as GeoJSONSource).setData({ type: 'FeatureCollection', features: ends })
  }

  /** The rest of a vehicle's way to the boarding stop: the approach cut where the vehicle is now. */
  function ahead(line: LonLat[], v: LonLat): LonLat[] | null {
    const k = Math.cos((v[1] * Math.PI) / 180)
    let best = { d: Infinity, i: 0, t: 0, p: line[0] }
    for (let i = 0; i < line.length - 1; i++) {
      const [a, b] = [line[i], line[i + 1]]
      const dx = (b[0] - a[0]) * k, dy = b[1] - a[1]
      const len = dx * dx + dy * dy
      const t = len ? Math.max(0, Math.min(1, (((v[0] - a[0]) * k) * dx + (v[1] - a[1]) * dy) / len)) : 0
      const p: LonLat = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
      const d = metres(p, v)
      if (d < best.d) best = { d, i, t, p }
    }
    // Off its way (e.g. still at the depot or on its previous trip): no line rather than a wrong one.
    if (best.d > 400) return null
    // Past the boarding stop (beyond the line's end): nothing left to come.
    if (best.i === line.length - 2 && best.t >= 1) return null
    const rest = [v, best.p, ...line.slice(best.i + 1)]
    return rest.length >= 2 && metres(rest[0], rest.at(-1)!) > 30 ? rest : null
  }

  function updateApproach(): void {
    if (!map) return
    const byKey = new Map((app.live?.vehicles ?? []).map((x) => [x.key, x]))
    const features = []
    for (const l of app.view.kind === 'plan' ? (planOpt?.legs ?? []) : []) {
      if (l.kind !== 'ride' || !l.vehicle || !l.approach) continue
      const v = byKey.get(l.vehicle)
      const rest = v && ahead(l.approach, [v.lon, v.lat])
      if (rest) features.push({ type: 'Feature' as const, geometry: { type: 'LineString' as const, coordinates: rest }, properties: { color: l.color } })
    }
    ;(map.getSource('plan-approach') as GeoJSONSource).setData({ type: 'FeatureCollection', features })
  }

  // --- route overlay ----------------------------------------------------------------------------
  function updateRoute(lv: LineView | null): void {
    if (!map) return
    const route = map.getSource('route') as GeoJSONSource
    const stops = map.getSource('route-stops') as GeoJSONSource
    if (!lv || lv.line !== activeLine) {
      route.setData({ type: 'FeatureCollection', features: [] })
      stops.setData({ type: 'FeatureCollection', features: [] })
      return
    }
    const sel = selectedDir ?? lv.directions[0]?.id
    route.setData({
      type: 'FeatureCollection',
      features: lv.directions.flatMap((d) =>
        [d.coords, ...(d.branches ?? [])].map((coords) => ({
          type: 'Feature' as const,
          geometry: { type: 'LineString' as const, coordinates: coords },
          properties: { dir: d.id, sel: d.id === sel, color: lv.color },
        })),
      ),
    })
    const d = lv.directions.find((x) => x.id === sel)
    stops.setData({
      type: 'FeatureCollection',
      features: (d?.stops ?? []).map((s) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
        properties: { id: s.id, name: s.name, color: lv.color },
      })),
    })
  }

  // --- setup ------------------------------------------------------------------------------------
  const EMPTY = { type: 'FeatureCollection' as const, features: [] }
  const ICON_SIZE = ['interpolate', ['linear'], ['zoom'], 10, 0.42, 12, 0.66, 14, 0.88, 16, 1] as any
  const dimmed = (on: number, off: number, other = on) =>
    ['case', ['get', 'dim'], off, ['get', 'other'], other, on] as any
  // The active line's (or planned trip's) vehicles are 30% larger and always labelled;
  // vehicles out of service are 30% smaller.
  const VEH_SIZE = [
    'interpolate', ['linear'], ['zoom'],
    ...[[10, 0.42], [12, 0.66], [14, 0.88], [16, 1]].flatMap(([z, k]) => [
      z,
      ['case', ['get', 'hi'], Math.max(0.8, k * 1.3), ['get', 'idle'], k * 0.7, k],
    ]),
  ] as any
  const LONG = ['>=', ['length', ['get', 'line']], 3]
  const LABEL_SIZE = [
    'step', ['zoom'],
    ['case', ['get', 'hi'], ['case', LONG, 9.5, 11], 0],
    12, ['case', ['get', 'hi'], ['case', LONG, 10.5, 12.5], ['get', 'idle'], ['case', LONG, 7, 8], ['case', LONG, 9.5, 11.5]],
  ] as any

  function setup(m: MlMap): void {
    addMarkerImages(m)
    addPinImages(m)
    for (const id of ['stations', 'stops', 'station-sel', 'route', 'route-stops', 'plan', 'plan-approach', 'plan-stops', 'plan-ends', 'vehicles'])
      m.addSource(id, { type: 'geojson', data: EMPTY })
    const firstLabel = m.getStyle().layers.find((l) => l.type === 'symbol')?.id

    m.addLayer(
      {
        id: 'route-casing',
        type: 'line',
        source: 'route',
        layout: { 'line-join': 'round', 'line-cap': 'round', 'line-sort-key': ['case', ['get', 'sel'], 1, 0] },
        paint: {
          'line-color': '#ffffff',
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 7, 15, 14],
          'line-opacity': ['case', ['get', 'sel'], 1, 0.6],
        },
      },
      firstLabel,
    )
    m.addLayer(
      {
        id: 'route-line',
        type: 'line',
        source: 'route',
        layout: { 'line-join': 'round', 'line-cap': 'round', 'line-sort-key': ['case', ['get', 'sel'], 1, 0] },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 4.5, 15, 9],
          'line-opacity': ['case', ['get', 'sel'], 1, 0.35],
        },
      },
      firstLabel,
    )
    // Where the user's vehicle still has to come from: faint and dashed, under the trip itself.
    m.addLayer(
      {
        id: 'plan-approach-casing',
        type: 'line',
        source: 'plan-approach',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': '#ffffff', 'line-opacity': 0.85, 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 6, 15, 10] },
      },
      firstLabel,
    )
    m.addLayer(
      {
        id: 'plan-approach',
        type: 'line',
        source: 'plan-approach',
        layout: { 'line-join': 'round', 'line-cap': 'butt' },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 3, 15, 5],
          'line-opacity': 0.7,
          'line-dasharray': [2, 1.5],
        },
      },
      firstLabel,
    )
    m.addLayer(
      {
        id: 'plan-walk',
        type: 'line',
        source: 'plan',
        filter: ['==', ['get', 'kind'], 'walk'],
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': '#5b6470',
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 3.5, 15, 6],
          'line-dasharray': [0.1, 1.8],
        },
      },
      firstLabel,
    )
    m.addLayer(
      {
        id: 'plan-casing',
        type: 'line',
        source: 'plan',
        filter: ['==', ['get', 'kind'], 'ride'],
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 8, 15, 15] },
      },
      firstLabel,
    )
    m.addLayer(
      {
        id: 'plan-ride',
        type: 'line',
        source: 'plan',
        filter: ['==', ['get', 'kind'], 'ride'],
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': ['get', 'color'], 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 5, 15, 10] },
      },
      firstLabel,
    )
    m.addLayer({
      id: 'route-arrows',
      type: 'symbol',
      source: 'route',
      filter: ['get', 'sel'],
      minzoom: 10,
      layout: {
        'symbol-placement': 'line',
        'symbol-spacing': 140,
        'text-field': '›',
        'text-font': ['Noto Sans Bold'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 10, 12, 16, 20],
        'text-keep-upright': false,
        'text-allow-overlap': true,
        'text-offset': [0, -0.1],
      },
      paint: { 'text-color': '#ffffff' },
    })
    // One marker per station from zoom 14; from 17 its platforms, each with its letter.
    m.addLayer({
      id: 'stations',
      type: 'circle',
      source: 'stations',
      minzoom: 14,
      maxzoom: 17,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 14, 4, 16, 6.5],
        'circle-color': '#ffffff',
        'circle-stroke-color': '#4a525c',
        'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 14, 1.5, 16, 2.5],
      },
    })
    m.addLayer({
      id: 'stops',
      type: 'circle',
      source: 'stops',
      minzoom: 17,
      paint: {
        'circle-radius': 8,
        'circle-color': '#ffffff',
        'circle-stroke-color': '#4a525c',
        'circle-stroke-width': 2,
      },
    })
    m.addLayer({
      id: 'stops-label',
      type: 'symbol',
      source: 'stops',
      minzoom: 17,
      layout: {
        'text-field': ['get', 'plat'],
        'text-font': ['Noto Sans Bold'],
        'text-size': 10,
        'text-allow-overlap': true,
        'text-ignore-placement': true,
      },
      paint: { 'text-color': '#1d232b' },
    })
    m.addLayer({
      id: 'stations-label',
      type: 'symbol',
      source: 'stations',
      minzoom: 15,
      layout: {
        'text-field': ['get', 'name'],
        'text-font': ['Noto Sans Regular'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 15, 11, 17, 12.5],
        'text-anchor': 'top',
        'text-offset': ['step', ['zoom'], ['literal', [0, 0.8]], 17, ['literal', [0, 1.6]]],
        'text-optional': true,
      },
      paint: { 'text-color': '#4a525c', 'text-halo-color': '#ffffff', 'text-halo-width': 1.5 },
    })
    // The open station, at any zoom.
    m.addLayer({
      id: 'station-sel',
      type: 'circle',
      source: 'station-sel',
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 6, 16, 11],
        'circle-color': '#ffffff',
        'circle-opacity': ['step', ['zoom'], 1, 17, 0],
        'circle-stroke-color': '#1d232b',
        'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 11, 3, 16, 5],
      },
    })
    m.addLayer({
      id: 'station-sel-label',
      type: 'symbol',
      source: 'station-sel',
      layout: {
        'text-field': ['get', 'name'],
        'text-font': ['Noto Sans Bold'],
        'text-size': 13,
        'text-anchor': 'top',
        'text-offset': [0, 1.3],
        'text-allow-overlap': true,
      },
      paint: { 'text-color': '#1d232b', 'text-halo-color': '#ffffff', 'text-halo-width': 2 },
    })
    m.addLayer({
      id: 'route-stops',
      type: 'circle',
      source: 'route-stops',
      minzoom: 11,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 2.5, 15, 5.5],
        'circle-color': '#ffffff',
        'circle-stroke-color': ['get', 'color'],
        'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 11, 1.5, 15, 2.5],
      },
    })
    m.addLayer({
      id: 'route-stops-label',
      type: 'symbol',
      source: 'route-stops',
      minzoom: 13.5,
      layout: {
        'text-field': ['get', 'name'],
        'text-font': ['Noto Sans Bold'],
        'text-size': 11.5,
        'text-anchor': 'left',
        'text-offset': [0.9, 0],
        'text-optional': true,
      },
      paint: { 'text-color': '#1d232b', 'text-halo-color': '#ffffff', 'text-halo-width': 2 },
    })
    // Dimmed vehicles sit under the planned trip's stops; the rest above them.
    m.addLayer({
      id: 'veh-body-dim',
      type: 'symbol',
      source: 'vehicles',
      filter: ['get', 'dim'],
      layout: {
        'icon-image': ['concat', 'body-', ['get', 'type'], '-', ['get', 'c']],
        'icon-size': VEH_SIZE,
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
      },
      paint: { 'icon-opacity': 0.28 },
    })
    m.addLayer({
      id: 'plan-stops',
      type: 'circle',
      source: 'plan-stops',
      layout: { 'circle-sort-key': ['match', ['get', 'role'], 'mid', 0, 1] },
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, ['match', ['get', 'role'], 'mid', 2.5, 7], 15, ['match', ['get', 'role'], 'mid', 4, 8.5]],
        'circle-color': ['match', ['get', 'role'], 'board', ['get', 'color'], '#ffffff'],
        'circle-stroke-color': ['match', ['get', 'role'], 'board', '#ffffff', 'mid', ['get', 'color'], '#1d232b'],
        'circle-stroke-width': ['match', ['get', 'role'], 'board', 3, 'mid', 2, 4],
      },
    })
    m.addLayer({
      id: 'plan-from',
      type: 'circle',
      source: 'plan-ends',
      filter: ['==', ['get', 'role'], 'from'],
      paint: { 'circle-radius': 7, 'circle-color': '#ffffff', 'circle-stroke-color': '#1d232b', 'circle-stroke-width': 4.5 },
    })
    m.addLayer({
      id: 'plan-label',
      type: 'symbol',
      source: 'plan-stops',
      filter: ['!=', ['get', 'role'], 'mid'],
      layout: {
        'text-field': ['get', 'name'],
        'text-font': ['Noto Sans Bold'],
        'text-size': 12,
        'text-anchor': 'left',
        'text-offset': [1.1, 0],
        'text-optional': true,
      },
      paint: { 'text-color': '#1d232b', 'text-halo-color': '#ffffff', 'text-halo-width': 2 },
    })
    m.addLayer({
      id: 'plan-to',
      type: 'symbol',
      source: 'plan-ends',
      filter: ['==', ['get', 'role'], 'to'],
      layout: {
        'icon-image': 'pin-to',
        'icon-anchor': 'bottom',
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
        'text-field': ['get', 'name'],
        'text-font': ['Noto Sans Bold'],
        'text-size': 12.5,
        'text-anchor': 'left',
        'text-offset': [1.1, -1.4],
        'text-optional': true,
      },
      paint: { 'text-color': '#a51428', 'text-halo-color': '#ffffff', 'text-halo-width': 2 },
    })
    m.addLayer({
      id: 'veh-sel',
      type: 'circle',
      source: 'vehicles',
      filter: ['get', 'sel'],
      paint: {
        'circle-radius': 24,
        'circle-color': 'rgba(20, 110, 255, 0.16)',
        'circle-stroke-color': '#146eff',
        'circle-stroke-width': 2.5,
      },
    })
    m.addLayer({
      id: 'veh-arrow',
      type: 'symbol',
      source: 'vehicles',
      filter: ['all', ['>=', ['get', 'az'], 0], ['!', ['get', 'dim']], ['!', ['get', 'idle']]],
      layout: {
        'icon-image': ['concat', 'arrow-', ['get', 'c']],
        'icon-rotate': ['get', 'az'],
        'icon-rotation-alignment': 'map',
        'icon-size': VEH_SIZE,
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
        'symbol-sort-key': ['get', 'z'],
      },
      paint: { 'icon-opacity': dimmed(1, 0, 0.45) },
    })
    m.addLayer({
      id: 'veh-body',
      type: 'symbol',
      source: 'vehicles',
      filter: ['!', ['get', 'dim']],
      layout: {
        'icon-image': ['concat', 'body-', ['get', 'type'], '-', ['get', 'c']],
        'icon-size': VEH_SIZE,
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
        'text-field': ['get', 'line'],
        'text-font': ['Noto Sans Bold'],
        'text-size': LABEL_SIZE,
        'text-allow-overlap': true,
        'text-ignore-placement': true,
        'symbol-sort-key': ['get', 'z'],
      },
      paint: {
        'text-color': '#ffffff',
        'icon-opacity': ['case', ['get', 'idle'], 0.7, dimmed(1, 0.28, 0.5)],
        'text-opacity': ['case', ['get', 'idle'], 0.9, dimmed(1, 0, 0.6)],
      },
    })
    m.addLayer({
      id: 'veh-tag',
      type: 'symbol',
      source: 'vehicles',
      filter: ['get', 'mine'],
      layout: {
        'text-field': 'Váš spoj',
        'text-font': ['Noto Sans Bold'],
        'text-size': 11.5,
        'text-anchor': 'bottom',
        'text-offset': [0, -1.6],
        // Each ride of the trip can have its vehicle tagged; when two are close (one waiting where
        // the other arrives) their identical labels stacked into a doubled "Tvoj spoj". Let the
        // tags collide with each other, the earlier ride first; the tags still don't push away
        // other map labels.
        'text-allow-overlap': false,
        'text-ignore-placement': true,
        'symbol-sort-key': ['get', 'order'],
      },
      paint: { 'text-color': '#0f6b37', 'text-halo-color': '#ffffff', 'text-halo-width': 2 },
    })

    const box = (p: { x: number; y: number }, r: number): [PointLike, PointLike] => [
      [p.x - r, p.y - r],
      [p.x + r, p.y + r],
    ]
    m.on('click', (e) => {
      const r = isMobile() ? 14 : 8
      if (app.pick) {
        // Picking a planner end: a tapped station counts as that station, anywhere else as a point.
        const end = app.pick
        app.pick = null
        const f = m.queryRenderedFeatures(box(e.point, r), { layers: ['stations', 'stops', 'station-sel'] })[0]
        const code = f && String(f.properties.station ?? f.properties.code ?? '')
        if (code && app.stations[code]) setPlanEnd(end, code)
        else setPlanEnd(end, pointValue(e.lngLat.lat, e.lngLat.lng), 'Bod na mape')
        return
      }
      const vs = m.queryRenderedFeatures(box(e.point, r), { layers: ['veh-body', 'veh-body-dim'] })
      const v = vs.find((f) => !f.properties.dim) ?? vs[0]
      if (v) return navigate({ kind: 'vehicle', key: String(v.properties.key) })
      const s = m.queryRenderedFeatures(box(e.point, r), { layers: ['plan-stops', 'route-stops', 'stops', 'stations', 'station-sel'] })[0]
      if (s) {
        const p = s.properties
        // Platforms (route, plan and platform markers carry a stop id) open their station with that platform.
        const stop = p.id ? String(p.id) : null
        const code = p.code ? String(p.code) : stop ? app.stops[stop]?.station : null
        if (code) return navigate({ kind: 'station', code, stop: p.code ? null : stop })
      }
      const rl = m.queryRenderedFeatures(box(e.point, r), { layers: ['route-line'] })[0]
      if (rl && app.view.kind === 'line') return navigate({ ...app.view, dir: String(rl.properties.dir) }, { replace: true })
      if (app.view.kind === 'vehicle' || app.view.kind === 'station') closePanel()
    })
    for (const layer of ['veh-body', 'veh-body-dim', 'route-stops', 'stops', 'stations', 'station-sel', 'plan-stops', 'route-line']) {
      m.on('mouseenter', layer, () => (m.getCanvas().style.cursor = 'pointer'))
      m.on('mouseleave', layer, () => (m.getCanvas().style.cursor = ''))
    }
  }

  onMount(() => {
    const m = new maplibregl.Map({
      container: el,
      style: STYLE,
      center: [17.115, 48.152],
      zoom: 12,
      // Zoom 8 fits the whole IDS BK area (idsbk.AREA) on a phone. The bounds reach 60–70 km past
      // it on every side, so any part of it can be panned clear of the panel.
      minZoom: 8,
      maxZoom: 18,
      maxBounds: [
        [15.9, 47.35],
        [18.6, 49.15],
      ],
      attributionControl: false,
      locale: {
        'NavigationControl.ZoomIn': 'Priblížiť',
        'NavigationControl.ZoomOut': 'Oddialiť',
        'GeolocateControl.FindMyLocation': 'Moja poloha',
        'GeolocateControl.LocationNotAvailable': 'Poloha nie je dostupná',
        'AttributionControl.ToggleAttribution': 'Zdroje dát',
        'AttributionControl.MapFeedback': 'Nahlásiť chybu mapy',
      },
      dragRotate: false,
      pitchWithRotate: false,
    })
    m.touchZoomRotate.disableRotation()
    m.keyboard.disableRotation()
    m.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution: ['Cestovný poriadok © DPB, Hlavné mesto SR Bratislava (CC BY 4.0)', 'Regionálne autobusy: IDS BK'],
      }),
      'bottom-right',
    )
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    m.addControl(
      new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true }, trackUserLocation: true }),
      'top-right',
    )
    m.on('load', () => {
      // The compact attribution starts open and covers the bottom of a phone screen.
      el.querySelector('.maplibregl-compact-show')?.classList.remove('maplibregl-compact-show')
      setup(m)
      loaded = true
    })
    map = m
    return () => {
      cancelAnimationFrame(raf)
      m.remove()
    }
  })

  // New positions: animate from where markers are now.
  $effect(() => {
    const live = app.live
    if (loaded && live) untrack(() => onLive(live))
  })

  // Filters, selection, the active line or feed state changed: redraw at the current frame.
  $effect(() => {
    void [app.filters, app.view, activeLine, selectedDir, planKeys, feedDown(), regionalDown()]
    if (loaded) untrack(() => render(progress()))
  })

  $effect(() => {
    const stops = app.stops
    const stations = app.stations
    if (!loaded || !map) return
    ;(map.getSource('stops') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: Object.entries(stops).map(([id, s]) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
        properties: { id, station: s.station, plat: s.platform ?? '' },
      })),
    })
    ;(map.getSource('stations') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: Object.entries(stations).map(([code, s]) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
        properties: { code, name: s.name },
      })),
    })
  })

  // The open station: highlighted, and centred once when it opens.
  let centredStation: string | null = null
  $effect(() => {
    const v = app.view
    const station = v.kind === 'station' ? app.stations[v.code] : null
    // With a platform picked, the ring marks the platform instead.
    const plat = v.kind === 'station' && v.stop ? app.stops[v.stop] : null
    const st = station && plat && plat.station === (v as { code: string }).code ? { ...plat, name: `${plat.name} ${plat.platform ?? ''}`.trim() } : station
    if (!loaded || !map) return
    const code = v.kind === 'station' ? v.code : null
    ;(map.getSource('station-sel') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: st ? [{ type: 'Feature', geometry: { type: 'Point', coordinates: [st.lon, st.lat] }, properties: { code, name: st.name } }] : [],
    })
    if (!st) {
      centredStation = null
      return
    }
    if (centredStation === code || !station) return
    centredStation = code
    untrack(() => requestAnimationFrame(() => centreOn(station.lon, station.lat, Math.max(map!.getZoom(), 16))))
  })

  // The planner: draw the option (or just the chosen ends), and fit the map when the option changes.
  let fittedPlan: string | null = null
  $effect(() => {
    const o = planOpt
    const v = app.view
    void [app.stations, app.plan]
    if (!loaded) return
    untrack(() => {
      updatePlan()
      if (v.kind !== 'plan') {
        fittedPlan = null
        return
      }
      if (!o) {
        // No connection found: still show both ends.
        const q = planQuery(v.from, v.to, v.at)
        const ends = [placeCoords(v.from), placeCoords(v.to)].filter((c) => c != null)
        if (app.plan?.query === q && app.plan.data && ends.length === 2 && fittedPlan !== `${q}#none`) {
          fittedPlan = `${q}#none`
          requestAnimationFrame(() => fitCoords(ends))
        }
        return
      }
      // A refresh that keeps the same trips keeps the view; another option or query refits.
      const key = `${planQuery(v.from, v.to, v.at)}#${v.opt ?? 0}#${o.legs.map((l) => (l.kind === 'ride' ? l.trip : 'w')).join()}`
      if (fittedPlan === key) return
      fittedPlan = key
      // The trip's live vehicles are in view too, e.g. one still on its way to the boarding stop.
      const mine = (app.live?.vehicles ?? []).filter((x) => planKeys?.has(x.key)).map((x): [number, number] => [x.lon, x.lat])
      requestAnimationFrame(() => fitCoords([...o.legs.flatMap((l) => l.coords), ...mine]))
    })
  })


  // The approach follows each live poll.
  $effect(() => {
    void [planOpt, app.live, app.view]
    if (loaded) untrack(updateApproach)
  })

  let fitted: string | null = null
  $effect(() => {
    const lv = app.lineView
    void selectedDir
    if (!loaded) return
    untrack(() => {
      updateRoute(lv)
      if (!lv || lv.line !== activeLine) return
      if (app.view.kind === 'line' && fitted !== lv.line) {
        fitted = lv.line
        // Wait a frame so the panel has its final size.
        requestAnimationFrame(() => fitLine(lv))
      }
    })
  })
  $effect(() => {
    if (app.view.kind !== 'line') untrack(() => (fitted = null))
  })

  // Opening a vehicle (from a tap, a ribbon row or a deep link) centres it once.
  let centred: string | null = null
  $effect(() => {
    const view = app.view
    const live = app.live
    if (!loaded) return
    if (view.kind !== 'vehicle') {
      centred = null
      return
    }
    if (centred === view.key) return
    const v = live?.vehicles.find((x) => x.key === view.key)
    if (!v || !map) return
    centred = view.key
    untrack(() => requestAnimationFrame(() => centreOn(v.lon, v.lat, Math.max(map!.getZoom(), 14.5))))
  })

  $effect(() => {
    const f = app.focus
    if (loaded && f) untrack(() => centreOn(f.lon, f.lat, f.zoom))
  })
</script>

<div class="map" bind:this={el} role="application" aria-label="Mapa vozidiel MHD"></div>

<style>
  .map {
    position: absolute;
    inset: 0;
  }
</style>
