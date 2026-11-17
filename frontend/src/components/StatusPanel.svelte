<script lang="ts">
  import { delayText, TYPE_PLURAL } from '../lib/format'
  import { app, navigate } from '../lib/state.svelte'
  import type { VehicleType } from '../lib/types'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'

  const st = $derived(app.status)
  const pct = (x: number | null | undefined) => (x == null ? '–' : `${Math.round(x * 100)} %`)

  const W = 300
  const H = 90
  function path(curve: Record<string, number> | null | undefined, max: number): string {
    if (!curve) return ''
    const pts = Object.entries(curve)
      .map(([b, v]) => [+b, v] as const)
      .sort((a, b) => a[0] - b[0])
    let d = ''
    let prev = -2
    for (const [b, v] of pts) {
      const x = (b / 144) * W
      const y = H - (v / max) * H
      d += `${b === prev + 1 ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`
      prev = b
    }
    return d
  }
  const maxShare = $derived(
    Math.max(0.2, ...Object.values(st?.history?.today ?? {}), ...Object.values(st?.history?.baseline ?? {})),
  )
</script>

<Panel tall label="Stav dopravy">
  {#snippet header()}
    <strong>Stav dopravy v meste</strong>
  {/snippet}

  {#if !st}
    <p class="note">Načítavam…</p>
  {:else}
    <div class="big">
      <div class="fact">
        <span class="value">{pct(st.shareLate)}</span>
        <span class="label">vozidiel mešká 5+ min</span>
      </div>
      <div class="fact">
        <span class="value">{st.vehicles}</span>
        <span class="label">vozidiel v prevádzke</span>
      </div>
    </div>
    <div class="types">
      {#each ['tram', 'trolleybus', 'bus'] as VehicleType[] as t (t)}
        <span>{TYPE_PLURAL[t]} <strong>{st.byType[t] ?? 0}</strong></span>
      {/each}
    </div>

    <h3 class="section">Najhoršie linky teraz</h3>
    {#if st.worst.length}
      <ol class="worst">
        {#each st.worst as w (w.line)}
          <li>
            <button class="row" onclick={() => navigate({ kind: 'line', line: w.line, dir: null })}>
              <LineBadge line={w.line} />
              <span class="grow">medián {delayText(w.medianDelay)}</span>
              <span class="muted small">{w.vehicles} voz. · {pct(w.shareLate)} mešká</span>
            </button>
          </li>
        {/each}
      </ol>
    {:else}
      <p class="note">Žiadna linka s aspoň 3 vozidlami nemešká.</p>
    {/if}

    <h3 class="section">Podiel meškajúcich počas dňa</h3>
    {#if st.history && Object.keys(st.history.today).length > 1}
      <svg class="chart" viewBox="0 0 {W} {H + 16}" role="img" aria-label="Podiel meškajúcich vozidiel dnes">
        {#each [6, 12, 18] as h (h)}
          <line x1={(h / 24) * W} x2={(h / 24) * W} y1="0" y2={H} class="grid" />
          <text x={(h / 24) * W} y={H + 13} text-anchor="middle">{h}:00</text>
        {/each}
        <path d={path(st.history.baseline, maxShare)} class="base" />
        <path d={path(st.history.today, maxShare)} class="today" />
      </svg>
      <p class="legend">
        <span class="key today-key"></span> dnes
        {#if st.history.baseline}<span class="key base-key"></span> bežný deň (medián 4 rovnakých dní){/if}
      </p>
    {:else}
      <p class="note">Graf sa zobrazí, keď sa nazbiera aspoň hodina záznamov.</p>
    {/if}
    {#if st.history && !st.history.baseline}
      <p class="note">Porovnanie s bežným dňom bude dostupné po štyroch týždňoch záznamov.</p>
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
  .grid {
    stroke: #e3e6ea;
  }
  .today {
    fill: none;
    stroke: var(--accent);
    stroke-width: 2;
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
  .base-key {
    border-top: 2px dashed #8d95a0;
    margin-left: 8px;
  }
</style>
