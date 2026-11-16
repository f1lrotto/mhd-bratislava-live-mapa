<script lang="ts">
  import * as maplibregl from 'maplibre-gl'
  import type { GeoJSONSource, Map as MlMap, PointLike } from 'maplibre-gl'
  import 'maplibre-gl/dist/maplibre-gl.css'
  import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
  import { onMount, untrack } from 'svelte'
  import { passes } from './lib/filter'
  import { addMarkerImages } from './lib/markers'
  import { app, closePanel, feedDown, navigate } from './lib/state.svelte'
  import type { LineView, Live } from './lib/types'

  let { activeLine, selectedDir }: { activeLine: string | null; selectedDir: string | null } = $props()

  // The bundler moves MapLibre's worker; tell MapLibre where it ended up.
  maplibregl.setWorkerUrl(workerUrl)

  const STYLE = 'https://tiles.openfreemap.org/styles/positron'
  const ANIM_MS = 1500
  const TELEPORT_M = 1500

  let el: HTMLDivElement
  let map: MlMap | undefined
  let loaded = $state(false)

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
    const view = app.view
    const selKey = view.kind === 'vehicle' ? view.key : null
    const features = []
    for (const v of live.vehicles) {
      const sel = v.key === selKey
      if (!sel && !passes(v, app.filters)) continue
      const p = at(v.key, t) ?? [v.lon, v.lat]
      const dim = activeLine != null && v.line !== activeLine && !sel
      // On the active line, vehicles of the other directions stay visible but softer.
      const other = !dim && !sel && activeLine != null && selectedDir != null && v.dir != null && v.dir !== selectedDir
      const hi = activeLine != null && !dim
      features.push({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: p },
        properties: {
          key: v.key,
          line: v.line ?? '',
          type: v.type,
          c: down || v.stale || dim ? 's' : v.band == null ? 'n' : String(v.band),
          az: v.az ?? -1,
          dim,
          other,
          hi,
          sel,
          z: sel ? 3 : dim ? 0 : 1,
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
      padding: { top: 72 + pad, bottom: c.bottom + pad, left: c.left + pad, right: pad },
      maxZoom: 15,
      duration: 700,
    })
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
  // The active line's vehicles are 30% larger and always labelled.
  const VEH_SIZE = [
    'interpolate', ['linear'], ['zoom'],
    ...[[10, 0.42], [12, 0.66], [14, 0.88], [16, 1]].flatMap(([z, k]) => [z, ['case', ['get', 'hi'], Math.max(0.8, k * 1.3), k]]),
  ] as any
  const LONG = ['>=', ['length', ['get', 'line']], 3]
  const LABEL_SIZE = [
    'step', ['zoom'],
    ['case', ['get', 'hi'], ['case', LONG, 9.5, 11], 0],
    12, ['case', ['get', 'hi'], ['case', LONG, 10.5, 12.5], ['case', LONG, 9.5, 11.5]],
  ] as any

  function setup(m: MlMap): void {
    addMarkerImages(m)
    for (const id of ['stops', 'route', 'route-stops', 'vehicles']) m.addSource(id, { type: 'geojson', data: EMPTY })
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
    m.addLayer({
      id: 'stops',
      type: 'circle',
      source: 'stops',
      minzoom: 15,
      paint: {
        'circle-radius': 4,
        'circle-color': '#ffffff',
        'circle-stroke-color': '#6b7480',
        'circle-stroke-width': 1.5,
      },
    })
    m.addLayer({
      id: 'stops-label',
      type: 'symbol',
      source: 'stops',
      minzoom: 16,
      layout: {
        'text-field': ['get', 'name'],
        'text-font': ['Noto Sans Regular'],
        'text-size': 11,
        'text-anchor': 'top',
        'text-offset': [0, 0.7],
        'text-optional': true,
      },
      paint: { 'text-color': '#4a525c', 'text-halo-color': '#ffffff', 'text-halo-width': 1.5 },
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
      filter: ['all', ['>=', ['get', 'az'], 0], ['!', ['get', 'dim']]],
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
      paint: { 'text-color': '#ffffff', 'icon-opacity': dimmed(1, 0.28, 0.5), 'text-opacity': dimmed(1, 0, 0.6) },
    })

    const box = (p: { x: number; y: number }, r: number): [PointLike, PointLike] => [
      [p.x - r, p.y - r],
      [p.x + r, p.y + r],
    ]
    m.on('click', (e) => {
      const r = isMobile() ? 14 : 8
      const vs = m.queryRenderedFeatures(box(e.point, r), { layers: ['veh-body'] })
      const v = vs.find((f) => !f.properties.dim) ?? vs[0]
      if (v) return navigate({ kind: 'vehicle', key: String(v.properties.key) })
      const s = m.queryRenderedFeatures(box(e.point, r), { layers: ['route-stops', 'stops'] })[0]
      if (s) return navigate({ kind: 'stop', id: String(s.properties.id) })
      const rl = m.queryRenderedFeatures(box(e.point, r), { layers: ['route-line'] })[0]
      if (rl && app.view.kind === 'line') return navigate({ ...app.view, dir: String(rl.properties.dir) }, { replace: true })
      if (app.view.kind === 'vehicle' || app.view.kind === 'stop') closePanel()
    })
    for (const layer of ['veh-body', 'route-stops', 'stops', 'route-line']) {
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
      minZoom: 9,
      maxZoom: 18,
      maxBounds: [
        [16.6, 47.9],
        [17.65, 48.4],
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
        customAttribution: 'Cestovný poriadok © DPB, Hlavné mesto SR Bratislava (CC BY 4.0)',
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
    void [app.filters, app.view, activeLine, selectedDir, feedDown()]
    if (loaded) untrack(() => render(progress()))
  })

  $effect(() => {
    const stops = app.stops
    if (!loaded || !map) return
    ;(map.getSource('stops') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: Object.entries(stops).map(([id, s]) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
        properties: { id, name: s.platform ? `${s.name} (${s.platform})` : s.name },
      })),
    })
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
