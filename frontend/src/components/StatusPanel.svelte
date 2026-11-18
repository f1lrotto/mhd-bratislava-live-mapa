<script lang="ts">
  import { delayText, percent, typePlural } from '../lib/format'
  import { t } from '../lib/i18n'
  import { app, navigate } from '../lib/state.svelte'
  import type { VehicleType } from '../lib/types'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'

  const st = $derived(app.status)
  const pct = percent

  // Chart geometry: a gutter on the left for the % labels, room above the plot for the value label.
  const W = 300
  const L = 30
  const R = 10
  const T = 14
  const H = 90
  const bottom = T + H
  const x = (b: number) => L + (b / 144) * (W - L - R)
  const y = (v: number) => bottom - (v / maxShare) * H

  // Round up to the next 10 % above the data, so the curve never touches the top edge.
  const maxShare = $derived(
    Math.ceil(
      Math.max(
        0.1,
        ...Object.values(st?.history?.today ?? {}),
        ...Object.values(st?.history?.todayDelayed ?? {}),
        ...Object.values(st?.history?.baseline ?? {}),
      ) *
        10 +
        0.1,
    ) / 10,
  )
  const yTicks = $derived.by(() => {
    const step = maxShare > 0.5 ? 0.2 : 0.1
    return Array.from({ length: Math.floor(maxShare / step + 1e-9) + 1 }, (_, i) => +(i * step).toFixed(1))
  })

  /** Runs of consecutive buckets as [x, y] points; a gap in the logs breaks the line. */
  function runs(curve: Record<string, number> | null | undefined): [number, number][][] {
    const out: [number, number][][] = []
    let prev = -2
    for (const [b, v] of Object.entries(curve ?? {})
      .map(([b, v]) => [+b, v] as const)
      .sort((a, b) => a[0] - b[0])) {
      if (b !== prev + 1) out.push([])
      out.at(-1)!.push([x(b), y(v)])
      prev = b
    }
    return out
  }
  const line = (r: [number, number][]) => 'M' + r.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join('L')
  const area = (r: [number, number][]) => `${line(r)}V${bottom}H${r[0][0].toFixed(1)}Z`

  const todayRuns = $derived(runs(st?.history?.today))
  const delayedRuns = $derived(runs(st?.history?.todayDelayed))
  const baseRuns = $derived(runs(st?.history?.baseline))
  function lastOf(curve: Record<string, number> | undefined) {
    const b = Math.max(...Object.keys(curve ?? {}).map(Number))
    return Number.isFinite(b) ? { x: x(b), y: y(curve![b]), v: curve![b] } : null
  }
  const last = $derived(lastOf(st?.history?.today))
  const lastDelayed = $derived(lastOf(st?.history?.todayDelayed))
  // The 2+ min curve is never below the 5+ one. Both labels stay above both dots: when the two are
  // close, the 5+ label moves up above the 2+ dot and the 2+ label stacks above it.
  const lateLabelY = $derived(
    last && lastDelayed && last.y - lastDelayed.y < 18 ? lastDelayed.y - 7 : (last?.y ?? 0) - 7,
  )
  const delayedLabelY = $derived(Math.min((lastDelayed?.y ?? 0) - 7, last ? lateLabelY - 13 : Infinity))
  const labelX = (px: number) => Math.min(Math.max(px, L + 12), W - R - 12)
</script>

