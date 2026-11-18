<script lang="ts">
  import * as maplibregl from 'maplibre-gl'
  import type { GeoJSONSource, Map as MlMap, PointLike, StyleSpecification } from 'maplibre-gl'
  import 'maplibre-gl/dist/maplibre-gl.css'
  import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
  import { onMount, untrack } from 'svelte'
  import { drawnPlanOption, planQuery, reachQuery } from './lib/api'
  import { t } from './lib/i18n'
  import { prefs } from './lib/prefs.svelte'
  import { passes } from './lib/filter'
  import { addMarkerImages, addPinImages, arrowOffset } from './lib/markers'
  import { here, openNearby } from './lib/nearby.svelte'
  import { unread } from './lib/news.svelte'
  import { placeCoords, placeLabel, pointValue, setPlanEnd } from './lib/places'
  import { REACH_COLORS, reachBands, reachShapes } from './lib/reach'
  import { frame, replay } from './lib/replay.svelte'
  import { routeHops, SPEED_COLORS, SPEED_STEPS } from './lib/speeds'
  import { app, closePanel, feedDown, navigate, regionalDown, setSpeed } from './lib/state.svelte'
  import { isDark } from './lib/theme.svelte'
  import type { LineView, Live, PlanOption } from './lib/types'

  let { activeLine, selectedDir }: { activeLine: string | null; selectedDir: string | null } = $props()

  // The bundler moves MapLibre's worker; tell MapLibre where it ended up.
  maplibregl.setWorkerUrl(workerUrl)

  // The base map by theme; both share OpenFreeMap's sources, sprite and fonts.
  const STYLE = { light: 'https://tiles.openfreemap.org/styles/positron', dark: 'https://tiles.openfreemap.org/styles/dark' }
  /** What of the app's layers follows the theme, layers read it with C(name): colours, and the
   * opacity of dimmed vehicles (their grey glares on the dark map). */
  const PALETTE = {
    light: { paper: '#ffffff', ink: '#1d232b', ink2: '#4a525c', walk: '#5b6470', reach: '#2a2180', to: '#a51428', mine: '#0f6b37', dim: 0.28 },
    dark: { paper: '#1b1f24', ink: '#e6e9ed', ink2: '#aab2bc', walk: '#9ba4af', reach: '#c4bdfa', to: '#ff8a96', mine: '#6fd59b', dim: 0.1 },
  }
  const C = (name: keyof typeof PALETTE.light) => ['global-state', name] as any
  const ANIM_MS = 1500
  const TELEPORT_M = 1500

  let el: HTMLDivElement
  let map: MlMap | undefined

  /** MapLibre's UI strings that the map's controls show, in the visitor's language. */
  function mapLocale(): Record<string, string> {
    return {
      'Map.Title': t('Mapa', 'Map'),
      'NavigationControl.ZoomIn': t('Priblížiť', 'Zoom in'),
      'NavigationControl.ZoomOut': t('Oddialiť', 'Zoom out'),
      'AttributionControl.ToggleAttribution': t('Zdroje dát', 'Data sources'),
      'AttributionControl.MapFeedback': t('Nahlásiť chybu mapy', 'Report a map error'),
    }
  }

  let controls: maplibregl.IControl[] = []
  /** Bumped when the controls are added again, so effects that style their buttons re-run. */
  let controlsSeq = $state(0)
  function addControls(m: MlMap): void {
    speedButton.title = speedButton.ariaLabel = t('Rýchlosť jazdy', 'Travel speed')
    newsButton.title = t('Čo je nové', "What's new")
    const attribution = new maplibregl.AttributionControl({
      compact: true,
      customAttribution: [
        t('Cestovný poriadok © DPB, Hlavné mesto SR Bratislava (CC BY 4.0)', 'Timetable © DPB, City of Bratislava (CC BY 4.0)'),
        t('Regionálne autobusy: IDS BK', 'Regional buses: IDS BK'),
      ],
    })
    const nav = new maplibregl.NavigationControl({ showCompass: false })
    m.addControl(attribution, 'bottom-right')
    // Bottom controls stack upwards: this one sits above the attribution.
    m.addControl(newsControl, 'bottom-right')
    m.addControl(nav, 'top-right')
    m.addControl(locateControl, 'top-right')
    m.addControl(speedControl, 'top-right')
    controls = [attribution, newsControl, nav, locateControl, speedControl]
    controlsSeq++
    // The compact attribution starts open and covers the bottom of a phone screen.
    const close = () => el.querySelector('.maplibregl-compact-show')?.classList.remove('maplibregl-compact-show')
    if (m.loaded()) requestAnimationFrame(close)
    else m.once('load', close)
  }
  let loaded = $state(false)

  // The planner option drawn on the map: the selected one, or the first while the list shows.
  const planOpt = $derived.by((): PlanOption | null => drawnPlanOption())
  /** With the speed overlay on in the planner, only the drawn option's hops are coloured. */
  const routeHopKeys = $derived(app.speed && planOpt ? routeHops(planOpt) : null)
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
    const view = app.view
    // In replay, the fleet at the replayed instant, already in place; the feed's state is today's.
    const rp = view.kind === 'replay'
    const vehicles = rp ? frame(replay.t) : app.live?.vehicles
    if (!src || !vehicles) return
    const down = !rp && feedDown()
    const rDown = !rp && regionalDown()
    const selKey = view.kind === 'vehicle' ? view.key : rp ? replay.sel : null
    const features = []
    for (const v of vehicles) {
      const sel = v.key === selKey
      // The planned trip's vehicles: always shown, enlarged and tagged.
      const mine = planKeys?.has(v.key) ?? false
      if (!sel && !mine && !passes(v, app.filters)) continue
      const p = (!rp && at(v.key, t)) || [v.lon, v.lat]
      // Over the reachability map, vehicles fade so its bands read.
      const dim = (activeLine != null && v.line !== activeLine && !sel) || (planKeys != null && !mine && !sel) || view.kind === 'reach'
      // On the active line, vehicles of the other directions stay visible but softer.
      const other = !dim && !sel && activeLine != null && selectedDir != null && v.dir != null && v.dir !== selectedDir
      // Laying over, going to the depot, parked: grey, smaller and fainter than vehicles in service.
      const idle = v.service != null && v.service !== 'running' && !sel && !mine && !dim
      const hi = (activeLine != null && !dim && !other && !idle) || mine
      const type = v.regional ? 'regional' : v.type
      features.push({
        type: 'Feature' as const,
        geometry: { type: 'Point' as const, coordinates: p },
        properties: {
          key: v.key,
          line: v.line ?? '',
          type,
          c: (v.regional ? rDown : down) || v.stale || dim || idle ? 's' : v.band == null ? 'n' : String(v.band),
          az: v.az ?? -1,
          ao: v.az == null ? 0 : arrowOffset(type, v.az),
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
    // The speed card (SpeedCard) sits under the top bar: the route goes below it.
    const card = document.querySelector('.speed-card')?.getBoundingClientRect().bottom ?? 0
    map.fitBounds(b, {
      padding: { top: Math.max(72, card) + pad, bottom: c.bottom + pad, left: c.left + pad, right: 56 + pad },
      maxZoom: 16,
      duration: 700,
    })
  }

  // --- near me ----------------------------------------------------------------------------------
  // The locate button opens the nearby board; MapLibre's GeolocateControl only drew a dot.
  const locateControl = {
    btn: null as HTMLButtonElement | null,
    onAdd() {
      const box = document.createElement('div')
      box.className = 'maplibregl-ctrl maplibregl-ctrl-group'
      const b = document.createElement('button')
      b.type = 'button'
      b.className = 'maplibregl-ctrl-geolocate'
      b.title = t('Moja poloha a odchody v okolí', 'My location and departures nearby')
      b.setAttribute('aria-label', b.title)
      b.innerHTML = '<span class="maplibregl-ctrl-icon" aria-hidden="true"></span>'
      b.addEventListener('click', openNearby)
      box.append(b)
      this.btn = b
      return box
    },
    onRemove() {
      this.btn?.parentElement?.remove()
      this.btn = null
    },
  }

  $effect(() => {
    void controlsSeq
    const b = locateControl.btn
    const s = here.status
    const open = app.view.kind === 'nearby'
    if (!loaded || !b) return
    b.classList.toggle('maplibregl-ctrl-geolocate-waiting', s === 'waiting')
    b.classList.toggle('maplibregl-ctrl-geolocate-active', s === 'on' && open)
    b.classList.toggle('maplibregl-ctrl-geolocate-background', s === 'on' && !open)
    b.classList.toggle('maplibregl-ctrl-geolocate-active-error', s === 'denied' || s === 'unavailable')
    b.setAttribute('aria-pressed', String(open))
  })

  /** A circle of r metres around a point, as a polygon ring. */
  function circle(lon: number, lat: number, r: number): LonLat[] {
    const k = Math.cos((lat * Math.PI) / 180)
    return Array.from({ length: 49 }, (_, i) => {
      const a = (i / 48) * 2 * Math.PI
      return [lon + (Math.cos(a) * r) / (111320 * k), lat + (Math.sin(a) * r) / 110574] as LonLat
    })
  }

  $effect(() => {
    const p = here.pos
    if (!loaded || !map) return
    ;(map.getSource('me') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: p
        ? [
            { type: 'Feature', geometry: { type: 'Polygon', coordinates: [circle(p.lon, p.lat, p.acc)] }, properties: {} },
            { type: 'Feature', geometry: { type: 'Point', coordinates: [p.lon, p.lat] }, properties: {} },
          ]
        : [],
    })
  })

  $effect(() => {
    const near = app.view.kind === 'nearby' ? here.nearby : []
    if (!loaded || !map) return
    ;(map.getSource('near') as GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: near.map((s) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] }, properties: { code: s.code, name: s.name } })),
    })
  })

  // Each tap of the locate button fits the map to you and the nearby stations, once you are located.
  let fittedSeq = 0
  $effect(() => {
    const seq = here.fitSeq
    const p = here.pos
    const near = here.nearby
    if (!loaded || !p || seq === fittedSeq || !Object.keys(app.stations).length) return
    fittedSeq = seq
    untrack(() =>
      requestAnimationFrame(() =>
        near.length ? fitCoords([[p.lon, p.lat], ...near.flatMap((s) => s.pts.map((q): LonLat => [q.lon, q.lat]))]) : centreOn(p.lon, p.lat, 15),
      ),
    )
  })

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
        // A ride starts and ends at stops, which always have names.
        const boardName = l.from.platform ? `${l.from.name} (${l.from.platform})` : l.from.name!
        stops.push(pt(l.from.lon, l.from.lat, rides ? 'transfer' : 'board', boardName, l.from.stop))
        // Where a ride ends: a ring, unless the next ride starts there (its transfer ring) or it is
        // the end of the trip (the destination pin).
        if (!last && o!.legs[i + 1]?.kind !== 'ride') stops.push(pt(l.to.lon, l.to.lat, 'alight', l.to.name!, l.to.stop))
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

  // --- speed overlay ----------------------------------------------------------------------------
  /** Each road segment coloured by the runs of the hops on it: their actual over scheduled time,
   * damped like a single hop's (speeds.PRIOR_S). On a planned route only the route's hops count,
   * and its segments without data are grey (r = -1); elsewhere those aren't drawn. A segment's `k`
   * is the hop a tap opens: the one with the most runs. */
  function updateSpeeds(): void {
    if (!map) return
    const g = app.speedGeometry
    const d = app.speed ? app.speedData : null
    const route = routeHopKeys ? new Set(routeHopKeys) : null
    const runs = new Map((d?.hops ?? []).map((h) => [h.k, h]))
    const network = []
    const onRoute = []
    const sel = []
    for (const seg of g && d ? g.segments : []) {
      if (seg.o && !route) continue
      const keys = seg.h.map((i) => g!.hops[i].k).filter((k) => !route || route.has(k))
      if (!keys.length) continue
      let act = 0
      let sch = 0
      let k = keys[0]
      let most = 0
      for (const key of keys) {
        const h = runs.get(key)
        if (!h) continue
        act += h.n * h.a
        sch += h.n * h.s
        if (h.n > most) [k, most] = [key, h.n]
      }
      const f = {
        type: 'Feature' as const,
        geometry: { type: 'LineString' as const, coordinates: seg.c },
        properties: { k, r: sch ? (act + 60) / (sch + 60) : -1, sel: app.speedHop != null && keys.includes(app.speedHop) },
      }
      if (route) onRoute.push(f)
      else if (sch) network.push(f)
      if (!route && f.properties.sel) sel.push(f)
    }
    ;(map.getSource('speeds') as GeoJSONSource).setData({ type: 'FeatureCollection', features: network })
    ;(map.getSource('speed-route') as GeoJSONSource).setData({ type: 'FeatureCollection', features: onRoute })
    ;(map.getSource('speed-sel') as GeoJSONSource).setData({ type: 'FeatureCollection', features: sel })
  }

  /** The map button that switches the speed overlay on and off. */
  const speedButton = document.createElement('button')
  speedButton.type = 'button'
  speedButton.className = 'speed-toggle'
  speedButton.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 17a8 8 0 1 1 15 0"/><path d="M12 15l3.5-5"/><circle cx="12" cy="15.5" r="1.3"/></svg>'
  // Typical is the default: it covers the whole network at any hour; the live view is one tap away.
  speedButton.onclick = () => setSpeed(app.speed ? null : { view: 'typical', at: null })
  const speedControl: maplibregl.IControl = {
    onAdd() {
      const div = document.createElement('div')
      div.className = 'maplibregl-ctrl maplibregl-ctrl-group'
      div.append(speedButton)
      return div
    },
    onRemove() {
      speedButton.parentElement?.remove()
    },
  }

  /** "Čo je nové" in the bottom-right corner, out of the way; a dot marks entries not seen yet. */
  const newsButton = document.createElement('button')
  newsButton.type = 'button'
  newsButton.className = 'news-toggle'
  newsButton.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/></svg>'
  newsButton.onclick = () => (app.view.kind === 'news' ? closePanel() : navigate({ kind: 'news' }))
  const newsControl: maplibregl.IControl = {
    onAdd() {
      const div = document.createElement('div')
      div.className = 'maplibregl-ctrl maplibregl-ctrl-group'
      div.append(newsButton)
      return div
    },
    onRemove() {
      newsButton.parentElement?.remove()
    },
  }

  // --- setup ------------------------------------------------------------------------------------
  const EMPTY = { type: 'FeatureCollection' as const, features: [] }
  const ICON_SIZE = ['interpolate', ['linear'], ['zoom'], 10, 0.42, 12, 0.66, 14, 0.88, 16, 1] as any
  const dimmed = (on: number, off: number | object, other = on) =>
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

  const SOURCES = ['reach', 'speeds', 'speed-sel', 'speed-route', 'stations', 'stops', 'station-sel', 'route', 'route-stops', 'plan', 'plan-approach', 'plan-stops', 'plan-ends', 'vehicles', 'me', 'near']

  /** The other theme's base map with the app's sources and layers carried over: those under the
   * base map's labels stay under them, the rest on top. */
  function keepOwn(prev: StyleSpecification | undefined, next: StyleSpecification): StyleSpecification {
    if (!prev) return next
    const own = prev.layers.filter((l) => 'source' in l && SOURCES.includes(l.source))
    const cut = prev.layers.findIndex((l) => l.type === 'symbol' && !own.includes(l))
    const under = own.filter((l) => cut >= 0 && prev.layers.indexOf(l) < cut)
    const layers = [...next.layers]
    const label = layers.findIndex((l) => l.type === 'symbol')
    layers.splice(label < 0 ? layers.length : label, 0, ...under)
    layers.push(...own.filter((l) => !under.includes(l)))
    const sources = { ...next.sources }
    for (const id of SOURCES) sources[id] = prev.sources[id]
    return { ...next, sources, layers }
  }

  function setup(m: MlMap): void {
    addMarkerImages(m)
    addPinImages(m)
    for (const id of SOURCES) m.addSource(id, { type: 'geojson', data: EMPTY })
    const firstLabel = m.getStyle().layers.find((l) => l.type === 'symbol')?.id

    // The reachability bands, nested widest first, so the nearer ones are darker.
    m.addLayer(
      {
        id: 'reach-fill',
        type: 'fill',
        source: 'reach',
        filter: ['has', 'band'],
        paint: { 'fill-color': ['get', 'color'], 'fill-opacity': 0.2 },
      },
      firstLabel,
    )
    m.addLayer(
      {
        id: 'reach-line',
        type: 'line',
        source: 'reach',
        filter: ['has', 'band'],
        layout: { 'line-join': 'round' },
        paint: { 'line-color': ['get', 'color'], 'line-width': 1.5, 'line-opacity': 0.8 },
      },
      firstLabel,
    )
    // Stations reached in time, by band; a tap plans the trip there. Each shows from its zoom
    // (minz, see reachStations): zoomed out only the stations most lines pass.
    m.addLayer(
      {
        id: 'reach-stops',
        type: 'circle',
        source: 'reach',
        filter: ['all', ['has', 'station'], ['<=', ['get', 'minz'], 9]],
        layout: { 'circle-sort-key': ['-', 0, ['get', 't']] },
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 3.5, 13, 5, 16, 8],
          'circle-color': ['get', 'color'],
          'circle-stroke-color': C('paper'),
          'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 10, 1.5, 14, 2],
        },
      },
      firstLabel,
    )
    m.addLayer({
      id: 'reach-stops-label',
      type: 'symbol',
      source: 'reach',
      filter: ['all', ['has', 'station'], ['<=', ['get', 'minz'], 9]],
      minzoom: 13,
      layout: {
        'text-field': ['get', 'label'],
        'text-font': ['Noto Sans Bold'],
        'text-size': 11,
        'text-anchor': 'left',
        'text-offset': [0.9, 0],
        'text-optional': true,
        'symbol-sort-key': ['get', 'rank'],
      },
      paint: { 'text-color': C('reach'), 'text-halo-color': C('paper'), 'text-halo-width': 1.5 },
    })
    const showReachStops = () => {
      const f = ['all', ['has', 'station'], ['<=', ['get', 'minz'], Math.floor(m.getZoom())]] as any
      m.setFilter('reach-stops', f)
      m.setFilter('reach-stops-label', f)
    }
    m.on('zoom', showReachStops)
    showReachStops()
    m.addLayer({
      id: 'reach-origin',
      type: 'circle',
      source: 'reach',
      filter: ['has', 'origin'],
      paint: { 'circle-radius': 7, 'circle-color': C('paper'), 'circle-stroke-color': '#3a2ea8', 'circle-stroke-width': 4.5 },
    })
    // The speed overlay, under routes and plans. Each direction of a street sits on its own side
    // (the right, as traffic drives), so both show; the slowest hop draws on top where they overlap.
    const SPEED_COLOR = ['step', ['get', 'r'], '#9aa1ab', 0, SPEED_COLORS[0], ...SPEED_STEPS.flatMap((t, i) => [t, SPEED_COLORS[i + 1]])] as any
    const SPEED_W = ['interpolate', ['linear'], ['zoom'], 10, 2, 13, 3.5, 16, 7] as any
    const SPEED_OFF = ['interpolate', ['linear'], ['zoom'], 10, 1.2, 13, 2.2, 16, 4] as any
    m.addLayer(
      {
        id: 'speed-sel',
        type: 'line',
        source: 'speed-sel',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': C('ink'),
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 6, 13, 8, 16, 12],
          'line-offset': SPEED_OFF,
        },
      },
      firstLabel,
    )
    m.addLayer(
      {
        id: 'speed-line',
        type: 'line',
        source: 'speeds',
        layout: { 'line-join': 'round', 'line-cap': 'round', 'line-sort-key': ['get', 'r'] },
        paint: {
          'line-color': SPEED_COLOR,
          'line-width': SPEED_W,
          'line-offset': SPEED_OFF,
        },
      },
      firstLabel,
    )
    m.addLayer(
      {
        id: 'route-casing',
        type: 'line',
        source: 'route',
        layout: { 'line-join': 'round', 'line-cap': 'round', 'line-sort-key': ['case', ['get', 'sel'], 1, 0] },
        paint: {
          'line-color': C('paper'),
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
        paint: { 'line-color': C('paper'), 'line-opacity': 0.85, 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 6, 15, 10] },
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
          'line-color': C('walk'),
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
        paint: { 'line-color': C('paper'), 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 8, 15, 15] },
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
    // The speed overlay on a planned route: over the ride's own line, the tapped hop outlined.
    m.addLayer(
      {
        id: 'speed-route-sel',
        type: 'line',
        source: 'speed-route',
        filter: ['get', 'sel'],
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': C('ink'), 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 9, 15, 15] },
      },
      firstLabel,
    )
    m.addLayer(
      {
        id: 'speed-route',
        type: 'line',
        source: 'speed-route',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': SPEED_COLOR, 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 5, 15, 10] },
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
        'circle-color': C('paper'),
        'circle-stroke-color': C('ink2'),
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
        'circle-color': C('paper'),
        'circle-stroke-color': C('ink2'),
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
      paint: { 'text-color': C('ink') },
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
      paint: { 'text-color': C('ink2'), 'text-halo-color': C('paper'), 'text-halo-width': 1.5 },
    })
    // The open station, at any zoom.
    m.addLayer({
      id: 'station-sel',
      type: 'circle',
      source: 'station-sel',
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 6, 16, 11],
        'circle-color': C('paper'),
        'circle-opacity': ['step', ['zoom'], 1, 17, 0],
        'circle-stroke-color': C('ink'),
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
      paint: { 'text-color': C('ink'), 'text-halo-color': C('paper'), 'text-halo-width': 2 },
    })
    m.addLayer({
      id: 'route-stops',
      type: 'circle',
      source: 'route-stops',
      minzoom: 11,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 2.5, 15, 5.5],
        'circle-color': C('paper'),
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
      paint: { 'text-color': C('ink'), 'text-halo-color': C('paper'), 'text-halo-width': 2 },
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
      paint: { 'icon-opacity': C('dim') },
    })
    m.addLayer({
      id: 'plan-stops',
      type: 'circle',
      source: 'plan-stops',
      layout: { 'circle-sort-key': ['match', ['get', 'role'], 'mid', 0, 1] },
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, ['match', ['get', 'role'], 'mid', 2.5, 7], 15, ['match', ['get', 'role'], 'mid', 4, 8.5]],
        'circle-color': ['match', ['get', 'role'], 'board', ['get', 'color'], C('paper')],
        'circle-stroke-color': ['match', ['get', 'role'], 'board', C('paper'), 'mid', ['get', 'color'], C('ink')],
        'circle-stroke-width': ['match', ['get', 'role'], 'board', 3, 'mid', 2, 4],
      },
    })
    m.addLayer({
      id: 'plan-from',
      type: 'circle',
      source: 'plan-ends',
      filter: ['==', ['get', 'role'], 'from'],
      paint: { 'circle-radius': 7, 'circle-color': C('paper'), 'circle-stroke-color': C('ink'), 'circle-stroke-width': 4.5 },
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
      paint: { 'text-color': C('ink'), 'text-halo-color': C('paper'), 'text-halo-width': 2 },
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
      paint: { 'text-color': C('to'), 'text-halo-color': C('paper'), 'text-halo-width': 2 },
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
        // Pushes the arrow out past wider bodies; the offset turns with the arrow.
        'icon-offset': ['interpolate', ['linear'], ['get', 'ao'], 0, ['literal', [0, 0]], 20, ['literal', [0, -20]]],
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
        'icon-opacity': ['case', ['get', 'idle'], 0.7, dimmed(1, C('dim'), 0.5)],
        'text-opacity': ['case', ['get', 'idle'], 0.9, dimmed(1, 0, 0.6)],
      },
    })
    m.addLayer({
      id: 'veh-tag',
      type: 'symbol',
      source: 'vehicles',
      filter: ['get', 'mine'],
      layout: {
        'text-field': t('Váš spoj', 'Your vehicle'),
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
      paint: { 'text-color': C('mine'), 'text-halo-color': C('paper'), 'text-halo-width': 2 },
    })
    // The user's position: the accuracy circle under the streets' labels, the dot above everything.
    m.addLayer(
      {
        id: 'me-acc',
        type: 'fill',
        source: 'me',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'fill-color': '#146eff', 'fill-opacity': 0.1, 'fill-outline-color': 'rgba(20, 110, 255, 0.45)' },
      },
      firstLabel,
    )
    // The stations of the nearby board, at any zoom, under the vehicles.
    m.addLayer(
      {
        id: 'near',
        type: 'circle',
        source: 'near',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 5, 16, 9],
          'circle-color': C('paper'),
          'circle-stroke-color': C('ink'),
          'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 12, 2.5, 16, 4],
        },
      },
      'veh-body-dim',
    )
    m.addLayer(
      {
        id: 'near-label',
        type: 'symbol',
        source: 'near',
        minzoom: 13,
        layout: {
          'text-field': ['get', 'name'],
          'text-font': ['Noto Sans Bold'],
          'text-size': 12,
          'text-anchor': 'top',
          'text-offset': [0, 1.1],
          'text-optional': true,
        },
        paint: { 'text-color': C('ink'), 'text-halo-color': C('paper'), 'text-halo-width': 2 },
      },
      'veh-body-dim',
    )
    m.addLayer({
      id: 'me-dot',
      type: 'circle',
      source: 'me',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: { 'circle-radius': 7.5, 'circle-color': '#146eff', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 3 },
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
        else setPlanEnd(end, pointValue(e.lngLat.lat, e.lngLat.lng))
        return
      }
      if (app.view.kind === 'reach') {
        // A reached station opens the trip there (back returns to the map); a tap anywhere else
        // starts the reachability map there: at a station, or at the point.
        const v = app.view
        const hit = m.queryRenderedFeatures(box(e.point, r), { layers: ['reach-stops'] })[0]
        if (hit && v.from) return navigate({ kind: 'plan', from: v.from, to: String(hit.properties.station), at: v.at, opt: null })
        const f = m.queryRenderedFeatures(box(e.point, r), { layers: ['stations', 'stops', 'station-sel'] })[0]
        const code = f && String(f.properties.station ?? f.properties.code ?? '')
        if (code && app.stations[code]) setPlanEnd('from', code)
        else setPlanEnd('from', pointValue(e.lngLat.lat, e.lngLat.lng))
        return
      }
      const vs = m.queryRenderedFeatures(box(e.point, r), { layers: ['veh-body', 'veh-body-dim'] })
      const v = vs.find((f) => !f.properties.dim) ?? vs[0]
      // In replay a tap picks a vehicle to follow in the replay panel; the vehicle panel is live.
      if (app.view.kind === 'replay') {
        replay.sel = v ? String(v.properties.key) : null
        return
      }
      // The speed overlay's segments under the finger; they take a tap before dimmed vehicles.
      const sh = app.speed ? m.queryRenderedFeatures(box(e.point, r), { layers: ['speed-line', 'speed-route'] }) : []
      if (v && !(v.properties.dim && sh.length)) return navigate({ kind: 'vehicle', key: String(v.properties.key) })
      const s = m.queryRenderedFeatures(box(e.point, r), { layers: ['plan-stops', 'route-stops', 'stops', 'near', 'stations', 'station-sel'] })[0]
      if (s) {
        const p = s.properties
        // Platforms (route, plan and platform markers carry a stop id) open their station with that platform.
        const stop = p.id ? String(p.id) : null
        const code = p.code ? String(p.code) : stop ? app.stops[stop]?.station : null
        if (code) return navigate({ kind: 'station', code, stop: p.code ? null : stop })
      }
      // The slowest hop under the finger: the one drawn on top.
      if (sh.length) {
        app.speedHop = String(sh.reduce((a, b) => (b.properties.r > a.properties.r ? b : a)).properties.k)
        return
      }
      if (app.speedHop) app.speedHop = null
      const rl = m.queryRenderedFeatures(box(e.point, r), { layers: ['route-line'] })[0]
      if (rl && (app.view.kind === 'line' || app.view.kind === 'reliability')) return navigate({ ...app.view, dir: String(rl.properties.dir) }, { replace: true })
      if (app.view.kind === 'vehicle' || app.view.kind === 'station') closePanel()
    })
    for (const layer of ['reach-stops', 'veh-body', 'veh-body-dim', 'route-stops', 'stops', 'near', 'stations', 'station-sel', 'plan-stops', 'route-line', 'speed-line', 'speed-route']) {
      m.on('mouseenter', layer, () => (m.getCanvas().style.cursor = 'pointer'))
      m.on('mouseleave', layer, () => (m.getCanvas().style.cursor = ''))
    }
  }

  let theme: 'light' | 'dark' = isDark() ? 'dark' : 'light'

  onMount(() => {
    const m = new maplibregl.Map({
      container: el,
      style: STYLE[theme],
      globalState: PALETTE[theme],
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
      locale: mapLocale(),
      dragRotate: false,
      pitchWithRotate: false,
    })
    m.touchZoomRotate.disableRotation()
    m.keyboard.disableRotation()
    addControls(m)
    m.on('load', () => {
      setup(m)
      loaded = true
    })
    map = m
    return () => {
      cancelAnimationFrame(raf)
      m.remove()
    }
  })

  // A language change: MapLibre reads its UI strings when a control is added, so the controls are
  // added again with the new strings.
  let shownLang = prefs.lang
  $effect(() => {
    const lang = prefs.lang
    if (!map || lang === shownLang) return
    shownLang = lang
    untrack(() => {
      const m = map!
      m._locale = { ...m._locale, ...mapLocale() }
      m.getCanvas().setAttribute('aria-label', m._getUIString('Map.Title'))
      for (const c of controls) m.removeControl(c)
      addControls(m)
      if (loaded) m.setLayoutProperty('veh-tag', 'text-field', t('Váš spoj', 'Your vehicle'))
    })
  })

  // The theme changed: the other base map, and the app's layers in its colours.
  $effect(() => {
    const next = isDark() ? 'dark' : 'light'
    if (!map || next === theme) return
    theme = next
    for (const [k, v] of Object.entries(PALETTE[next])) map.setGlobalStateProperty(k, v)
    map.setStyle(STYLE[next], { globalState: PALETTE[next], transformStyle: keepOwn })
  })

  // New positions: animate from where markers are now.
  $effect(() => {
    const live = app.live
    if (loaded && live) untrack(() => onLive(live))
  })

  // The replayed instant moved or its chunk arrived.
  $effect(() => {
    void [replay.t, replay.loaded, replay.sel]
    if (loaded && app.view.kind === 'replay') untrack(() => render(1))
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
    void [app.stations, app.plan, app.speed != null, prefs.lang]
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
      // Switching the speed overlay on or off refits too: its card covers the top of the map.
      const key = `${planQuery(v.from, v.to, v.at)}#${v.opt ?? 0}#${o.legs.map((l) => (l.kind === 'ride' ? l.trip : 'w')).join()}#${app.speed != null}`
      if (fittedPlan === key) return
      fittedPlan = key
      // The trip's live vehicles are in view too, e.g. one still on its way to the boarding stop.
      const mine = (app.live?.vehicles ?? []).filter((x) => planKeys?.has(x.key)).map((x): [number, number] => [x.lon, x.lat])
      requestAnimationFrame(() => fitCoords([...o.legs.flatMap((l) => l.coords), ...mine]))
    })
  })


  /** Reached stations as map points, each with the zoom it shows from (minz): from zoom 9 up, a
   * station shows when no station shown before it is within REACH_GAP_PX, taking the stations most
   * lines pass first, then the earliest. A station once shown stays at every higher zoom. */
  const REACH_GAP_PX = 22
  function reachStations(best: Map<string, number>, bands: number[]) {
    const items = [...best].flatMap(([code, t]) => {
      const st = app.stations[code]
      const b = bands.findIndex((x) => t <= x * 60)
      return st && b >= 0 ? [{ code, t, b, st, x: st.lon * 111_320 * Math.cos((st.lat * Math.PI) / 180), y: st.lat * 110_574, minz: 99 }] : []
    })
    items.sort((a, b) => b.st.lines.length - a.st.lines.length || a.t - b.t)
    const shown: typeof items = []
    for (let z = 9; z <= 16; z++) {
      const gap = (REACH_GAP_PX * 40_075_016 * Math.cos((48.15 * Math.PI) / 180)) / (512 * 2 ** z) // metres
      const grid = new Map<string, typeof items>()
      const cellOf = (it: (typeof items)[number]) => [Math.floor(it.x / gap), Math.floor(it.y / gap)]
      const add = (it: (typeof items)[number]) => {
        const [cx, cy] = cellOf(it)
        const k = `${cx},${cy}`
        grid.set(k, [...(grid.get(k) ?? []), it])
      }
      for (const it of shown) add(it)
      for (const it of items) {
        if (it.minz <= 16 && it.minz < z) continue
        const [cx, cy] = cellOf(it)
        let free = z === 16 // everything from zoom 16
        if (!free) {
          free = true
          for (let dx = -1; dx <= 1 && free; dx++)
            for (let dy = -1; dy <= 1 && free; dy++)
              for (const o of grid.get(`${cx + dx},${cy + dy}`) ?? []) if (Math.hypot(o.x - it.x, o.y - it.y) < gap) free = false
        }
        if (free) {
          it.minz = z
          shown.push(it)
          add(it)
        }
      }
    }
    return items.map((it, i) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [it.st.lon, it.st.lat] },
      properties: { station: it.code, t: it.t, minz: it.minz, rank: i, color: REACH_COLORS[it.b], label: `${Math.max(1, Math.round(it.t / 60))} min` },
    }))
  }

  // The reachability map: its bands, fitted once per starting point, time and limit.
  let fittedReach: string | null = null
  $effect(() => {
    const v = app.view
    const r = app.reach
    if (!loaded || !map) return
    const q = v.kind === 'reach' ? reachQuery(v.from, v.at, v.min) : null
    const data = q && r?.query === q ? r.data : null
    const bands = v.kind === 'reach' ? reachBands(v.min) : []
    const shapes = data ? reachShapes(data, bands) : null
    // Per station, its earliest platform; not the start itself.
    const best = new Map<string, number>()
    for (const [, , t, id] of data?.stops ?? []) {
      const code = app.stops[id]?.station
      if (code && code !== data!.origin.station && t < (best.get(code) ?? Infinity)) best.set(code, t)
    }
    const stations = reachStations(best, bands)
    ;(map.getSource('reach') as GeoJSONSource).setData({ type: 'FeatureCollection', features: [...(shapes?.features ?? []), ...stations] })
    if (!q) fittedReach = null
    if (!shapes?.bounds || fittedReach === q) return
    fittedReach = q
    const [[w, s], [e, n]] = shapes.bounds
    untrack(() => requestAnimationFrame(() => fitCoords([[w, s], [e, n]])))
  })

  $effect(() => {
    const isNew = unread()
    newsButton.classList.toggle('unread', isNew)
    newsButton.ariaLabel = isNew ? t('Čo je nové (nové novinky)', "What's new (new entries)") : t('Čo je nové', "What's new")
    newsButton.setAttribute('aria-pressed', String(app.view.kind === 'news'))
  })

  $effect(() => {
    const on = app.speed != null
    speedButton.setAttribute('aria-pressed', String(on))
    void [app.speedGeometry, app.speedData, app.speedHop, routeHopKeys]
    if (loaded) untrack(updateSpeeds)
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
      if ((app.view.kind === 'line' || app.view.kind === 'reliability') && fitted !== lv.line) {
        fitted = lv.line
        // Wait a frame so the panel has its final size.
        requestAnimationFrame(() => fitLine(lv))
      }
    })
  })
  $effect(() => {
    if (app.view.kind !== 'line' && app.view.kind !== 'reliability') untrack(() => (fitted = null))
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

<div class="map" bind:this={el} role="application" aria-label={t('Mapa vozidiel MHD', 'Map of public transport vehicles')}></div>

<style>
  .map {
    position: absolute;
    inset: 0;
  }
</style>
