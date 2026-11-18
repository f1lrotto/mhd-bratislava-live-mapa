<script lang="ts">
  import { untrack } from 'svelte'
  import { poll, reachQuery, refreshReach } from '../lib/api'
  import { hm } from '../lib/format'
  import { placeLabel, pointValue, setPlanEnd } from '../lib/places'
  import { REACH_COLORS, REACH_LIMITS, reachBands, reachShapes } from '../lib/reach'
  import { app, navigate, SLOW_POLL_MS } from '../lib/state.svelte'
  import DepartPicker from './DepartPicker.svelte'
  import Panel from './Panel.svelte'
  import PlaceInput from './PlaceInput.svelte'

  let { from, at, min }: { from: string | null; at: string | null; min: number } = $props()

  const query = $derived(reachQuery(from, at, min))
  const reach = $derived(app.reach && app.reach.query === query ? app.reach : null)
  const bands = $derived(reachBands(min))
  // Contoured here only for the areas; the map draws its own copy of the same shapes.
  const areas = $derived(reach?.data ? reachShapes(reach.data, bands).areas : null)
  const now = $derived(app.tick + app.skewMs)

  // Departing now: refresh every 30 s while open, as "now" moves on and delays change. A fixed
  // time is fetched once.
  $effect(() => {
    const q = query
    if (!q) return
    if (at) {
      untrack(() => {
        if (app.reach?.query !== q || app.reach.error) refreshReach(q)
      })
      return
    }
    return untrack(() => poll(() => refreshReach(q), SLOW_POLL_MS))
  })

  let fromInput = $state<HTMLInputElement>()
  $effect(() => {
    if (!untrack(() => from)) fromInput?.focus()
  })

  function set(v: Partial<{ from: string | null; at: string | null; min: number }>) {
    navigate({ kind: 'reach', from, at, min, ...v }, { replace: true })
  }

  let geoError = $state<string | null>(null)
  let geoBusy = $state(false)
  function locate() {
    geoError = null
    if (!navigator.geolocation) {
      geoError = 'Tento prehliadač polohu nepodporuje.'
      return
    }
    geoBusy = true
    navigator.geolocation.getCurrentPosition(
      (p) => {
        geoBusy = false
        setPlanEnd('from', pointValue(p.coords.latitude, p.coords.longitude), 'Moja poloha')
      },
      (e) => {
        geoBusy = false
        geoError = e.code === e.PERMISSION_DENIED ? 'Prístup k polohe je zakázaný.' : 'Polohu sa nepodarilo zistiť.'
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 },
    )
  }

  let pickerOpen = $state(false)

  const errorText = (e: string) =>
    /unknown station/.test(e) ? 'Zastávku sme nenašli. Vyberte ju znova.' : `Dostupnosť sa nepodarilo vypočítať (${e}).`
  const areaText = (km2: number) => (km2 < 10 ? km2.toFixed(1).replace('.', ',') : String(Math.round(km2)))
</script>

<Panel tall label="Dostupnosť" expand={pickerOpen}>
  {#snippet header()}
    <svg class="head-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="2" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="10" /></svg>
    <strong>Kam sa dostanem</strong>
  {/snippet}

  <PlaceInput end="from" label="Odkiaľ" value={from} bind:input={fromInput} onpick={(c) => set({ from: c })} onlocate={locate} onmap={() => (app.pick = app.pick === 'from' ? null : 'from')} />
  {#if geoBusy}<p class="note">Zisťujem polohu…</p>{/if}
  {#if geoError}<p class="note error">{geoError}</p>{/if}

  <div class="when">
    <DepartPicker {at} {now} bind:open={pickerOpen} onchange={(v) => set({ at: v })} />
  </div>

  <div class="chips-row" role="group" aria-label="Najviac">
    <span class="muted small">najviac</span>
    {#each REACH_LIMITS as m (m)}
      <button class:active={min === m} aria-pressed={min === m} onclick={() => set({ min: m })}>{m} min</button>
    {/each}
  </div>

  {#if !from}
    <p class="note">Zadajte zastávku, svoju polohu alebo ťuknite na mapu. Ukážeme, kam sa odtiaľ dostanete MHD a pešo.</p>
  {:else if !reach || (reach.loading && !reach.data)}
    <div class="skeleton" aria-busy="true"><div></div></div>
  {:else if reach.error && !reach.data}
    <p class="note error">{errorText(reach.error)}</p>
  {:else if reach.data && areas}
    <ul class="legend" aria-label="Kam sa dostanete">
      {#each bands as b, i (b)}
        <li>
          <span class="swatch" style:--c={REACH_COLORS[i]} aria-hidden="true"></span>
          <span><strong>do {b} min</strong> <span class="muted">· {areaText(areas[i])} km²</span></span>
        </li>
      {/each}
    </ul>
    <p class="note">
      Z miesta {placeLabel(from)} {at ? `o ${hm(at)}` : 'teraz'}{reach.data.live ? ', s aktuálnym meškaním' : ''}: pešo
      k zastávke, MHD s prestupmi a pešo k cieľu (najviac 2 km vzdušnou čiarou).
    </p>
    <p class="note">Ťuknite na zvýraznenú zastávku a ukážeme vám spojenie k nej. Inde na mape začnete odtiaľ.</p>
    {#if reach.error}<p class="note error">Obnovenie zlyhalo, ukazujeme posledný výsledok.</p>{/if}
  {/if}
</Panel>

<style>
  .head-icon {
    width: 24px;
    height: 24px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
  }
  .chips-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin: 10px 0 4px;
  }
  .chips-row button {
    height: 34px;
    padding: 0 12px;
    border-radius: 999px;
    background: var(--chip);
    font-weight: 600;
    font-size: 0.88rem;
  }
  .chips-row button.active {
    background: var(--text);
    color: #fff;
  }
  .when {
    margin: 10px 0 4px;
  }
  .legend {
    list-style: none;
    margin: 14px 0 6px;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .legend li {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .swatch {
    width: 22px;
    height: 16px;
    border-radius: 4px;
    background: var(--c);
    opacity: 0.75;
  }
  .skeleton div {
    height: 110px;
    border-radius: 12px;
    background: var(--chip);
    margin: 14px 0;
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse {
    50% {
      opacity: 0.5;
    }
  }
</style>
