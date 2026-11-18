<script lang="ts">
  import { getJson } from '../lib/api'
  import { percent } from '../lib/format'
  import { count, locale, t } from '../lib/i18n'
  import { app, navigate } from '../lib/state.svelte'
  import type { LineReliability, ReliabilityDirection } from '../lib/types'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'

  let { line, dir, weekends }: { line: string; dir: string | null; weekends: boolean } = $props()

  let data = $state.raw<LineReliability | null>(null)
  let error = $state.raw<string | null>(null)
  const kind = $derived(weekends ? 'weekends' : 'workdays')

  // History only grows overnight: fetched once per line and kind of days, not polled.
  $effect(() => {
    const url = `/api/line/${encodeURIComponent(line)}/reliability?days=${kind}`
    const ctl = new AbortController()
    error = null
    getJson<LineReliability>(url, ctl.signal)
      .then((d) => (data = d))
      .catch((e) => {
        if (!ctl.signal.aborted) error = (e as Error).message
      })
    return () => ctl.abort()
  })

  const rel = $derived(data?.line === line && data.kind === kind ? data : null)
  const current = $derived(rel?.directions.find((d) => d.id === dir) ?? rel?.directions[0] ?? null)
  let metric = $state<'median' | 'p90'>('median')
  let picked = $state<{ dir: string; k: number; i: number } | null>(null)

  const dupHeadsign = (d: ReliabilityDirection) => (rel?.directions.filter((x) => x.headsign === d.headsign).length ?? 0) > 1
  const tabLabel = (d: ReliabilityDirection) => (dupHeadsign(d) ? `${d.from} → ${d.headsign}` : d.headsign)

  /** "2,4 min", "−0,3 min", "12 min" ("2.4 min" in English). */
  function mins(s: number | null | undefined): string {
    if (s == null) return '–'
    const m = s / 60
    if (Math.abs(m) < 0.05) return '0 min'
    const v = Math.abs(m) >= 10 ? String(Math.round(m)) : m.toFixed(1).replace('.', t(',', '.'))
    return `${v.replace('-', '−')} min`
  }
  const num = (n: number) => n.toLocaleString(locale())
  const trips = (n: number) => t(`${num(n)} spojov`, `${num(n)} ${n === 1 ? 'trip' : 'trips'}`)
  const departures = (n: number) => t(`${num(n)} odjazdov`, `${num(n)} ${n === 1 ? 'departure' : 'departures'}`)
  const hourText = (h: number) => `${h % 24}:00`
  /** "17. 11." / "17/11". */
  const dayText = (iso: string) => {
    const [, m, d] = iso.split('-')
    return t(`${+d}. ${+m}.`, `${+d}/${+m}`)
  }

  // Sequential scale: on time is pale green, then yellow, orange and red as the delay grows.
  // The first label, "do ½" / "under ½", is translated where the legend shows it.
  const STEPS: [number, string, string][] = [
    [30, '#d9f0d3', '½'],
    [60, '#a6dba0', '1'],
    [120, '#fee391', '2'],
    [180, '#fec44f', '3'],
    [300, '#fe9929', '5'],
    [600, '#e34a33', '10'],
    [Infinity, '#b30000', '10+'],
  ]
  const color = (s: number | null) => (s == null ? null : STEPS.find(([max]) => s < max)![1])

  const grid = $derived(current ? current[metric] : [])

  /** The cell with the biggest value of the shown metric. */
  const worst = $derived.by(() => {
    let best: { k: number; i: number; v: number } | null = null
    grid.forEach((row, k) =>
      row.forEach((v, i) => {
        if (v != null && (!best || v > best.v)) best = { k, i, v }
      }),
    )
    return best as { k: number; i: number; v: number } | null
  })

  /** Between which consecutive stops (with data) the all-day median delay grows the most. */
  const buildup = $derived.by(() => {
    if (!current) return null
    let best: { from: number; to: number; s: number } | null = null
    let prev: number | null = null
    current.stopMedian.forEach((v, k) => {
      if (v == null) return
      if (prev != null) {
        const s = v - current.stopMedian[prev]!
        if (!best || s > best.s) best = { from: prev, to: k, s }
      }
      prev = k
    })
    return best as { from: number; to: number; s: number } | null
  })

  const cell = $derived.by(() => {
    if (!current) return null
    const p = picked?.dir === current.id ? picked : worst
    if (!p) return null
    return {
      stop: current.stops[p.k],
      hour: current.hours[p.i],
      median: current.median[p.k][p.i],
      p90: current.p90[p.k][p.i],
      late: current.late[p.k][p.i],
      n: current.n[p.k][p.i],
      k: p.k,
      i: p.i,
    }
  })

  function pick(e: Event) {
    const el = (e.target as HTMLElement).closest<HTMLElement>('[data-k]')
    if (el && current) picked = { dir: current.id, k: +el.dataset.k!, i: +el.dataset.i! }
  }

  function daysText(r: LineReliability): string {
    const n = r.days.count
    const what = weekends
      ? count(n, ['víkendový deň', 'víkendové dni', 'víkendových dní'], ['weekend day', 'weekend days'])
      : count(n, ['pracovný deň', 'pracovné dni', 'pracovných dní'], ['working day', 'working days'])
    return r.days.from && r.days.to ? `${what} (${dayText(r.days.from)} – ${dayText(r.days.to)})` : what
  }

  const setDir = (id: string) => navigate({ kind: 'reliability', line, dir: id, weekends }, { replace: true })
  const setDays = (w: boolean) => navigate({ kind: 'reliability', line, dir, weekends: w }, { replace: true })
  // Opened by a deep link there's no history to go back to: back goes to the live line instead.
  const back = $derived(app.canBack ? undefined : { label: t(`Linka ${line} naživo`, `Line ${line} live`), go: () => navigate({ kind: 'line', line, dir }) })
