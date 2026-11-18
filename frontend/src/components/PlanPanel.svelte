<script lang="ts">
  import { onMount, tick, untrack } from 'svelte'
  import { track } from '../lib/analytics.svelte'
  import { planQuery, poll, refreshPlan } from '../lib/api'
  import { delayBand, delayText, durationText, fromLocalInput, hm, isRegional, minsUntil, toLocalInput, dayText } from '../lib/format'
  import { count, t } from '../lib/i18n'
  import { markHere, placeLabel, rideSig, pointValue, setPlanEnd } from '../lib/places'
  import { routeFavorite } from '../lib/profile.svelte'
  import { routeOverlay } from '../lib/speeds'
  import { app, navigate, setSpeed, SLOW_POLL_MS } from '../lib/state.svelte'
  import type { FallbackOption, PlanOption, PlanPlace, PlanReason, RideLeg } from '../lib/types'
  import DepartPicker from './DepartPicker.svelte'
  import FavButton from './FavButton.svelte'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'
  import PlaceInput from './PlaceInput.svelte'

  let { from, to, at, opt }: { from: string | null; to: string | null; at: string | null; opt: number | null } = $props()

  const query = $derived(planQuery(from, to, at))
  const plan = $derived(app.plan && app.plan.query === query ? app.plan : null)
  const options = $derived(plan?.data?.options ?? [])
  const sel = $derived(opt != null ? (options[Math.min(opt, options.length - 1)] ?? null) : null)
  const now = $derived(app.tick + app.skewMs)
  const reason = $derived(plan?.data?.reason ?? null)
  const fav = $derived(routeFavorite(from, to))

  // --- the form: on phones it folds into one summary line once both ends are set ------------------
  let fromInput = $state<HTMLInputElement>()
  let toInput = $state<HTMLInputElement>()
  let inputFocus = $state(false)
  let formOpen = $state(false)
  let keepOpen = false
  const collapsed = $derived(!!from && !!to && !formOpen && !inputFocus)
  // The phone sheet grows when a field gets focus and stays up until the form folds, so tapping
  // a chip right after typing doesn't hit a sheet that is shrinking under the finger.
  let sheetUp = $state(false)
  $effect(() => {
    if (inputFocus) sheetUp = true
  })
  $effect(() => {
    if (collapsed) sheetUp = false
  })

  // A new end (picked, located, tapped on the map) folds the form again; a swap keeps it open.
  // (Props re-run effects on any view change, so compare with the last ends seen.)
  let lastEnds = untrack(() => `${from}|${to}`)
  $effect(() => {
    const ends = `${from}|${to}`
    if (ends === lastEnds) return
    lastEnds = ends
    untrack(() => {
      if (keepOpen) keepOpen = false
      else formOpen = false
    })
  })

  // Opened with one end set ("Trasa odtiaľto" / "Trasa sem"): start typing the other one.
  onMount(() => {
    if (opt == null && !!from !== !!to) (from ? toInput : fromInput)?.focus()
  })

  function picked(end: 'from' | 'to', code: string) {
    setPlanEnd(end, code)
    const other = end === 'from' ? to : from
    // The empty end is next; with both set, close the keyboard and show the results.
    if (!other) (end === 'from' ? toInput : fromInput)?.focus()
    else (document.activeElement as HTMLElement | null)?.blur()
  }

  async function editForm() {
    formOpen = true
    await tick()
    fromInput?.focus()
  }

  // --- departure time: Bratislava calendar days -----------------------------------------------------
  const DAY_MS = 86_400_000
  const today = $derived(toLocalInput(new Date(now).toISOString()).slice(0, 10))
  const tomorrow = $derived(new Date(Date.parse(today) + DAY_MS).toISOString().slice(0, 10))
  let pickerOpen = $state(false)

  function dayWord(iso: string | null): string {
    if (!iso) return t('teraz', 'now')
    const d = toLocalInput(iso).slice(0, 10)
    return `${d === today ? t('dnes', 'today') : d === tomorrow ? t('zajtra', 'tomorrow') : dayText(iso)} ${hm(iso)}`
  }

  // The open option's rides are kept in its history entry, so coming back to it (the back button
  // after a fallback plan or a vehicle, which remounts or re-queries this panel) shows and tracks the
  // same connection, not whatever now has its index.
  type PlanHist = { prev?: string; sig?: string | null } | null
  const histSig = () => (history.state as PlanHist)?.sig ?? null
  function saveSig(sig: string | null) {
    if (histSig() === sig) return
    history.replaceState({ ...(history.state as object | null), sig }, '')
  }
  /** Focus to move once results are on screen: the first card after opening a fallback, the
   * option's heading when returning to an option. */
  let focusAfter: 'card' | 'sum' | null = null

  // Departing now: refresh every 30 s (SLOW_POLL_MS) while open. A fixed time is fetched once (and on return
  // from a vehicle only if the cached result is for another query or failed).
  $effect(() => {
    const q = query
    untrack(() => {
      selSig = opt != null ? histSig() : null
      if (selSig) focusAfter = 'sum'
    })
    if (!q) return
    if (at) {
      untrack(() => {
        if (app.plan?.query !== q || app.plan.error) refreshPlan(q, selSig)
      })
      return
    }
    // untrack: refreshPlan reads app.plan synchronously, which must not re-run this effect.
    // The open option is tracked, so it stays after its first ride left or a change failed.
    return untrack(() => poll(() => refreshPlan(q, selSig), SLOW_POLL_MS))
  })

  // Keep the chosen option across refreshes: the one with the same rides, else the same index.
  let selSig: string | null = null
  let seen: unknown = null
  $effect(() => {
    const data = plan?.data
    const o = opt
    untrack(() => {
      const fresh = data !== seen
      seen = data
      if (o == null) {
        selSig = null
        saveSig(null)
        return
      }
      if (!data) return
      if (fresh && selSig) {
        const i = data.options.findIndex((x) => rideSig(x) === selSig)
        if (i >= 0 && i !== o) return navigate({ kind: 'plan', from, to, at, opt: i }, { replace: true })
      }
      selSig = rideSig(data.options[Math.min(o, data.options.length - 1)])
      saveSig(selSig)
    })
  })

  $effect(() => {
    // Results on screen (a cached plan that is refreshing counts: its option is already shown).
    const ready = !!plan?.data
    void opt
    if (!ready || !focusAfter) return
    const which = focusAfter
    untrack(async () => {
      focusAfter = null
      await tick()
      if (which === 'sum') sumEl?.focus()
      else (document.querySelector('.panel .card') as HTMLElement | null)?.focus()
    })
  })

  let geoError = $state<string | null>(null)
  let geoBusy = $state<'from' | 'to' | null>(null)
  function locate(end: 'from' | 'to') {
    geoError = null
    if (!navigator.geolocation) {
      geoError = t('Tento prehliadač polohu nepodporuje.', "This browser doesn't support location.")
      return
    }
    geoBusy = end
    navigator.geolocation.getCurrentPosition(
      (p) => {
        geoBusy = null
        setPlanEnd(end, markHere(pointValue(p.coords.latitude, p.coords.longitude)))
      },
      (e) => {
        geoBusy = null
        geoError =
          e.code === e.PERMISSION_DENIED
            ? t('Prístup k polohe je zakázaný.', 'Location access is blocked.')
            : t('Polohu sa nepodarilo zistiť.', "Couldn't find your location.")
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 },
    )
  }

  function pickOnMap(end: 'from' | 'to') {
    app.pick = app.pick === end ? null : end
  }

  function swap() {
    keepOpen = true
    navigate({ kind: 'plan', from: to, to: from, at, opt: null }, { replace: true })
  }

  function setAt(v: string | null) {
    navigate({ kind: 'plan', from, to, at: v, opt: null }, { replace: true })
  }

  // A card opens an option as a new history entry (system back returns to the list); the tabs
  // between options and the panel's back control replace it.
  let sumEl = $state<HTMLElement>()
  async function select(i: number | null, fromCard = false) {
    navigate({ kind: 'plan', from, to, at, opt: i }, { replace: !fromCard })
    if (!fromCard) return
    track('route_option_opened', { index: i })
    await tick()
    sumEl?.focus()
  }

  function backToList() {
    if ((history.state as { prev?: string } | null)?.prev === 'plan') history.back()
    else select(null)
  }

  // Each option starts at the top of the panel.
  $effect(() => {
    void opt
    untrack(() => document.querySelector('.panel .body')?.scrollTo({ top: 0 }))
  })

  const rides = (o: PlanOption) => o.legs.filter((l): l is RideLeg => l.kind === 'ride')
  const isLive = (o: PlanOption) => rides(o).some((l) => l.vehicle || l.delay != null)
  const transfersText = (n: number) =>
    n === 0 ? t('bez prestupu', 'no changes') : count(n, ['prestup', 'prestupy', 'prestupov'], ['change', 'changes'])
  const walkOnly = () => t('len pešo', 'walk only')
  const walkM = (m: number) => t(`${m} m pešo`, `${m} m on foot`)
  /** A map point or the user's location has no name from the planner: label it as the form does. */
  const nameOf = (p: { name: string | null; lat: number; lon: number }) => p.name ?? placeLabel(pointValue(p.lat, p.lon))
  // Minutes between two times as displayed (HH:MM, seconds dropped), so durations add up with them.
  const minOf = (iso: string) => Math.floor(Date.parse(iso) / 60000)
  const walkMin = (s: string, e: string) => Math.max(1, minOf(e) - minOf(s))
  // Live delays: a ride a minute or more late shows its timetable time struck through.
  const isLate = (l: { delay: number | null }) => l.delay != null && l.delay >= 60
  // A regional bus's delay has no 15-minute cap.
  const lateText = (l: { line: string; delay: number | null }) => delayText(l.delay, false, !!app.lines[l.line]?.regional)
  // DPB's vehicles go by fleet number; a regional bus has none and goes by its trip number.
  const vehicleNo = (key: string) => (isRegional(key) ? app.live?.vehicles.find((v) => v.key === key)?.tripNo : key)
  const sched = (iso: string, delay: number | null) => new Date(Date.parse(iso) - (delay ?? 0) * 1000).toISOString()
  /** The worst change of an option with current delays. */
  function riskOf(o: PlanOption): 'missed' | 'tight' | null {
    const s = rides(o).map((l) => l.transfer?.status)
    return s.includes('missed') ? 'missed' : s.includes('tight') ? 'tight' : null
  }
  /** The ride whose change is worst: missed before tight. */
  const riskLeg = (o: PlanOption) =>
    rides(o).find((l) => l.transfer?.status === 'missed') ?? rides(o).find((l) => l.transfer?.status === 'tight') ?? null
  const riskLine = (o: PlanOption) => riskLeg(o)?.line ?? ''
  /** The way on when a change is already missed: the trip's real arrival is then the fallback's. */
  const missedFb = (o: PlanOption) => {
    const l = riskLeg(o)
    return l?.transfer?.status === 'missed' ? l.transfer.fallback : null
  }
  /** Door to door, until the fallback's arrival when a change is missed. */
  const durOf = (o: PlanOption) => (missedFb(o) ? (Date.parse(missedFb(o)!.arrive) - Date.parse(o.depart)) / 1000 : o.duration)

  type FbRide = Extract<FallbackOption['legs'][number], { kind: 'ride' }>
  const fbRides = (fb: FallbackOption) => fb.legs.filter((l): l is FbRide => l.kind === 'ride')
  const laterMin = (fb: FallbackOption, o: PlanOption) => minOf(fb.arrive) - minOf(o.arrive)
  /** "98 › 90 · 10:24 → 11:49 (+60 min)" */
  function fbSummary(fb: FallbackOption, o: PlanOption): string {
    const d = laterMin(fb, o)
    const lines = fbRides(fb).map((l) => l.line).join(' › ') || t('pešo', 'walk')
    // The time to be at the stop: the first ride's departure, not the start of a walk to it.
    const leave = fbRides(fb)[0]?.start ?? fb.depart
    return `${lines} · ${hm(leave)} → ${hm(fb.arrive)}${d > 0 ? ` (+${d} min)` : ''}`
  }
  const placeShort = (p: PlanPlace) => nameOf(p) + (p.platform ? ` (${p.platform})` : '')
  /** Where to board and change: "pešo z Kutlíkova (D) do Pajštúnska (E), 98 o 10:27, prestup Ekonom. univerzita 90". */
  function fbSteps(fb: FallbackOption): string {
    const [first, ...more] = fbRides(fb)
    const start = fb.legs[0]
    if (!first) return t(`pešo z ${placeShort(start.from)}`, `walk from ${placeShort(start.from)}`)
    const a = placeShort(start.from)
    const b = placeShort(first.from)
    const go = hm(first.start)
    const parts =
      start.kind === 'walk' && start.from.name !== first.from.name
        ? [t(`pešo z ${a} do ${b}, ${first.line} o ${go}`, `walk from ${a} to ${b}, ${first.line} at ${go}`)]
        : [t(`z ${b} ${first.line} o ${go}`, `from ${b} ${first.line} at ${go}`)]
    for (const r of more) parts.push(t(`prestup ${r.from.name} ${r.line}`, `change at ${r.from.name} to ${r.line}`))
    return parts.join(', ')
  }
  /** Plan anew from where the fallback starts (where the ride before the change ends), at its time. */
  function openFallback(fb: FallbackOption) {
    const p = fb.legs[0]?.from
    const code = p?.station ?? (p?.stop ? app.stops[p.stop]?.station : null)
    // The departure rounded down to the minute (Bratislava time), never later than the real one.
    if (!code) return
    focusAfter = 'card'
    navigate({ kind: 'plan', from: code, to, at: fromLocalInput(toLocalInput(fb.depart)), opt: null })
  }
  function showRiskBox() {
    const box = document.querySelector('.panel .risk-box') as HTMLElement | null
    box?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    box?.focus({ preventScroll: true })
  }
  /** Delay colour by the app's bands: a minute is muted (on time on the map), amber 2–5 min, red from 5. */
  const lateTone = (delay: number | null) => ['soft', 'amber', 'red', 'red'][delayBand(delay) ?? 0]
  /** The card's accessible name, including what its visible tags say. */
  function cardLabel(o: PlanOption, i: number): string {
    const fb = missedFb(o)
    const dep = hm(o.depart)
    const arr = hm(fb ? fb.arrive : o.arrive)
    const dur = durationText(durOf(o))
    const parts = [t(`Možnosť ${i + 1}: ${dep} až ${arr}, ${dur}`, `Option ${i + 1}: ${dep} to ${arr}, ${dur}`)]
    if (o.tracked) parts.push(t('sledované spojenie', 'tracked connection'))
    else if (isLive(o)) parts.push(t('naživo', 'live'))
    for (const l of rides(o)) if (isLate(l)) parts.push(t(`${l.line} mešká ${lateText(l)}`, `${l.line} is ${lateText(l)} late`))
    const r = riskOf(o)
    const rl = riskLine(o)
    if (r === 'missed')
      parts.push(
        t(`prestup na ${rl} nestihnete`, `you'll miss the change to ${rl}`) +
          (fb ? t(`, pôvodne v cieli o ${hm(o.arrive)}`, `, originally arriving at ${hm(o.arrive)}`) : ''),
      )
    else if (r === 'tight') parts.push(t(`prestup na ${rl} je ohrozený`, `the change to ${rl} is at risk`))
    parts.push(rides(o).length ? transfersText(o.transfers) : walkOnly())
    if (o.walkM) parts.push(walkM(o.walkM))
    return parts.join(', ')
  }
  const prevRide = (o: PlanOption, i: number) => o.legs.slice(0, i).findLast((l): l is RideLeg => l.kind === 'ride')!
  const spareText = (s: number) =>
    s < 60
      ? t('na prestup nezostáva takmer žiadny čas', 'leaves almost no time to change')
      : t(`na prestup zostáva ${Math.floor(s / 60)} min`, `leaves ${Math.floor(s / 60)} min to change`)
  const placeText = (p: PlanPlace) => nameOf(p) + (p.platform ? t(` · nást. ${p.platform}`, ` · platform ${p.platform}`) : '')
  const missText = (line: string) => t(`Prestup na ${line} nestihnete`, `You'll miss the change to ${line}`)
  const noOtherText = () => t('Iné spojenie do cieľa sme nenašli.', 'We found no other connection to the destination.')
  const lateOrOnTime = (l: { line: string; delay: number | null }) =>
    l.delay! < 60 ? t('načas', 'on time') : t(`mešká ${lateText(l)}`, `${lateText(l)} late`)

  function inText(iso: string): string | null {
    if (at || Date.parse(iso) < now - 60_000) return null // a tracked option's ride that already left
    const m = minsUntil(iso, now)
    return m < 1 ? t('teraz', 'now') : m < 60 ? t(`o ${m} min`, `in ${m} min`) : null
  }

  const reasonsText = (): Record<PlanReason, string> => ({
    same_place: t('Začiatok a cieľ sú na rovnakom mieste.', 'The start and destination are in the same place.'),
    no_stops_near_origin: t(
      'Pri začiatku nie je na pešiu vzdialenosť žiadna zastávka MHD. Vyberte iné miesto.',
      'There is no public transport stop within walking distance of the start. Choose another place.',
    ),
    no_stops_near_destination: t(
      'Pri cieli nie je na pešiu vzdialenosť žiadna zastávka MHD. Vyberte iné miesto.',
      'There is no public transport stop within walking distance of the destination. Choose another place.',
    ),
    no_connection: '',
  })
  const noConnection = $derived(
    t(
      `Nenašli sme spojenie${at ? ` na ${dayWord(at)}` : ' v najbližšom čase'}. Skúste iný čas alebo blízku zastávku.`,
      `We found no connection${at ? ` for ${dayWord(at)}` : ' soon'}. Try another time or a nearby stop.`,
    ),
  )
  const reasonText = $derived(reason ? reasonsText()[reason] || noConnection : noConnection)

  /** Wait between arriving at a leg's stop (by a ride or a walk) and its ride leaving, in minutes. */
  function waitMin(o: PlanOption, i: number): number {
    const prev = o.legs[i - 1]
    return prev ? Math.max(0, minOf(o.legs[i].start) - minOf(prev.end)) : 0
  }

  function errorText(e: string): string {
    if (/unknown station|unknown stop/.test(e)) return t('Zastávku sme nenašli. Vyberte ju znova.', "We couldn't find the stop. Choose it again.")
    return t(`Spojenie sa nepodarilo vyhľadať (${e}).`, `Couldn't search for a connection (${e}).`)
  }

  let openStops = $state<Record<number, boolean>>({})
  $effect(() => {
    void opt
    openStops = {}
  })
