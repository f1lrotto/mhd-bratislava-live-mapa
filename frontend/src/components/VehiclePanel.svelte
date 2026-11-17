<script lang="ts">
  import { getJson, poll } from '../lib/api'
  import { agoText, bandColor, delayText, hm, TYPE_LABELS } from '../lib/format'
  import { app, feedDown, navigate } from '../lib/state.svelte'
  import type { ServiceState, VehicleDetail } from '../lib/types'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'

  let { key }: { key: string } = $props()

  let detail = $state.raw<VehicleDetail | null>(null)
  let allStops = $state(false)
  let showPassed = $state(false)
  $effect(() => {
    const k = key
    detail = null
    return poll(async () => {
      try {
        const d = await getJson<VehicleDetail>(`/api/vehicle/${encodeURIComponent(k)}`)
        if (k === key) detail = d
      } catch {
        /* unknown vehicle: the live list says so */
      }
    })
  })

  const v = $derived(app.live?.vehicles.find((x) => x.key === key) ?? detail?.vehicle ?? null)
  const trip = $derived(detail?.vehicle.key === key ? detail.trip : null)
  const nextStops = $derived(trip ? (allStops ? trip.stops : trip.stops.slice(0, 8)) : [])
  const running = $derived(v?.service === 'running')
  const SERVICE: Record<ServiceState, string> = {
    running: 'V prevádzke',
    layover: 'Na konečnej, čaká na odchod',
    depot: 'Ide do depa',
    parked: 'Stojí / mimo prevádzky',
    unknown: 'Stav nevieme určiť',
  }
  const lv = $derived(v?.line && app.lineView?.line === v.line ? app.lineView : null)
  const dir = $derived(lv?.directions.find((d) => d.id === v?.dir) ?? null)
  const rv = $derived(dir?.vehicles.find((x) => x.key === key) ?? null)
  const unmatched = $derived(lv?.unmatched.find((u) => u.key === key) ?? null)
  // movedAgo is relative to the server's `now`; keep counting between polls.
  const movedAgo = $derived(
    v?.movedAgo != null && app.live ? v.movedAgo + (app.tick + app.skewMs - Date.parse(app.live.feed.now)) / 1000 : null,
  )

  const REASONS: Record<string, string> = {
    to_depot: 'Ide do depa, preto nie je v poradí linky.',
    no_destination: 'Vozidlo nehlási cieľ, smer nevieme určiť.',
    unknown_direction: 'Cieľ nepatrí žiadnemu smeru linky v cestovnom poriadku.',
    unknown_line: 'Linka nie je v cestovnom poriadku DPB.',
  }
</script>

