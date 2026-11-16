<script lang="ts">
  import { bandColor, delayBand, delayText, minutes, plural, TYPE_LABELS } from '../lib/format'
  import { app, navigate } from '../lib/state.svelte'
  import type { LineDirection, RibbonVehicle } from '../lib/types'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'

  let { line, dir }: { line: string; dir: string | null } = $props()

  const lv = $derived(app.lineView?.line === line ? app.lineView : null)
  const info = $derived(app.lines[line])
  const current = $derived(lv?.directions.find((d) => d.id === dir) ?? lv?.directions[0] ?? null)
  // Off-route vehicles have no meaningful position on the route; list them after the running ones.
  const ordered = $derived(current ? [...current.vehicles.filter((v) => !v.offRoute), ...current.vehicles.filter((v) => v.offRoute)] : [])
  const AT_END_M = 250
  const dupHeadsign = (d: LineDirection) => (lv?.directions.filter((x) => x.headsign === d.headsign).length ?? 0) > 1
  const tabLabel = (d: LineDirection) => (dupHeadsign(d) ? `${d.from} → ${d.headsign}` : d.headsign)
  // Dots closer than this share of the ribbon would overlap; lift the later one so both show.
  const lifted = $derived.by(() => {
    const out = new Set<string>()
    if (!current) return out
    const run = current.vehicles.filter((v) => !v.offRoute)
    for (let i = 1; i < run.length; i++) {
      if (!out.has(run[i - 1].key) && pct(current, run[i].along) - pct(current, run[i - 1].along) < 4) out.add(run[i].key)
    }
    return out
  })

  function pct(d: LineDirection, along: number): number {
    return Math.min(100, Math.max(0, (along / Math.max(1, d.length)) * 100))
  }

  function where(d: LineDirection, v: RibbonVehicle): string {
    if (v.offRoute) return 'mimo trasy'
    if (v.along < AT_END_M) return `na konečnej ${d.from}`
    if (v.along > d.length - AT_END_M) return `na konečnej ${d.headsign}`
    return `za zastávkou ${d.stops[v.lastStop]?.name ?? ''}`
  }

  function summary(d: LineDirection): string {
    const s = d.summary
    const parts = [plural(s.count, 'vozidlo', 'vozidlá', 'vozidiel') + ` smer ${d.headsign}`]
    if (s.medianDelay != null)
      parts.push(s.medianDelay < 60 ? 'väčšinou načas' : `medián meškania ${delayText(s.medianDelay)}`)
    if (s.biggestGap) {
      const g = s.biggestGap
      parts.push(
        g.fromStop && g.fromStop !== g.afterStop
          ? `medzera ≈${minutes(g.s)} medzi ${g.fromStop} a ${g.afterStop}`
          : `medzera ≈${minutes(g.s)} pri zastávke ${g.afterStop}`,
      )
    }
    else if (s.bunched) parts.push(s.bunched === 1 ? 'dve vozidlá idú tesne za sebou' : `${s.bunched}× vozidlá tesne za sebou`)
    return parts.join(', ')
  }

  function openVehicle(key: string) {
    navigate({ kind: 'vehicle', key })
  }

  const UNMATCHED: Record<string, string> = {
    to_depot: 'do depa',
    no_destination: 'bez cieľa',
    unknown_direction: 'neznámy smer',
    unknown_line: 'linka nie je v cestovnom poriadku',
  }
</script>

