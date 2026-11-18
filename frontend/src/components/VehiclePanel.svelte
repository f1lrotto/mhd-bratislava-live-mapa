<script lang="ts">
  import { getJson, poll } from '../lib/api'
  import { agoText, bandColor, delayText, hm, isRegional, percent, typeLabel, vehicleName } from '../lib/format'
  import { t } from '../lib/i18n'
  import { app, feedDown, navigate, regionalDown } from '../lib/state.svelte'
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
  const regional = $derived(isRegional(key))
  const name = $derived(vehicleName(key, v?.tripNo))
  const operator = $derived(regional && v?.line ? app.lines[v.line]?.operator : null)
  const serviceText = (s: ServiceState): string =>
    ({
      running: t('V prevádzke', 'In service'),
      layover: t('Na konečnej, čaká na odchod', 'At the terminus, waiting to leave'),
      depot: t('Ide do depa', 'Going to the depot'),
      parked: t('Stojí / mimo prevádzky', 'Parked / out of service'),
      unknown: t('Stav nevieme určiť', 'Status unknown'),
    })[s] ?? t('Stav nevieme určiť', 'Status unknown')
  const lv = $derived(v?.line && app.lineView?.line === v.line ? app.lineView : null)
  const dir = $derived(lv?.directions.find((d) => d.id === v?.dir) ?? null)
  const rv = $derived(dir?.vehicles.find((x) => x.key === key) ?? null)
  const unmatched = $derived(lv?.unmatched.find((u) => u.key === key) ?? null)
  // movedAgo is relative to the server's `now`; keep counting between polls.
  const movedAgo = $derived(
    v?.movedAgo != null && app.live ? v.movedAgo + (app.tick + app.skewMs - Date.parse(app.live.feed.now)) / 1000 : null,
  )

  function reason(r: string): string {
    if (regional && r === 'unknown_line') return t('Linka nie je v cestovnom poriadku IDS BK.', "The line isn't in the IDS BK timetable.")
    return (
      {
        to_depot: t('Ide do depa, preto nie je v poradí linky.', "It's going to the depot, so it isn't in the line's order."),
        no_destination: t('Vozidlo nehlási cieľ, smer nevieme určiť.', "The vehicle reports no destination, so its direction is unknown."),
        unknown_direction: t('Cieľ nepatrí žiadnemu smeru linky v cestovnom poriadku.', "The destination doesn't match any of the line's timetabled directions."),
        unknown_trip: t('Spoj nie je v cestovnom poriadku IDS BK.', "The trip isn't in the IDS BK timetable."),
        unknown_line: t('Linka nie je v cestovnom poriadku DPB.', "The line isn't in the DPB timetable."),
      }[r] ?? ''
    )
  }
</script>