<Panel tall label={t('Stav dopravy', 'Service status')}>
  {#snippet header()}
    <strong>{t('Stav dopravy v meste', 'Service status in the city')}</strong>
  {/snippet}

  {#if !st}
    <p class="note">{t('Načítavam…', 'Loading…')}</p>
  {:else}
    <div class="big">
      <div class="fact">
        <span class="value">{pct(st.shareLate)}</span>
        <span class="label">{t('vozidiel mešká 5+ min', 'of vehicles 5+ min late')}</span>
      </div>
      <div class="fact">
        <span class="value">{st.vehicles}</span>
        <span class="label">{t('vozidiel v prevádzke', 'vehicles in service')}</span>
      </div>
    </div>
    <div class="types">
      {#each ['tram', 'trolleybus', 'bus'] as VehicleType[] as ty (ty)}
        <span>{typePlural(ty)} <strong>{st.byType[ty] ?? 0}</strong></span>
      {/each}
    </div>

    <h3 class="section">{t('Najhoršie linky teraz', 'Worst lines now')}</h3>
    {#if st.worst.length}
      <ol class="worst">
        {#each st.worst as w (w.line)}
          <li>
            <button class="row" onclick={() => navigate({ kind: 'line', line: w.line, dir: null })}>
              <LineBadge line={w.line} />
              <span class="grow">{t('medián', 'median')} {delayText(w.medianDelay)}</span>
              <span class="muted small">{t(`${w.vehicles} voz. · ${pct(w.shareLate)} mešká`, `${w.vehicles} veh. · ${pct(w.shareLate)} late`)}</span>
            </button>
          </li>
        {/each}
      </ol>
    {:else}
      <p class="note">{t('Žiadna linka s aspoň 3 vozidlami nemešká.', 'No line with at least 3 vehicles is running late.')}</p>
    {/if}

    <h3 class="section">{t('Podiel meškajúcich počas dňa', 'Share running late through the day')}</h3>
    {#if st.history && Object.keys(st.history.today).length >= 6}
      <svg
        class="chart"
        viewBox="0 0 {W} {bottom + 16}"
        role="img"
        aria-label={t(
          `Podiel spojov meškajúcich dnes, naposledy ${pct(lastDelayed?.v)} 2+ min a ${pct(last?.v)} 5+ min`,
          `Share of trips running late today, latest ${pct(lastDelayed?.v)} 2+ min and ${pct(last?.v)} 5+ min`,
        )}
      >
        {#each yTicks as v (v)}
          <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} class:axis={v === 0} class="grid" />
          <text x={L - 5} y={y(v) + 3.5} text-anchor="end">{pct(v)}</text>
        {/each}
        {#each [0, 6, 12, 18, 24] as h (h)}
          <text x={x(h * 6)} y={bottom + 13} text-anchor={h === 0 ? 'start' : h === 24 ? 'end' : 'middle'}>{h}:00</text>
        {/each}
        {#each todayRuns as r, i (i)}<path d={area(r)} class="fill" />{/each}
        {#each baseRuns as r, i (i)}<path d={line(r)} class="base" />{/each}
        {#each delayedRuns as r, i (i)}<path d={line(r)} class="delayed" />{/each}
        {#each todayRuns as r, i (i)}<path d={line(r)} class="today" />{/each}
        {#if lastDelayed}
          <text x={labelX(lastDelayed.x)} y={delayedLabelY} text-anchor="middle" class="value-label delayed-label">
            {pct(lastDelayed.v)}
          </text>
          <circle cx={lastDelayed.x} cy={lastDelayed.y} r="3" class="dot delayed-dot" />
        {/if}
        {#if last}
          <text x={labelX(last.x)} y={lateLabelY} text-anchor="middle" class="value-label">{pct(last.v)}</text>
          <circle cx={last.x} cy={last.y} r="3" class="dot" />
        {/if}
      </svg>
      <p class="legend">
        <span class="key delayed-key"></span> 2+ min
        <span class="key today-key"></span> 5+ min
        {#if st.history.baseline}<span class="key base-key"></span> {t('5+ min v bežný deň (medián 4 rovnakých dní)', '5+ min on a usual day (median of the same 4 weekdays)')}{/if}
      </p>
    {:else}
      <p class="note">{t('Graf sa zobrazí, keď sa nazbiera aspoň hodina záznamov.', 'The chart shows once at least an hour of records has been collected.')}</p>
    {/if}
    {#if st.history && !st.history.baseline}
      <p class="note">{t('Porovnanie s bežným dňom bude dostupné po štyroch týždňoch záznamov.', 'A comparison with a usual day will be available after four weeks of records.')}</p>
    {/if}
  {/if}
</Panel>

<style>
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
  }
  .types {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    margin: 10px 0 4px;
    font-size: 0.9rem;
    color: var(--muted);
  }
  .types strong {
    color: var(--text);
  }
  .worst {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 12px;
    width: calc(100% + 16px);
    margin: 0 -8px;
    padding: 8px;
    border-radius: 10px;
    text-align: left;
    min-height: 48px;
  }
  .row:hover {
    background: var(--hover);
  }
  .grow {
    flex: 1;
    font-weight: 600;
  }
  .chart {
    width: 100%;
    height: auto;
    overflow: visible;
  }
  .chart text {
    font-size: 10px;
    fill: var(--muted);
  }
  .chart .value-label {
    font-size: 11px;
    font-weight: 700;
    fill: var(--accent);
    paint-order: stroke;
    stroke: var(--surface);
    stroke-width: 3px;
  }
  .grid {
    stroke: #eceef1;
  }
  .grid.axis {
    stroke: #d3d7dc;
  }
  .fill {
    fill: var(--accent);
    opacity: 0.12;
  }
  .today {
    fill: none;
    stroke: var(--accent);
    stroke-width: 2;
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .dot {
    fill: var(--accent);
  }
  .delayed {
    fill: none;
    stroke: var(--warn);
    stroke-width: 1.5;
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .dot.delayed-dot {
    fill: var(--warn);
  }
  .chart .delayed-label {
    fill: var(--warn-text);
  }
  .base {
    fill: none;
    stroke: #8d95a0;
    stroke-width: 1.5;
    stroke-dasharray: 4 3;
  }
  .legend {
    font-size: 0.8rem;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .key {
    display: inline-block;
    width: 16px;
    height: 0;
    border-top: 2px solid var(--accent);
  }
  .delayed-key {
    border-top-color: var(--warn);
  }
  .today-key,
  .base-key {
    margin-left: 8px;
  }
  .base-key {
    border-top: 2px dashed #8d95a0;
  }
</style>