</script>

{#snippet walkIcon()}
  <svg class="walk" viewBox="0 0 24 24" aria-hidden="true"
    ><circle cx="13" cy="4.5" r="2" /><path d="M10 21l2-6 3 3v3M8 12l2-4 4 1 2 4M12 15l-1-6" /></svg
  >
{/snippet}

{#snippet legsSummary(o: PlanOption | FallbackOption)}
  <span class="seq">
    {#each o.legs as l, i (i)}
      {#if i > 0}<span class="sep" aria-hidden="true">›</span>{/if}
      {#if l.kind === 'ride'}
        <span class="ride-chip">
          <LineBadge line={l.line} size="sm" />
          {#if isLate(l)}<span class="late-badge {lateTone(l.delay)}" role="img" aria-label={t(`mešká ${Math.floor(l.delay! / 60)} min`, `${Math.floor(l.delay! / 60)} min late`)}
              ><span aria-hidden="true">+{Math.floor(l.delay! / 60)}</span></span
            >{/if}
        </span>
      {:else}
        <span class="walk-chip" role="img" aria-label={t(`pešo ${walkMin(l.start, l.end)} min, ${l.m} m`, `walk ${walkMin(l.start, l.end)} min, ${l.m} m`)}
          >{@render walkIcon()}<span class="small" aria-hidden="true">{walkMin(l.start, l.end)} min</span></span
        >
      {/if}
    {/each}
  </span>
{/snippet}

<Panel
  tall
  label={t('Trasa', 'Trip planner')}
  expand={(sheetUp || pickerOpen) && !collapsed && !sel}
  onback={sel ? { label: t('Všetky možnosti', 'All options'), go: backToList } : undefined}
>
  {#snippet header()}
    <svg class="head-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="6" r="2.5" /><path d="M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5" /></svg>
    <strong>{t('Trasa', 'Trip planner')}</strong>
    {#if fav}<FavButton kind="route" ref={fav.ref} names={fav.names} label={t(`trasa ${placeLabel(from)} → ${placeLabel(to)}`, `trip ${placeLabel(from)} → ${placeLabel(to)}`)} />{/if}
  {/snippet}

  {#if sel}
    <!-- One option: compact ends, the other options as tabs, and the timeline. The panel's back
         button (and Esc) return to the list. -->
    <p class="ends">
      {placeLabel(from)} <span aria-hidden="true">→</span><span class="sr">{t('do', 'to')}</span> {placeLabel(to)}
      <span class="muted small">· {dayWord(at)}</span>
    </p>
    {#if options.length > 1}
      <div class="opt-tabs" role="group" aria-label={t('Možnosť', 'Option')}>
        {#each options as o, i (i)}
          <button class:active={o === sel} aria-pressed={o === sel} onclick={() => select(i)}>
            {hm(o.depart)}–{hm(missedFb(o)?.arrive ?? o.arrive)}
          </button>
        {/each}
      </div>
    {/if}
    <div class="sum">
      <h2 class="big" tabindex="-1" bind:this={sumEl}>
        {hm(sel.depart)} →
        {#if missedFb(sel)}
          <s class="old-arr"><span class="sr">{t('pôvodne ', 'originally ')}</span>{hm(sel.arrive)}</s><span class="new-arr"
            ><span class="sr">{t(', teraz ', ', now ')}</span>{hm(missedFb(sel)!.arrive)}</span
          >
        {:else}{hm(sel.arrive)}{/if}
      </h2>
      <span class="muted">{durationText(durOf(sel))} · {rides(sel).length ? transfersText(sel.transfers) : walkOnly()}{sel.walkM ? ` · ${walkM(sel.walkM)}` : ''}</span>
      {#if sel.tracked}<span
          class="tracked small"
          title={t(
            'Toto spojenie sledujeme naživo, aj keď už nie je medzi novými možnosťami.',
            "We're tracking this connection live, even though it's no longer among the new options.",
          )}><span class="live-dot" aria-hidden="true"></span>{t('Sledované naživo', 'Tracked live')}</span
        >{/if}
      {#if rides(sel).length}
        <!-- The speed overlay on this option's rides only, at the time it leaves. -->
        <button class="speed-btn" aria-pressed={app.speed != null} onclick={() => setSpeed(app.speed ? null : routeOverlay(sel, now))}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 17a8 8 0 1 1 15 0" /><path d="M12 15l3.5-5" /></svg>
          {app.speed ? t('Skryť rýchlosť na trase', 'Hide speed on the route') : t('Rýchlosť jazdy na trase', 'Travel speed on the route')}
        </button>
      {/if}
    </div>
    {#if riskLeg(sel)}
      {@const rl = riskLeg(sel)!}
      {@const fb = rl.transfer!.fallback}
      {@const missed = rl.transfer!.status === 'missed'}
      <!-- On phones the change (with its fallback) is below the fold: the banner says the fallback
           and jumps to the details. -->
      <button class="risk-note" class:missed onclick={showRiskBox}>
        <span class="rn-head">{missed ? missText(rl.line) : t(`Prestup na ${rl.line} je ohrozený meškaním`, `The change to ${rl.line} is at risk from a delay`)}</span>
        <span class="rn-fb">
          {#if fb}{missed ? t('Ďalšie spojenie', 'Next connection') : t('Ak ho nestihnete', 'If you miss it')}: <span class="nowrap">{fbSummary(fb, sel)}</span>
          {:else}{noOtherText()}{/if}
        </span>
        <span class="rn-more" aria-hidden="true">{t('Podrobnosti ↓', 'Details ↓')}</span>
      </button>
    {/if}

    <ol class="timeline">
      {#each sel.legs as l, i (i)}
        {#if l.kind === 'walk'}
          <li class="leg walk-leg">
            <span class="t muted">{hm(l.start)}</span>
            <span class="rail dashed" aria-hidden="true"></span>
            <div class="leg-body">
              <div class="walk-line">
                {@render walkIcon()}
                <span><strong>{t('Pešo', 'Walk')} {l.m} m</strong> <span class="muted">· {walkMin(l.start, l.end)} min</span></span>
              </div>
              <span class="muted small">
                {i === 0 ? t(`z ${placeText(l.from)} `, `from ${placeText(l.from)} `) : ''}{t('do', 'to')} {placeText(l.to)}
              </span>
            </div>
          </li>
        {:else}
          {@const transfer = sel.legs.slice(0, i).some((x) => x.kind === 'ride')}
          {@const mid = l.stops.slice(1, -1)}
          <li class="leg ride-leg" style:--c={l.color}>
            <span class="t">
              <strong class={isLate(l) ? lateTone(l.delay) : ''}>{hm(l.start)}</strong>
              {#if isLate(l)}<s class="sched"><span class="sr">{t('podľa cestovného poriadku ', 'timetabled ')}</span>{hm(sched(l.start, l.delay))}</s>{/if}
            </span>
            <span class="rail" aria-hidden="true"><span class="dot" class:ring={transfer} class:origin={i === 0}></span></span>
            <div class="leg-body">
              <div class="stop-name">
                {#if l.from.station}
                  <button class="link" onclick={() => navigate({ kind: 'station', code: l.from.station!, stop: l.from.stop })}>{l.from.name}</button>
                {:else}{l.from.name}{/if}
                {#if l.from.platform}<span class="plat">{l.from.platform}</span>{/if}
                {#if transfer}<span class="muted small">{t('prestup', 'change')}</span>{/if}
              </div>
              {#if i > 0 && (sel.legs[i - 1].kind === 'ride' || waitMin(sel, i) > 0)}
                <span class="muted small">
                  {#if sel.legs[i - 1].kind === 'ride'}{t('príchod', 'arrives')} {hm(sel.legs[i - 1].end)}{/if}
                  {#if l.transfer?.status !== 'missed'}{sel.legs[i - 1].kind === 'ride' ? ' · ' : ''}{t('čakanie', 'wait')} {waitMin(sel, i)} min{/if}
                </span>
              {/if}
              {#if l.transfer && l.transfer.status !== 'ok'}
                {@const prev = prevRide(sel, i)}
                {@const missed = l.transfer.status === 'missed'}
                {@const fb = l.transfer.fallback}
                <div class="risk-box" class:missed tabindex="-1">
                  <strong>{missed ? missText(l.line) : t(`Prestup na ${l.line} je ohrozený`, `The change to ${l.line} is at risk`)}</strong>
                  <span>
                    {prev.line}{isLate(prev) ? t(` mešká ${lateText(prev)} a`, ` is ${lateText(prev)} late and`) : ''}
                    {missed
                      ? t(`príde o ${hm(prev.end)}, ${l.line} odchádza o ${hm(l.start)}.`, `arrives at ${hm(prev.end)}, ${l.line} leaves at ${hm(l.start)}.`)
                      : `${spareText(l.transfer.margin)}.`}
                  </span>
                  {#if fb}
                    <span class="fb-label">{missed ? t('Ďalšie spojenie do cieľa', 'Next connection to the destination') : t('Ak ho nestihnete, ďalšie spojenie', 'If you miss it, the next connection')}:</span>
                    <button class="fb" onclick={() => openFallback(fb)}>
                      <span class="fb-top">
                        {@render legsSummary(fb)}
                        <span><strong class="fb-times">{hm(fb.depart)} → {hm(fb.arrive)}</strong>
                          {#if laterMin(fb, sel) > 0}<span class="muted small">· {t(`v cieli o ${laterMin(fb, sel)} min neskôr`, `arrives ${laterMin(fb, sel)} min later`)}</span>{/if}</span>
                      </span>
                      <span class="fb-steps">{fbSteps(fb)}</span>
                      <span class="fb-go">{t('Zobraziť toto spojenie', 'Show this connection')} <span aria-hidden="true">›</span></span>
                    </button>
                  {:else}
                    <span class="muted small">{noOtherText()}</span>
                  {/if}
                </div>
              {/if}
              <div class="ride">
                <LineBadge line={l.line} />
                <span class="hs">→ {l.headsign}</span>
              </div>
              {#if l.vehicle}
                {@const no = vehicleNo(l.vehicle)}
                <button class="mine" onclick={() => navigate({ kind: 'vehicle', key: l.vehicle! })}>
                  <span class="live-dot" aria-hidden="true"></span>
                  <span>{t('Váš spoj', 'Your vehicle')}{no != null ? t(` č. ${no}`, ` no. ${no}`) : ''}{#if l.delay != null}{' · '}<span class="nowrap">{lateOrOnTime(l)}</span>{/if}</span>
                  <span aria-hidden="true">›</span>
                </button>
              {:else if l.delay != null}
                <span class="mine static"><span class="live-dot" aria-hidden="true"></span>{lateOrOnTime(l)}</span>
              {/if}
              <button class="count" onclick={() => (openStops = { ...openStops, [i]: !openStops[i] })} aria-expanded={!!openStops[i]} disabled={!mid.length}>
                {walkMin(l.start, l.end)} min · {count(l.stops.length - 1, ['zastávka', 'zastávky', 'zastávok'], ['stop', 'stops'])}
                {#if mid.length}<span aria-hidden="true">{openStops[i] ? '▴' : '▾'}</span>{/if}
              </button>
              {#if openStops[i]}
                <ol class="mid">
                  {#each mid as s (s.stop)}
                    <li><span class="muted">{hm(s.time)}</span> {s.name}</li>
                  {/each}
                </ol>
              {/if}
            </div>
          </li>
          {#if sel.legs[i + 1]?.kind !== 'ride'}
            <li class="leg alight" style:--c={l.color}>
              <span class="t">
                <strong class={isLate(l) ? lateTone(l.delay) : ''}>{hm(l.end)}</strong>
                {#if isLate(l)}<s class="sched"><span class="sr">{t('podľa cestovného poriadku ', 'timetabled ')}</span>{hm(sched(l.end, l.delay))}</s>{/if}
              </span>
              <span class="rail end" aria-hidden="true"><span class="dot" class:flag={i === sel.legs.length - 1} class:ring={i !== sel.legs.length - 1}></span></span>
              <div class="leg-body">
                <div class="stop-name">
                  {#if l.to.station}
                    <button class="link" onclick={() => navigate({ kind: 'station', code: l.to.station!, stop: l.to.stop })}>{l.to.name}</button>
                  {:else}{l.to.name}{/if}
                  {#if l.to.platform}<span class="plat">{l.to.platform}</span>{/if}
                  <span class="muted small">{i === sel.legs.length - 1 ? t('cieľ', 'destination') : t('vystúpiť', 'get off')}</span>
                </div>
              </div>
            </li>
          {/if}
        {/if}
      {/each}
      {#if sel.legs.at(-1)?.kind === 'walk'}
        <li class="leg arrive">
          <span class="t"><strong>{hm(sel.arrive)}</strong></span>
          <span class="rail end" aria-hidden="true"><span class="dot flag"></span></span>
          <div class="leg-body"><div class="stop-name">{placeLabel(to)} <span class="muted small">{t('cieľ', 'destination')}</span></div></div>
        </li>
      {/if}
    </ol>
  {:else}
    {#if collapsed}
      <button class="summary-line" onclick={editForm} aria-label={t(`Upraviť: ${placeLabel(from)} do ${placeLabel(to)}, ${dayWord(at)}`, `Edit: ${placeLabel(from)} to ${placeLabel(to)}, ${dayWord(at)}`)}>
        <span class="sl-text"><strong>{placeLabel(from)} → {placeLabel(to)}</strong> <span class="muted">· {dayWord(at)}</span></span>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4" /></svg>
      </button>
    {/if}
    <div
      class="form-wrap"
      class:collapsed
      onfocusin={(e) => (inputFocus = (e.target as HTMLElement).tagName === 'INPUT')}
      onfocusout={() => (inputFocus = false)}
    >
    <div class="form">
      <div class="ends-form">
        <PlaceInput end="from" label={t('Odkiaľ', 'From')} value={from} bind:input={fromInput} onpick={(c) => picked('from', c)} onlocate={() => locate('from')} onmap={() => pickOnMap('from')} />
        <PlaceInput end="to" label={t('Kam', 'To')} value={to} bind:input={toInput} onpick={(c) => picked('to', c)} onlocate={() => locate('to')} onmap={() => pickOnMap('to')} />
      </div>
      <button class="swap" onclick={swap} aria-label={t('Vymeniť začiatok a cieľ', 'Swap start and destination')} title={t('Vymeniť', 'Swap')} disabled={!from && !to}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4v16M8 4L4.5 7.5M8 4l3.5 3.5M16 20V4M16 20l-3.5-3.5M16 20l3.5-3.5" /></svg>
      </button>
    </div>
    {#if geoBusy}<p class="note">{t('Zisťujem polohu…', 'Finding your location…')}</p>{/if}
    {#if geoError}<p class="note error">{geoError}</p>{/if}

    <div class="when">
      <DepartPicker {at} {now} bind:open={pickerOpen} onchange={setAt} />
    </div>
    </div>

    {#if !from || !to}
      <p class="note">
        {t(
          'Zadajte, odkiaľ a kam idete: názov zastávky, vašu polohu alebo bod na mape.',
          "Enter where you're going from and to: a stop name, your location or a point on the map.",
        )}
      </p>
    {:else if from === to}
      <p class="note">{t('Začiatok a cieľ sú rovnaké.', 'The start and destination are the same.')}</p>
    {:else if !plan || (plan.loading && !plan.data)}
      <div class="skeleton" aria-busy="true"><div></div><div></div><div></div></div>
    {:else if plan.error && !plan.data}
      <p class="note error">{errorText(plan.error)}</p>
    {:else if !options.length}
      <p class="empty">{reasonText}</p>
    {:else}
      {#if reason === 'no_connection'}
        <p class="note">
          {t(
            `Spojenie MHD${at ? ` na ${dayWord(at)}` : ''} sme nenašli, dá sa však ísť pešo.`,
            `We found no public transport connection${at ? ` for ${dayWord(at)}` : ''}, but you can walk.`,
          )}
        </p>
      {:else if reason}<p class="note">{reasonText}</p>{/if}
      <ul class="cards">
        {#each options as o, i (i)}
          {@const first = rides(o)[0]}
          <li>
            <button class="card" class:drawn={i === 0} onclick={() => select(i, true)} aria-label={cardLabel(o, i)}>
              <span class="card-top">
                <strong class="times">
                  {hm(o.depart)} →
                  {#if missedFb(o)}<s class="old-arr">{hm(o.arrive)}</s><span class="new-arr">{hm(missedFb(o)!.arrive)}</span>
                  {:else}{hm(o.arrive)}{/if}
                </strong>
                <span class="dur">{durationText(durOf(o))}</span>
              </span>
              {@render legsSummary(o)}
              <span class="card-meta muted small">
                {#if o.tracked}<span class="live"><span class="live-dot" aria-hidden="true"></span>{t('sledované spojenie', 'tracked connection')}</span>
                {:else if isLive(o)}<span class="live"><span class="live-dot" aria-hidden="true"></span>{t('naživo', 'live')}</span>{/if}
                {#if riskOf(o)}
                  <span class="risk-tag" class:missed={riskOf(o) === 'missed'}>
                    {riskOf(o) === 'missed'
                      ? t(`prestup na ${riskLine(o)} nestihnete`, `you'll miss the change to ${riskLine(o)}`)
                      : t(`prestup na ${riskLine(o)} ohrozený`, `change to ${riskLine(o)} at risk`)}
                  </span>
                {/if}
                {#if first && inText(first.start)}<span class="soon">{first.line} {inText(first.start)}</span>{/if}
                <span>{rides(o).length ? transfersText(o.transfers) : walkOnly()}</span>
                {#if o.walkM}<span>{walkM(o.walkM)}</span>{/if}
              </span>
            </button>
          </li>
        {/each}
      </ul>
      {#if plan.error}<p class="note error">{t('Obnovenie zlyhalo, ukazujeme posledné výsledky.', 'Refreshing failed; showing the last results.')}</p>{/if}
    {/if}
  {/if}
</Panel>

<style>
  .head-icon {
    width: 24px;
    height: 24px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
  .form {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .ends-form {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .swap {
    flex: none;
    width: 36px;
    height: 48px;
    border-radius: 10px;
    display: grid;
    place-items: center;
    color: var(--muted);
  }
  .swap:hover:not(:disabled) {
    background: var(--hover);
    color: var(--text);
  }
  .swap:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .swap svg {
    width: 22px;
    height: 22px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .when {
    margin: 10px 0 4px 22px;
  }
  .summary-line {
    display: none;
  }
  @media (max-width: 767.98px) {
    .form-wrap.collapsed {
      display: none;
    }
    .summary-line {
      width: 100%;
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 46px;
      padding: 8px 12px;
      border-radius: 12px;
      background: var(--chip);
      text-align: left;
    }
    .summary-line:hover {
      background: var(--hover);
    }
    .sl-text {
      flex: 1;
      min-width: 0;
      line-height: 1.3;
    }
    .summary-line svg {
      flex: none;
      width: 20px;
      height: 20px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linejoin: round;
    }
  }
  .cards {
    list-style: none;
    margin: 12px 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .card {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    border-radius: 12px;
    border: 1.5px solid var(--line);
    text-align: left;
  }
  .card:hover {
    background: var(--hover);
  }
  .card.drawn {
    border-color: var(--text);
  }
  .card-top {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8px;
  }
  .times {
    font-size: 1.1rem;
    font-variant-numeric: tabular-nums;
  }
  .dur {
    font-weight: 600;
    white-space: nowrap;
  }
  .seq {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
  }
  .sep {
    color: var(--muted);
  }
  .walk-chip {
    display: inline-flex;
    align-items: center;
    gap: 1px;
    color: var(--muted);
  }
  .walk {
    width: 18px;
    height: 18px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
    flex: none;
  }
  .ride-chip {
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }
  .late-badge {
    font-weight: 700;
    font-size: 0.8rem;
    font-variant-numeric: tabular-nums;
  }
  .risk-tag {
    color: var(--warn-text);
    font-weight: 600;
  }
  .risk-tag.missed {
    color: var(--bad-text);
  }
  .risk-tag::before {
    content: '⚠ ';
  }
  .risk-note {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 2px;
    text-align: left;
    margin: 0 0 10px;
    padding: 8px 10px;
    border-radius: 10px;
    background: var(--warn-bg);
    color: var(--warn-text);
    font-weight: 600;
    font-size: 0.88rem;
  }
  .rn-fb {
    font-weight: 500;
    color: var(--text);
  }
  .rn-more {
    font-size: 0.8rem;
    text-decoration: underline;
  }
  .risk-note.missed {
    background: var(--bad-bg);
    color: var(--bad-text);
  }
  .risk-box {
    align-self: stretch;
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin: 2px 0 4px;
    padding: 8px 10px;
    border-radius: 10px;
    border-left: 4px solid var(--warn);
    background: var(--warn-bg);
    font-size: 0.88rem;
  }
  .risk-box > strong {
    color: var(--warn-text);
  }
  .risk-box.missed {
    border-left-color: var(--bad);
    background: var(--bad-bg);
  }
  .risk-box.missed > strong {
    color: var(--bad-text);
  }
  .fb-label {
    margin-top: 2px;
    font-weight: 600;
  }
  .fb {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
    width: 100%;
    padding: 8px 10px;
    border-radius: 10px;
    background: var(--surface);
    border: 1.5px solid var(--line);
    text-align: left;
  }
  .fb:hover {
    border-color: var(--text);
  }
  .fb-top {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 10px;
  }
  .fb-steps {
    font-size: 0.85rem;
  }
  .fb-go {
    color: var(--accent);
    font-weight: 600;
    font-size: 0.85rem;
  }
  .risk-box:focus {
    outline: none;
  }
  .fb-times {
    font-variant-numeric: tabular-nums;
  }
  .soft {
    color: var(--muted);
  }
  .amber {
    color: var(--warn-text);
  }
  .red {
    color: var(--bad-text);
  }
  .old-arr {
    color: var(--muted);
    font-weight: 600;
    font-size: 0.85em;
  }
  .new-arr {
    margin-left: 0.3em;
    color: var(--bad-text);
  }
  .nowrap {
    white-space: nowrap;
  }
  .speed-btn {
    align-self: flex-start;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-top: 8px;
    padding: 6px 12px;
    min-height: 36px;
    border-radius: 9px;
    background: var(--chip);
    font-weight: 600;
    font-size: 0.88rem;
  }
  .speed-btn:hover {
    background: var(--hover);
  }
  .speed-btn[aria-pressed='true'] {
    background: var(--text);
    color: var(--on-text);
  }
  .speed-btn svg {
    width: 18px;
    height: 18px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2.2;
    stroke-linecap: round;
  }
  .tracked {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--ok);
    font-weight: 600;
  }
  .sched {
    display: block;
    color: var(--muted);
    font-size: 0.8rem;
  }
  .card-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 10px;
  }
  .live {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: var(--ok);
    font-weight: 600;
  }
  .soon {
    color: var(--text);
    font-weight: 600;
  }
  .live-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--ok);
    box-shadow: 0 0 0 2.5px rgba(26, 152, 80, 0.2);
    flex: none;
  }
  .empty {
    margin: 12px 0;
    padding: 14px;
    border-radius: 12px;
    background: var(--chip);
    color: var(--muted);
    text-align: center;
  }
  .ends {
    margin: 2px 0 8px;
    font-weight: 600;
  }
  .opt-tabs {
    display: flex;
    gap: 6px;
    margin-bottom: 10px;
    overflow-x: auto;
  }
  .opt-tabs button {
    flex: 1;
    min-width: max-content;
    height: 34px;
    padding: 0 10px;
    border-radius: 999px;
    background: var(--chip);
    font-weight: 600;
    font-size: 0.85rem;
    font-variant-numeric: tabular-nums;
  }
  .opt-tabs button.active {
    background: var(--text);
    color: var(--on-text);
  }
  .big:focus {
    outline: none;
  }
  .sum {
    display: flex;
    flex-direction: column;
    margin-bottom: 10px;
  }
  .big {
    margin: 0;
    font-size: 1.2rem;
    font-variant-numeric: tabular-nums;
  }
  .timeline {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .leg {
    display: grid;
    grid-template-columns: 3.2em 22px 1fr;
    gap: 0 8px;
  }
  .t {
    font-variant-numeric: tabular-nums;
    padding-top: 2px;
  }
  .rail {
    position: relative;
  }
  .rail::before {
    content: '';
    position: absolute;
    left: 8px;
    top: 0;
    bottom: 0;
    width: 6px;
    background: var(--c, var(--rail));
    border-radius: 3px;
  }
  .rail.dashed::before {
    width: 0;
    left: 10px;
    background: none;
    border-left: 3px dotted #8d95a0;
  }
  .rail.end::before {
    bottom: auto;
    height: 12px;
  }
  .arrive .rail::before {
    display: none;
  }
  .dot {
    position: absolute;
    left: 3px;
    top: 3px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--c, var(--text));
    border: 3px solid var(--surface);
    box-shadow: 0 0 0 1.5px var(--c, var(--text));
  }
  .dot.ring {
    background: var(--surface);
    border: 4px solid var(--c, var(--text));
    box-shadow: 0 0 0 2px var(--surface), 0 0 0 3.5px var(--text);
  }
  .dot.origin {
    background: var(--surface);
    border: 4px solid var(--text);
    box-shadow: 0 0 0 2px var(--surface);
  }
  .dot.flag {
    background: var(--bad);
    border-radius: 4px;
    box-shadow: 0 0 0 1.5px var(--bad);
  }
  .leg-body {
    min-width: 0;
    padding-bottom: 14px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    align-items: flex-start;
  }
  .walk-line {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .stop-name {
    font-weight: 600;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .link {
    font-weight: 600;
    text-align: left;
  }
  .link:hover {
    text-decoration: underline;
  }
  .plat {
    font-size: 0.75rem;
    font-weight: 700;
    min-width: 20px;
    height: 20px;
    padding: 0 5px;
    border-radius: 5px;
    border: 1.5px solid var(--text);
    display: inline-grid;
    place-items: center;
  }
  .ride {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .hs {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mine {
    text-align: left;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    background: var(--ok-bg);
    color: var(--ok-text);
    font-weight: 600;
    font-size: 0.85rem;
  }
  .mine.static {
    background: none;
    padding: 0;
  }
  .count {
    color: var(--muted);
    font-size: 0.85rem;
    padding: 2px 0;
  }
  .count:disabled {
    cursor: default;
  }
  .mid {
    list-style: none;
    margin: 0;
    padding: 0;
    font-size: 0.85rem;
  }
  .mid li {
    padding: 2px 0;
  }
  .skeleton div {
    height: 60px;
    border-radius: 12px;
    background: var(--chip);
    margin: 10px 0;
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse {
    50% {
      opacity: 0.5;
    }
  }
</style>
