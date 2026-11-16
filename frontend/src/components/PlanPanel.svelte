<script lang="ts">
  import { untrack } from 'svelte'
  import { planQuery, poll, refreshPlan } from '../lib/api'
  import { delayText, durationText, fromLocalInput, hm, minsUntil, plural, toLocalInput, dayText } from '../lib/format'
  import { firstTrip, placeLabel, pointValue, setPlanEnd } from '../lib/places'
  import { app, navigate } from '../lib/state.svelte'
  import type { PlanOption, RideLeg } from '../lib/types'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'
  import PlaceInput from './PlaceInput.svelte'

  let { from, to, at, opt }: { from: string | null; to: string | null; at: string | null; opt: number | null } = $props()

  const query = $derived(planQuery(from, to, at))
  const plan = $derived(app.plan && app.plan.query === query ? app.plan : null)
  const options = $derived(plan?.data?.options ?? [])
  const sel = $derived(opt != null ? (options[Math.min(opt, options.length - 1)] ?? null) : null)
  const now = $derived(app.tick + app.skewMs)

  // Departing now: refresh every 30 s while open. A fixed time is fetched once (and on return
  // from a vehicle only if the cached result is for another query or failed).
  $effect(() => {
    const q = query
    if (!q) return
    if (at) {
      untrack(() => {
        if (app.plan?.query !== q || app.plan.error) refreshPlan(q)
      })
      return
    }
    // untrack: refreshPlan reads app.plan synchronously, which must not re-run this effect.
    return untrack(() => poll(() => refreshPlan(q)))
  })

  // Keep the chosen option across refreshes: the one with the same first ride, else the same index.
  let selTrip: string | null = null
  let seen: unknown = null
  $effect(() => {
    const data = plan?.data
    const o = opt
    untrack(() => {
      const fresh = data !== seen
      seen = data
      if (!data || o == null) {
        if (o == null) selTrip = null
        return
      }
      if (fresh && selTrip) {
        const i = data.options.findIndex((x) => firstTrip(x) === selTrip)
        if (i >= 0 && i !== o) return navigate({ kind: 'plan', from, to, at, opt: i }, { replace: true })
      }
      selTrip = firstTrip(data.options[Math.min(o, data.options.length - 1)])
    })
  })

  let geoError = $state<string | null>(null)
  let geoBusy = $state<'from' | 'to' | null>(null)
  function locate(end: 'from' | 'to') {
    geoError = null
    if (!navigator.geolocation) {
      geoError = 'Tento prehliadač polohu nepodporuje.'
      return
    }
    geoBusy = end
    navigator.geolocation.getCurrentPosition(
      (p) => {
        geoBusy = null
        setPlanEnd(end, pointValue(p.coords.latitude, p.coords.longitude), 'Moja poloha')
      },
      (e) => {
        geoBusy = null
        geoError = e.code === e.PERMISSION_DENIED ? 'Prístup k polohe je zakázaný.' : 'Polohu sa nepodarilo zistiť.'
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 },
    )
  }

  function pickOnMap(end: 'from' | 'to') {
    app.pick = app.pick === end ? null : end
  }

  function swap() {
    navigate({ kind: 'plan', from: to, to: from, at, opt: null }, { replace: true })
  }

  function setAt(v: string | null) {
    navigate({ kind: 'plan', from, to, at: v, opt: null }, { replace: true })
  }

  function later() {
    // The next full 5 minutes, in Bratislava time.
    const ms = Math.ceil((now + 60_000) / 300_000) * 300_000
    setAt(fromLocalInput(toLocalInput(new Date(ms).toISOString())))
  }

  function select(i: number | null) {
    navigate({ kind: 'plan', from, to, at, opt: i }, { replace: i == null })
  }

  const rides = (o: PlanOption) => o.legs.filter((l): l is RideLeg => l.kind === 'ride')
  const isLive = (o: PlanOption) => rides(o).some((l) => l.vehicle || l.delay != null)
  const transfersText = (n: number) => (n === 0 ? 'bez prestupu' : plural(n, 'prestup', 'prestupy', 'prestupov'))
  const walkMin = (s: string, e: string) => Math.max(1, Math.round((Date.parse(e) - Date.parse(s)) / 60000))
  const placeText = (p: { name: string; platform: string | null }) => p.name + (p.platform ? ` · nást. ${p.platform}` : '')

  function inText(iso: string): string | null {
    if (at) return null
    const m = minsUntil(iso, now)
    return m < 1 ? 'teraz' : m < 60 ? `o ${m} min` : null
  }

  function errorText(e: string): string {
    if (/unknown station|unknown stop/.test(e)) return 'Zastávku sme nenašli. Vyberte ju znova.'
    return `Spojenie sa nepodarilo vyhľadať (${e}).`
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

{#snippet legsSummary(o: PlanOption)}
  <span class="seq">
    {#each o.legs as l, i (i)}
      {#if i > 0}<span class="sep" aria-hidden="true">›</span>{/if}
      {#if l.kind === 'ride'}
        <LineBadge line={l.line} size="sm" />
      {:else}
        <span class="walk-chip" aria-label="pešo {l.m} m">{@render walkIcon()}<span class="small">{walkMin(l.start, l.end)}</span></span>
      {/if}
    {/each}
  </span>
{/snippet}

<Panel tall label="Trasa">
  {#snippet header()}
    <svg class="head-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="6" r="2.5" /><path d="M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5" /></svg>
    <strong>Trasa</strong>
  {/snippet}

  {#if sel}
    <!-- One option: compact ends, the other options as tabs, and the timeline. -->
    <button class="back-list" onclick={() => select(null)}>
      <span aria-hidden="true">‹</span> Všetky možnosti
    </button>
    <p class="ends">{placeLabel(from)} <span aria-hidden="true">→</span><span class="sr">do</span> {placeLabel(to)}</p>
    {#if options.length > 1}
      <div class="opt-tabs" role="group" aria-label="Možnosť">
        {#each options as o, i (i)}
          <button class:active={o === sel} aria-pressed={o === sel} onclick={() => select(i)}>
            {hm(o.depart)}–{hm(o.arrive)}
          </button>
        {/each}
      </div>
    {/if}
    <div class="sum">
      <strong class="big">{hm(sel.depart)} → {hm(sel.arrive)}</strong>
      <span class="muted">{durationText(sel.duration)} · {rides(sel).length ? transfersText(sel.transfers) : 'len pešo'}{sel.walkM ? ` · ${sel.walkM} m pešo` : ''}</span>
    </div>

    <ol class="timeline">
      {#each sel.legs as l, i (i)}
        {#if l.kind === 'walk'}
          <li class="leg walk-leg">
            <span class="t muted">{hm(l.start)}</span>
            <span class="rail dashed" aria-hidden="true"></span>
            <div class="leg-body">
              <div class="walk-line">
                {@render walkIcon()}
                <span><strong>Pešo {l.m} m</strong> <span class="muted">· {walkMin(l.start, l.end)} min</span></span>
              </div>
              <span class="muted small">
                {i === 0 ? `z ${placeText(l.from)} ` : ''}do {placeText(l.to)}
              </span>
            </div>
          </li>
        {:else}
          {@const transfer = sel.legs.slice(0, i).some((x) => x.kind === 'ride')}
          {@const mid = l.stops.slice(1, -1)}
          <li class="leg ride-leg" style:--c={l.color}>
            <span class="t"><strong>{hm(l.start)}</strong></span>
            <span class="rail" aria-hidden="true"><span class="dot" class:ring={transfer}></span></span>
            <div class="leg-body">
              <div class="stop-name">
                {#if l.from.station}
                  <button class="link" onclick={() => navigate({ kind: 'station', code: l.from.station!, stop: l.from.stop })}>{l.from.name}</button>
                {:else}{l.from.name}{/if}
                {#if l.from.platform}<span class="plat">{l.from.platform}</span>{/if}
                {#if transfer}<span class="muted small">prestup</span>{/if}
              </div>
              <div class="ride">
                <LineBadge line={l.line} />
                <span class="hs">→ {l.headsign}</span>
              </div>
              {#if l.vehicle}
                <button class="mine" onclick={() => navigate({ kind: 'vehicle', key: l.vehicle! })}>
                  <span class="live-dot" aria-hidden="true"></span>
                  Tvoj spoj č. {l.vehicle}{l.delay != null ? ` · ${l.delay < 60 ? 'načas' : `mešká ${delayText(l.delay)}`}` : ''}
                  <span aria-hidden="true">›</span>
                </button>
              {:else if l.delay != null}
                <span class="mine static"><span class="live-dot" aria-hidden="true"></span>{l.delay < 60 ? 'načas' : `mešká ${delayText(l.delay)}`}</span>
              {/if}
              <button class="count" onclick={() => (openStops = { ...openStops, [i]: !openStops[i] })} aria-expanded={!!openStops[i]} disabled={!mid.length}>
                {walkMin(l.start, l.end)} min · {plural(l.stops.length - 1, 'zastávka', 'zastávky', 'zastávok')}
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
              <span class="t"><strong>{hm(l.end)}</strong></span>
              <span class="rail end" aria-hidden="true"><span class="dot" class:flag={i === sel.legs.length - 1} class:ring={i !== sel.legs.length - 1}></span></span>
              <div class="leg-body">
                <div class="stop-name">
                  {#if l.to.station}
                    <button class="link" onclick={() => navigate({ kind: 'station', code: l.to.station!, stop: l.to.stop })}>{l.to.name}</button>
                  {:else}{l.to.name}{/if}
                  {#if l.to.platform}<span class="plat">{l.to.platform}</span>{/if}
                  <span class="muted small">{i === sel.legs.length - 1 ? 'cieľ' : 'vystúpiť'}</span>
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
          <div class="leg-body"><div class="stop-name">{placeLabel(to)} <span class="muted small">cieľ</span></div></div>
        </li>
      {/if}
    </ol>
  {:else}
    <div class="form">
      <div class="ends-form">
        <PlaceInput end="from" label="Odkiaľ" value={from} onpick={(c) => setPlanEnd('from', c)} onlocate={() => locate('from')} onmap={() => pickOnMap('from')} />
        <PlaceInput end="to" label="Kam" value={to} onpick={(c) => setPlanEnd('to', c)} onlocate={() => locate('to')} onmap={() => pickOnMap('to')} />
      </div>
      <button class="swap" onclick={swap} aria-label="Vymeniť začiatok a cieľ" title="Vymeniť" disabled={!from && !to}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4v16M8 4L4.5 7.5M8 4l3.5 3.5M16 20V4M16 20l-3.5-3.5M16 20l3.5-3.5" /></svg>
      </button>
    </div>
    {#if geoBusy}<p class="note">Zisťujem polohu…</p>{/if}
    {#if geoError}<p class="note error">{geoError}</p>{/if}

    <div class="when" role="group" aria-label="Čas odchodu">
      <button class:active={!at} aria-pressed={!at} onclick={() => setAt(null)}>Teraz</button>
      <button class:active={!!at} aria-pressed={!!at} onclick={() => !at && later()}>Odchod o…</button>
      {#if at}
        <input
          type="datetime-local"
          aria-label="Dátum a čas odchodu"
          value={toLocalInput(at)}
          onchange={(e) => {
            const v = fromLocalInput((e.currentTarget as HTMLInputElement).value)
            if (v) setAt(v)
          }}
        />
      {/if}
    </div>

    {#if !from || !to}
      <p class="note">Zadajte, odkiaľ a kam idete: názov zastávky, vašu polohu alebo bod na mape.</p>
    {:else if from === to}
      <p class="note">Začiatok a cieľ sú rovnaké.</p>
    {:else if !plan || (plan.loading && !plan.data)}
      <div class="skeleton" aria-busy="true"><div></div><div></div><div></div></div>
    {:else if plan.error && !plan.data}
      <p class="note error">{errorText(plan.error)}</p>
    {:else if !options.length}
      <p class="empty">Nenašli sme spojenie{at ? ` na ${dayText(at)} ${hm(at)}` : ' v najbližšom čase'}. Skúste iný čas alebo blízku zastávku.</p>
    {:else}
      <ul class="cards">
        {#each options as o, i (i)}
          {@const first = rides(o)[0]}
          <li>
            <button class="card" class:drawn={i === 0} onclick={() => select(i)} aria-label="Možnosť {i + 1}: {hm(o.depart)} až {hm(o.arrive)}, {durationText(o.duration)}">
              <span class="card-top">
                <strong class="times">{hm(o.depart)} → {hm(o.arrive)}</strong>
                <span class="dur">{durationText(o.duration)}</span>
              </span>
              {@render legsSummary(o)}
              <span class="card-meta muted small">
                {#if isLive(o)}<span class="live"><span class="live-dot" aria-hidden="true"></span>naživo</span>{/if}
                {#if first && inText(first.start)}<span class="soon">{first.line} {inText(first.start)}</span>{/if}
                <span>{rides(o).length ? transfersText(o.transfers) : 'len pešo'}</span>
                {#if o.walkM}<span>{o.walkM} m pešo</span>{/if}
              </span>
            </button>
          </li>
        {/each}
      </ul>
      {#if plan.error}<p class="note error">Obnovenie zlyhalo, ukazujeme posledné výsledky.</p>{/if}
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
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin: 10px 0 4px 22px;
  }
  .when button {
    height: 34px;
    padding: 0 12px;
    border-radius: 999px;
    background: var(--chip);
    font-weight: 600;
    font-size: 0.88rem;
  }
  .when button.active {
    background: var(--text);
    color: #fff;
  }
  .when input {
    height: 34px;
    border-radius: 8px;
    border: 1.5px solid #d4d8dd;
    padding: 0 8px;
    font: inherit;
    font-size: 16px;
    min-width: 0;
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
    border: 1.5px solid #e3e6ea;
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
  .back-list {
    color: var(--accent);
    font-weight: 600;
    padding: 4px 0;
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
    color: #fff;
  }
  .sum {
    display: flex;
    flex-direction: column;
    margin-bottom: 10px;
  }
  .big {
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
    background: var(--c, #c9ced5);
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
    border: 3px solid #fff;
    box-shadow: 0 0 0 1.5px var(--c, var(--text));
  }
  .dot.ring {
    background: #fff;
    border: 4px solid var(--c, var(--text));
    box-shadow: 0 0 0 2px #fff, 0 0 0 3.5px var(--text);
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
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    background: #e5f4ea;
    color: #0f6b37;
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