<Panel label={t('Vozidlo', 'Vehicle') + ' ' + name}>
  {#snippet header()}
    {#if v?.line}<LineBadge line={v.line} size="lg" />{/if}
    <div class="head-text">
      <strong class="dest">{v ? (v.dest ? `→ ${v.dest}` : t('Bez cieľa', 'No destination')) : regional ? t('Regionálny spoj', 'Regional bus') : t(`Vozidlo ${key}`, `Vehicle ${key}`)}</strong>
      <span class="muted">{regional ? t('regionálny autobus', 'regional bus') : v ? typeLabel(v.type) : ''} {name}</span>
    </div>
  {/snippet}

  {#if !app.live}
    <p class="note">{t('Načítavam polohy…', 'Loading positions…')}</p>
  {:else if !v}
    <p class="note">
      {regional
        ? t('Spoj už skončil alebo nehlási polohu.', "The trip has ended or isn't reporting its position.")
        : t(`Vozidlo č. ${key} teraz nie je v prevádzke alebo nehlási polohu.`, `Vehicle no. ${key} isn't in service now or isn't reporting its position.`)}
    </p>
  {:else}
    <div class="facts">
      {#if running}
        <div class="fact">
          <span class="label">{t('Meškanie', 'Delay')}</span>
          <span class="value" style:color={bandColor(v.band)}>{delayText(v.delay, v.delayCapped, v.regional)}</span>
        </div>
      {:else}
        <div class="fact">
          <span class="label">{t('Stav', 'Status')}</span>
          <span class="value small-value">{serviceText(v.service)}</span>
        </div>
      {/if}
      <div class="fact">
        <span class="label">{t('Poloha zmenená', 'Last moved')}</span>
        <span class="value small-value">{agoText(movedAgo)}</span>
      </div>
    </div>

    {#if v.delayCapped && running}
      <p class="note">{t('Systém DPB nehlási viac ako 15 minút, skutočné meškanie môže byť vyššie.', "DPB's system reports at most 15 minutes, so the real delay may be longer.")}</p>
    {/if}
    {#if operator}
      <p class="muted small">{t('Dopravca', 'Operator')}: {operator}</p>
    {/if}
    {#if regional ? regionalDown() : feedDown()}
      <p class="note warn">{t('Dáta o polohe sú staré, vozidlo už môže byť inde.', 'The position data is old; the vehicle may be elsewhere by now.')}</p>
    {:else if v.stale}
      <p class="note warn">{t('Poloha sa viac ako 10 minút nezmenila. Vozidlo môže stáť alebo nehlásiť polohu.', "The position hasn't changed for over 10 minutes. The vehicle may be standing or not reporting its position.")}</p>
    {/if}

    {#if trip}
      {#if trip.passed.length}
        <button class="section passed-toggle" onclick={() => (showPassed = !showPassed)} aria-expanded={showPassed}>
          {t('Prejdené zastávky', 'Passed stops')} ({trip.passed.length}) <span aria-hidden="true">{showPassed ? '▴' : '▾'}</span>
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
                    <span class="muted" title={t('Čas prejazdu nepoznáme, podľa cestovného poriadku', 'Passing time unknown; timetabled time')}>{hm(s.scheduled)}</span>
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
        {trip.waiting ? t(`Odchod z konečnej o ${hm(trip.start)}`, `Leaves the terminus at ${hm(trip.start)}`) : t('Ďalšie zastávky', 'Next stops')}
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
          {allStops ? t('Menej zastávok', 'Fewer stops') : t(`Všetky zastávky (${trip.stops.length})`, `All stops (${trip.stops.length})`)}
        </button>
      {/if}
      {#if trip.uncertain}
        <p class="note">{t('Meškanie je 15+ min, časy môžu byť ešte neskôr.', 'The delay is 15+ min; the times may be later still.')}</p>
      {/if}
    {:else if detail && running}
      <p class="note">{t('Spoj z cestovného poriadku sme vozidlu nepriradili, ďalšie zastávky preto nevieme.', "We couldn't match the vehicle to a timetabled trip, so its next stops are unknown.")}</p>
    {/if}

    {#if dir && rv && running}
      <p class="where">
        {#if rv.offRoute}
          {t(`Mimo trasy smeru ${dir.headsign}.`, `Off the route towards ${dir.headsign}.`)}
        {:else if rv.along > dir.length - 250}
          {t('Na konečnej', 'At the terminus')} <strong>{dir.headsign}</strong>.
        {:else if rv.along < 250}
          {t('Na konečnej', 'At the terminus')} <strong>{dir.from}</strong>, {t('čaká na odchod', 'waiting to leave')}.
        {:else}
          {t('Za zastávkou', 'Past')} <strong>{dir.stops[rv.lastStop]?.name}</strong>, {t(`${percent(rv.along / dir.length)} trasy`, `${percent(rv.along / dir.length)} of the route`)}.
        {/if}
      </p>
    {:else if unmatched && !(unmatched.reason === 'to_depot' && v.service === 'depot')}
      <p class="note">{reason(unmatched.reason)}</p>
    {/if}

    {#if v.line && app.lines[v.line]}
      <button class="primary" onclick={() => navigate({ kind: 'line', line: v.line!, dir: v.dir })}>
        {t(`Celá linka ${v.line}`, `Whole line ${v.line}`)}: {regional ? t('trasa a spoje', 'route and trips') : t('poradie a medzery', 'order and gaps')}
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
    background: var(--rail);
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
    background: var(--surface);
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