<Panel tall label="Linka {line}">
  {#snippet header()}
    <LineBadge {line} size="lg" />
    <div class="head-text">
      <strong>Linka {line}</strong>
      <span class="muted">{info ? TYPE_LABELS[info.type] : ''}</span>
    </div>
  {/snippet}

  {#if !lv}
    {#if app.lineViewError}
      <p class="note error">
        {app.lineViewError.startsWith('unknown line') ? `Linka ${line} neexistuje.` : `Linku sa nepodarilo načítať (${app.lineViewError}).`}
      </p>
    {:else}
      <div class="skeleton" aria-busy="true">
        <div></div>
        <div></div>
        <div></div>
      </div>
    {/if}
  {:else if !current}
    <p class="note">Linka {line} nemá v cestovnom poriadku žiadnu trasu.</p>
  {:else}
    {#if lv.directions.length > 1}
      <div class="tabs" class:many={lv.directions.length > 2} role="group" aria-label="Smer">
        {#each lv.directions as d (d.id)}
          <button
            aria-pressed={d.id === current.id}
            class:active={d.id === current.id}
            onclick={() => navigate({ kind: 'line', line, dir: d.id }, { replace: true })}
          >
            {#if !dupHeadsign(d)}<span class="arrow" aria-hidden="true">→</span>{/if}
            <span class="tab-name">{tabLabel(d)}</span>
            <span class="count">{d.summary.count}</span>
          </button>
        {/each}
      </div>
    {/if}

    <p class="summary">{summary(current)}.</p>
    <p class="interval">
      {#if current.interval}
        Podľa cestovného poriadku teraz každých <strong class="nowrap">{minutes(current.interval)}</strong>
      {:else}
        Podľa cestovného poriadku teraz nepremáva
      {/if}
    </p>

    <div class="ribbon" aria-hidden="true">
      <div class="track" style:background={lv.color}></div>
      {#each current.stops as s, i (i)}
        <div class="tick" class:end={i === 0 || i === current.stops.length - 1} style:left="{pct(current, s.dist)}%"></div>
      {/each}
      {#each current.vehicles as v, i (v.key)}
        {#if v.gapAhead?.flag && current.vehicles[i + 1]}
          <div
            class="seg {v.gapAhead.flag}"
            style:left="{pct(current, v.along)}%"
            style:width="{pct(current, current.vehicles[i + 1].along) - pct(current, v.along)}%"
          ></div>
        {/if}
      {/each}
      {#each current.vehicles.filter((v) => !v.offRoute) as v (v.key)}
        <button
          class="dot"
          class:stale={v.stale}
          class:lift={lifted.has(v.key)}
          style:left="{pct(current, v.along)}%"
          style:background={v.stale ? 'var(--stale)' : bandColor(delayBand(v.delay))}
          tabindex="-1"
          aria-label="Vozidlo {v.key}"
          onclick={() => openVehicle(v.key)}
        ></button>
      {/each}
    </div>
    <div class="ends">
      <span>{current.from}</span>
      <span>{current.headsign}</span>
    </div>

    {#if ordered.length}
      <h3 class="section">Poradie vozidiel od začiatku trasy</h3>
      <ol class="order">
        {#each ordered as v, i (v.key)}
          <li>
            <button class="row" onclick={() => openVehicle(v.key)}>
              <span class="pip" style:background={v.stale ? 'var(--stale)' : bandColor(delayBand(v.delay))}></span>
              <span class="row-main">
                <span class="where">{where(current, v)}</span>
                <span class="muted small">č. {v.key}{v.stale ? ' · poloha sa nemení' : ''}</span>
              </span>
              <span class="delay" class:late={(v.delay ?? 0) >= 180}>{delayText(v.delay)}</span>
            </button>
            {#if v.gapAhead && i < ordered.length - 1}
              <div class="between {v.gapAhead.flag ?? ''}">
                <span class="gap-line" aria-hidden="true"></span>
                {#if v.gapAhead.s != null}≈{minutes(v.gapAhead.s)}{/if}
                <span class="muted">· {(v.gapAhead.m / 1000).toFixed(1).replace('.', ',')} km</span>
                {#if v.gapAhead.flag === 'gap'}<span class="flag">medzera</span>{/if}
                {#if v.gapAhead.flag === 'bunched'}<span class="flag">tesne za sebou</span>{/if}
              </div>
            {/if}
          </li>
        {/each}
      </ol>
    {:else}
      <p class="note">V tomto smere teraz nejde žiadne vozidlo.</p>
    {/if}

    {#if lv.unmatched.length}
      <h3 class="section">Mimo poradia</h3>
      <ul class="unmatched">
        {#each lv.unmatched as u (u.key)}
          <li>
            <button class="row" onclick={() => openVehicle(u.key)}>
              <span class="row-main"
                ><span>č. {u.key}</span><span class="muted small">{u.dest ?? 'bez cieľa'} · {UNMATCHED[u.reason] ?? u.reason}</span></span
              >
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</Panel>

<style>
  .head-text {
    display: flex;
    flex-direction: column;
    line-height: 1.2;
  }
  .tabs {
    display: flex;
    gap: 6px;
    margin: 2px 0 12px;
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
    color: #fff;
  }
  .tab-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 600;
  }
  .count {
    font-variant-numeric: tabular-nums;
    opacity: 0.75;
    font-size: 0.8rem;
  }
  .summary {
    margin: 0 0 4px;
    font-size: 1rem;
    line-height: 1.4;
    font-weight: 600;
  }
  .interval {
    margin: 0 0 14px;
    color: var(--muted);
    font-size: 0.9rem;
  }
  .interval strong {
    color: var(--text);
  }
  .ribbon {
    position: relative;
    height: 40px;
    margin: 0 9px;
  }
  .track {
    position: absolute;
    left: 0;
    right: 0;
    top: 21px;
    height: 4px;
    border-radius: 2px;
    opacity: 0.45;
  }
  .tick {
    position: absolute;
    top: 19px;
    width: 2px;
    height: 8px;
    margin-left: -1px;
    background: #8d95a0;
    border-radius: 1px;
  }
  .tick.end {
    top: 16px;
    height: 14px;
    width: 3px;
    background: var(--text);
  }
  .nowrap {
    white-space: nowrap;
  }
  .seg {
    min-width: 10px;
    position: absolute;
    top: 20px;
    height: 6px;
    border-radius: 3px;
  }
  .seg.gap {
    background: var(--bad);
  }
  .seg.bunched {
    background: var(--warn);
  }
  .dot {
    position: absolute;
    top: 14px;
    width: 18px;
    height: 18px;
    margin-left: -9px;
    border-radius: 50%;
    border: 2.5px solid #fff;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
    padding: 0;
  }
  .dot.lift {
    top: -4px;
    box-shadow: 0 0 0 2px var(--warn), 0 1px 3px rgba(0, 0, 0, 0.35);
  }
  .ends {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    font-size: 0.8rem;
    color: var(--muted);
    margin-bottom: 8px;
  }
  .ends span:last-child {
    text-align: right;
  }
  .order,
  .unmatched {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .row {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 9px 8px;
    margin: 0 -8px;
    width: calc(100% + 16px);
    border-radius: 10px;
    text-align: left;
    min-height: 48px;
  }
  .row:hover {
    background: var(--hover);
  }
  .pip {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    flex: none;
  }
  .row-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .where {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .delay {
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    white-space: nowrap;
  }
  .delay.late {
    color: var(--bad-text);
  }
  .between {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 2px 0 2px 1px;
    font-size: 0.85rem;
    font-variant-numeric: tabular-nums;
  }
  .gap-line {
    width: 2px;
    height: 20px;
    margin: 0 15px 0 4px;
    background: #c9ced5;
    border-radius: 1px;
  }
  .between.gap .gap-line {
    background: var(--bad);
    width: 4px;
    margin: 0 14px 0 3px;
  }
  .between.bunched .gap-line {
    background: var(--warn);
    width: 4px;
    margin: 0 14px 0 3px;
  }
  .flag {
    font-weight: 700;
    font-size: 0.75rem;
    padding: 2px 7px;
    border-radius: 999px;
  }
  .between.gap .flag {
    background: var(--bad-bg);
    color: var(--bad-text);
  }
  .between.bunched .flag {
    background: var(--warn-bg);
    color: var(--warn-text);
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