</script>

<Panel tall label={t(`Spoľahlivosť linky ${line}`, `Line ${line} reliability`)} onback={back}>
  {#snippet header()}
    <LineBadge {line} size="lg" />
    <div class="head-text">
      <strong>{t(`Spoľahlivosť linky ${line}`, `Line ${line} reliability`)}</strong>
      <span class="muted">{t('meškanie za posledné 4 týždne', 'delays over the last 4 weeks')}</span>
    </div>
  {/snippet}

  <div class="seg" role="group" aria-label={t('Dni', 'Days')}>
    <button aria-pressed={!weekends} class:active={!weekends} onclick={() => setDays(false)}>{t('Pracovné dni', 'Working days')}</button>
    <button aria-pressed={weekends} class:active={weekends} onclick={() => setDays(true)}>{t('Víkendy', 'Weekends')}</button>
  </div>

  {#if !rel}
    {#if error}
      <p class="note error">
        {error.startsWith('unknown line')
          ? t(`Linka ${line} neexistuje.`, `Line ${line} doesn't exist.`)
          : t(`Štatistiky sa nepodarilo načítať (${error}).`, `Couldn't load the statistics (${error}).`)}
      </p>
    {:else}
      <div class="skeleton" aria-busy="true"><div></div><div></div><div></div></div>
    {/if}
  {:else if !rel.days.count}
    <p class="note">
      {weekends
        ? t('Zatiaľ nie je uložený žiadny celý víkendový deň.', 'No full weekend day has been stored yet.')
        : t('Zatiaľ nie je uložený žiadny celý pracovný deň.', 'No full working day has been stored yet.')}
      {t('Záznamy dňa sa ukladajú v noci o dva dni neskôr.', "A day's records are stored overnight two days later.")}
    </p>
  {:else if !rel.summary.trips}
    <p class="note">
      {t(`Za ${daysText(rel)} nie sú pre linku ${line} žiadne záznamy o spojoch.`, `There are no trip records for line ${line} over ${daysText(rel)}.`)}
    </p>
  {:else}
    <div class="big">
      <div class="fact">
        <span class="value">{mins(rel.summary.p90)}</span>
        <span class="label">{t('p90 meškania: 9 z 10 odjazdov meškalo menej', 'p90 delay: 9 in 10 departures were less late')}</span>
      </div>
      <div class="fact">
        <span class="value">{percent(rel.summary.lateTrips)}</span>
        <span class="label">{t('spojov meškalo 5+ min aspoň na jednej zastávke', 'of trips were 5+ min late at one stop or more')}</span>
      </div>
    </div>
    <p class="muted small basis">
      {t('Celá linka', 'Whole line')} · {daysText(rel)} · {trips(rel.summary.trips)} · {t('medián', 'median')} {mins(rel.summary.p50)}
    </p>

    {#if rel.directions.length > 1}
      <div class="tabs" class:many={rel.directions.length > 2} role="group" aria-label={t('Smer', 'Direction')}>
        {#each rel.directions as d (d.id)}
          <button aria-pressed={d.id === current?.id} class:active={d.id === current?.id} onclick={() => setDir(d.id)}>
            {#if !dupHeadsign(d)}<span class="arrow" aria-hidden="true">→</span>{/if}
            <span class="tab-name">{tabLabel(d)}</span>
          </button>
        {/each}
      </div>
    {/if}

    {#if current}
      {@const s = current.summary}
      {#if !s.trips}
        <p class="note">{t('V tomto smere nie sú za tieto dni žiadne záznamy.', 'There are no records in this direction for these days.')}</p>
      {:else}
        <p class="dir-summary">
          {t('Smer', 'Towards')} {current.headsign}: p90 <strong>{mins(s.p90)}</strong>, {t('5+ min meškalo', '')}
          <strong>{percent(s.lateTrips)}</strong>
          {t(`z ${trips(s.trips)}.`, `of ${trips(s.trips)} were 5+ min late.`)}
        </p>
        <ul class="insights">
          {#if worst && worst.v >= 60}
            <li>
              {t('Najviac mešká pri zastávke', 'Delays are worst at')} <strong>{current.stops[worst.k]}</strong>
              {t('okolo', 'around')} {hourText(current.hours[worst.i])}
              ({metric === 'median' ? t('medián', 'median') : 'p90'} {mins(worst.v)}).
            </li>
          {:else}
            <li>{t('V tomto smere jazdí linka väčšinou načas.', 'In this direction the line mostly runs on time.')}</li>
          {/if}
          {#if buildup && buildup.s >= 60}
            <li>
              {t('Meškanie najviac narastá medzi', 'The delay grows the most between')} <strong>{current.stops[buildup.from]}</strong>
              {t('a', 'and')}
              <strong>{current.stops[buildup.to]}</strong> ({t('medián', 'median')} +{mins(buildup.s)}).
            </li>
          {/if}
        </ul>

        <h3 class="section">{t('Meškanie podľa zastávky a hodiny', 'Delay by stop and hour')}</h3>
        <div class="seg small-seg" role="group" aria-label={t('Ukazovateľ', 'Measure')}>
          <button aria-pressed={metric === 'median'} class:active={metric === 'median'} onclick={() => (metric = 'median')}
            >{t('Bežný spoj (medián)', 'Typical trip (median)')}</button
          >
          <button aria-pressed={metric === 'p90'} class:active={metric === 'p90'} onclick={() => (metric = 'p90')}
            >{t('Horšie spoje (p90)', 'Worse trips (p90)')}</button
          >
        </div>
        <p class="muted small explain">
          {metric === 'median'
            ? t('Medián meškania pri odjazde zo zastávky', 'Median delay when leaving the stop')
            : t('p90 meškania: 1 z 10 spojov meškal viac', 'p90 delay: 1 in 10 trips was later')}{t(
            ', podľa hodiny v cestovnom poriadku. Ťuknite na políčko.',
            ', by timetabled hour. Tap a cell.',
          )}
        </p>

        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
        <div
          class="heat"
          style:grid-template-columns="minmax(0, 1fr) repeat({current.hours.length}, minmax(0, 12px))"
          onclick={pick}
          onpointerover={(e) => e.pointerType === 'mouse' && pick(e)}
          role="img"
          aria-label={t(
            `Mapa meškania smeru ${current.headsign}: zastávky v riadkoch, hodiny v stĺpcoch`,
            `Delay map towards ${current.headsign}: stops in rows, hours in columns`,
          )}
        >
          <span></span>
          {#each current.hours as h, i (i)}
            <span class="hour">{h % 3 === 0 ? h % 24 : ''}</span>
          {/each}
          {#each current.stops as name, k (k)}
            <span class="stop" class:on={cell?.k === k}>{name}</span>
            {#each grid[k] as v, i (i)}
              <span
                class="cell"
                class:empty={v == null}
                class:sel={cell?.k === k && cell?.i === i}
                style:background={color(v)}
                data-k={k}
                data-i={i}
              ></span>
            {/each}
          {/each}
        </div>

        {#if cell}
          <div class="detail" aria-live="polite">
            <strong>{cell.stop}</strong>
            <span class="muted">{hourText(cell.hour)}–{hourText(cell.hour + 1)}</span>
            {#if cell.median != null}
              <span>{t('medián', 'median')} <b>{mins(cell.median)}</b> · p90 <b>{mins(cell.p90)}</b> · 5+ min {percent(cell.late)}</span>
              <span class="muted small">{departures(cell.n ?? 0)}</span>
            {:else}
              <span class="muted"
                >{cell.n
                  ? t(`len ${cell.n} odjazdov, málo na štatistiku`, `only ${departures(cell.n)}, too few for statistics`)
                  : t('žiadne spoje', 'no trips')}</span
              >
            {/if}
          </div>
        {/if}

        <div class="legend" aria-hidden="true">
          {#each STEPS as [, c, label], i (label)}
            <span class="key"><span class="swatch" style:background={c}></span>{i === 0 ? t('do ½', 'under ½') : label}</span>
          {/each}
          <span class="muted">min</span>
        </div>
      {/if}
    {/if}
  {/if}
</Panel>

<style>
  .head-text {
    display: flex;
    flex-direction: column;
    line-height: 1.2;
  }
  .seg {
    display: flex;
    gap: 4px;
    padding: 3px;
    border-radius: 10px;
    background: var(--chip);
    margin: 2px 0 12px;
  }
  .seg button {
    flex: 1;
    padding: 7px 10px;
    border-radius: 8px;
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--muted);
  }
  .seg button.active {
    background: var(--surface);
    color: var(--text);
    box-shadow: var(--shadow-sm);
  }
  .small-seg {
    margin: 0;
  }
  .small-seg button {
    padding: 5px 8px;
    font-size: 0.82rem;
  }
  .big {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .fact {
    background: var(--chip);
    border-radius: 12px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
  }
  .value {
    font-size: 1.6rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .label {
    font-size: 0.8rem;
    color: var(--muted);
    line-height: 1.3;
  }
  .basis {
    margin: 8px 0 14px;
  }
  .tabs {
    display: flex;
    gap: 6px;
    margin: 0 0 10px;
  }
  .tabs.many {
    flex-wrap: wrap;
  }
  .tabs.many button {
    flex: 1 1 calc(50% - 3px);
  }
  .tabs.many .tab-name {
    white-space: normal;
    line-height: 1.2;
  }
  .tabs button {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 9px 10px;
    border-radius: 10px;
    background: var(--chip);
    font-size: 0.9rem;
    text-align: left;
  }
  .tabs button.active {
    background: var(--text);
    color: var(--on-text);
  }
  .tab-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 600;
  }
  .dir-summary {
    margin: 0 0 6px;
    font-size: 0.95rem;
  }
  .insights {
    margin: 0;
    padding-left: 18px;
    font-size: 0.9rem;
    line-height: 1.45;
  }
  .explain {
    margin: 6px 0 8px;
    line-height: 1.35;
  }
  .heat {
    display: grid;
    gap: 1px;
    align-items: center;
    cursor: pointer;
    user-select: none;
  }
  .hour {
    font-size: 10px;
    color: var(--muted);
    text-align: center;
    overflow: visible;
    white-space: nowrap;
  }
  .stop {
    font-size: 11px;
    line-height: 15px;
    padding-right: 6px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted);
  }
  .stop.on {
    color: var(--text);
    font-weight: 700;
  }
  .cell {
    height: 15px;
    border-radius: 2px;
  }
  .cell.empty {
    background: var(--chip);
  }
  .cell.sel {
    outline: 2px solid var(--text);
    outline-offset: 0;
    position: relative;
  }
  .detail {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 2px 8px;
    margin: 10px 0 4px;
    padding: 8px 10px;
    border-radius: 10px;
    background: var(--chip);
    font-size: 0.88rem;
    font-variant-numeric: tabular-nums;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 10px;
    margin-top: 8px;
    font-size: 0.75rem;
  }
  .key {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .swatch {
    width: 12px;
    height: 12px;
    border-radius: 2px;
  }
  .skeleton div {
    height: 18px;
    border-radius: 6px;
    background: var(--chip);
    margin: 10px 0;
    animation: pulse 1.2s ease-in-out infinite;
  }
  .skeleton div:nth-child(2) {
    width: 70%;
  }
  @keyframes pulse {
    50% {
      opacity: 0.5;
    }
  }
</style>