<Panel label="Vozidlo {key}">
  {#snippet header()}
    {#if v?.line}<LineBadge line={v.line} size="lg" />{/if}
    <div class="head-text">
      <strong class="dest">{v ? (v.dest ? `→ ${v.dest}` : 'Bez cieľa') : `Vozidlo ${key}`}</strong>
      <span class="muted">{v ? TYPE_LABELS[v.type] : ''} č. {key}</span>
    </div>
  {/snippet}

  {#if !app.live}
    <p class="note">Načítavam polohy…</p>
  {:else if !v}
    <p class="note">Vozidlo č. {key} teraz nie je v prevádzke alebo nehlási polohu.</p>
  {:else}
    <div class="facts">
      {#if running}
        <div class="fact">
          <span class="label">Meškanie</span>
          <span class="value" style:color={bandColor(v.band)}>{delayText(v.delay, v.delayCapped)}</span>
        </div>
      {:else}
        <div class="fact">
          <span class="label">Stav</span>
          <span class="value small-value">{SERVICE[v.service] ?? SERVICE.unknown}</span>
        </div>
      {/if}
      <div class="fact">
        <span class="label">Poloha zmenená</span>
        <span class="value small-value">{agoText(movedAgo)}</span>
      </div>
    </div>

    {#if v.delayCapped && running}
      <p class="note">Systém DPB nehlási viac ako 15 minút, skutočné meškanie môže byť vyššie.</p>
    {/if}
    {#if feedDown()}
      <p class="note warn">Dáta o polohe sú staré, vozidlo už môže byť inde.</p>
    {:else if v.stale}
      <p class="note warn">Poloha sa viac ako 10 minút nezmenila. Vozidlo môže stáť alebo nehlásiť polohu.</p>
    {/if}

    {#if trip}
      {#if trip.passed.length}
        <button class="section passed-toggle" onclick={() => (showPassed = !showPassed)} aria-expanded={showPassed}>
          Prejdené zastávky ({trip.passed.length}) <span aria-hidden="true">{showPassed ? '▴' : '▾'}</span>
        </button>
        {#if showPassed}
          <ol class="stops passed">
            {#each trip.passed as s (s.index)}
              <li>
                <span class="tl" aria-hidden="true"></span>
                <span class="st-time">
                  {#if s.actual && hm(s.actual) !== hm(s.scheduled)}
                    <strong>{hm(s.actual)}</strong> <s class="muted small">{hm(s.scheduled)}</s>
                  {:else if s.actual}
                    <strong>{hm(s.actual)}</strong>
                  {:else}
                    <span class="muted" title="Čas prejazdu nepoznáme, podľa cestovného poriadku">{hm(s.scheduled)}</span>
                  {/if}
                </span>
                {#if s.station}
                  <button class="st-name" onclick={() => navigate({ kind: 'station', code: s.station!, stop: s.stopId })}>
                    {s.name}{#if s.platform}<span class="muted small">&nbsp;· {s.platform}</span>{/if}
                  </button>
                {:else}
                  <span class="st-name">{s.name}</span>
                {/if}
              </li>
            {/each}
          </ol>
        {/if}
      {/if}
      <h3 class="section">
        {trip.waiting ? `Odchod z konečnej o ${hm(trip.start)}` : 'Ďalšie zastávky'}
      </h3>
      <ol class="stops">
        {#each nextStops as s (s.index)}
          {@const changed = s.predicted && hm(s.predicted) !== hm(s.scheduled)}
          <li class:end={s.arrival}>
            <span class="tl" aria-hidden="true"></span>
            <span class="st-time">
              {#if changed}
                <strong>{hm(s.predicted)}</strong> <s class="muted small">{hm(s.scheduled)}</s>
              {:else}
                <strong>{hm(s.predicted ?? s.scheduled)}</strong>
              {/if}
            </span>
            {#if s.station}
              <button class="st-name" onclick={() => navigate({ kind: 'station', code: s.station!, stop: s.stopId })}>
                {s.name}{#if s.platform}<span class="muted small">&nbsp;· {s.platform}</span>{/if}
              </button>
            {:else}
              <span class="st-name">{s.name}</span>
            {/if}
          </li>
        {/each}
      </ol>
      {#if trip.stops.length > 8}
        <button class="more" onclick={() => (allStops = !allStops)} aria-expanded={allStops}>
          {allStops ? 'Menej zastávok' : `Všetky zastávky (${trip.stops.length})`}
        </button>
      {/if}
      {#if trip.uncertain}
        <p class="note">Meškanie je 15+ min, časy môžu byť ešte neskôr.</p>
      {/if}
    {:else if detail && running}
      <p class="note">Spoj z cestovného poriadku sme vozidlu nepriradili, ďalšie zastávky preto nevieme.</p>
    {/if}

    {#if dir && rv && running}
      <p class="where">
        {#if rv.offRoute}
          Mimo trasy smeru {dir.headsign}.
        {:else if rv.along > dir.length - 250}
          Na konečnej <strong>{dir.headsign}</strong>.
        {:else if rv.along < 250}
          Na konečnej <strong>{dir.from}</strong>, čaká na odchod.
        {:else}
          Za zastávkou <strong>{dir.stops[rv.lastStop]?.name}</strong>, {Math.round((rv.along / dir.length) * 100)} % trasy.
        {/if}
      </p>
    {:else if unmatched && !(unmatched.reason === 'to_depot' && v.service === 'depot')}
      <p class="note">{REASONS[unmatched.reason] ?? ''}</p>
    {/if}

    {#if v.line && app.lines[v.line]}
      <button class="primary" onclick={() => navigate({ kind: 'line', line: v.line!, dir: v.dir })}>
        Celá linka {v.line}: poradie a medzery
      </button>
    {/if}
  {/if}
</Panel>

<style>
  .head-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
    line-height: 1.25;
  }
  .dest {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .facts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin: 4px 0 10px;
  }
  .fact {
    background: var(--chip);
    border-radius: 12px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .label {
    font-size: 0.8rem;
    color: var(--muted);
  }
  .value {
    font-size: 1.35rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .small-value {
    font-size: 1.05rem;
    padding-top: 4px;
  }
  .stops {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .stops li {
    position: relative;
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 40px;
  }
  .tl {
    position: relative;
    align-self: stretch;
    width: 14px;
    flex: none;
  }
  .tl::before {
    content: '';
    position: absolute;
    left: 5px;
    top: 0;
    bottom: 0;
    width: 4px;
    background: #c9ced5;
  }
  .stops li:first-child .tl::before {
    top: 50%;
  }
  .stops li:last-child .tl::before {
    bottom: 50%;
  }
  .tl::after {
    content: '';
    position: absolute;
    left: 2px;
    top: calc(50% - 5px);
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #fff;
    border: 2.5px solid var(--text);
    box-sizing: border-box;
  }
  .stops li.end .tl::after {
    background: var(--text);
  }
  .st-time {
    width: 4.6em;
    flex: none;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .st-name {
    flex: 1;
    min-width: 0;
    text-align: left;
    padding: 8px 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  button.st-name:hover {
    text-decoration: underline;
  }
  .passed-toggle {
    display: block;
    padding: 4px 0;
    margin-bottom: 4px;
  }
  .passed-toggle:hover {
    color: var(--text);
  }
  .stops.passed {
    color: var(--muted);
  }
  .stops.passed .tl::after {
    border-color: #9aa1ab;
    background: #9aa1ab;
  }
  .stops.passed li:last-child .tl::before {
    bottom: 0;
  }
  .more {
    color: var(--accent);
    font-weight: 600;
    padding: 8px 0;
  }
  .where {
    margin: 4px 0 14px;
    line-height: 1.4;
  }
</style>
