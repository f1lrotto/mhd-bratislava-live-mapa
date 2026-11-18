<script lang="ts">
  import { bandColor, delayBand, delayText, minutes, typeLabel, vehicleName } from '../lib/format'
  import { count, locale, t } from '../lib/i18n'
  import { app, navigate } from '../lib/state.svelte'
  import type { LineDirection, RibbonVehicle } from '../lib/types'
  import FavButton from './FavButton.svelte'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'

  let { line, dir }: { line: string; dir: string | null } = $props()

  const lv = $derived(app.lineView?.line === line ? app.lineView : null)
  const info = $derived(app.lines[line])
  const regional = $derived(!!info?.regional)
  const current = $derived(lv?.directions.find((d) => d.id === dir) ?? lv?.directions[0] ?? null)
  // Running vehicles are on the ribbon and in the order list. Parked (position unchanged 10+ min)
  // and off-route vehicles aren't part of the service right now, so they get their own list.
  const running = $derived(current ? current.vehicles.filter((v) => !v.offRoute && !v.stale) : [])
  const parked = $derived(current ? current.vehicles.filter((v) => v.offRoute || v.stale) : [])
  const AT_END_M = 250
  const dupHeadsign = (d: LineDirection) => (lv?.directions.filter((x) => x.headsign === d.headsign).length ?? 0) > 1
  const tabLabel = (d: LineDirection) => (dupHeadsign(d) ? `${d.from} → ${d.headsign}` : d.headsign)
  // Dots closer than 4% of the ribbon would overlap; stack each cluster in rows so all show.
  const row = $derived.by(() => {
    const out = new Map<string, number>()
    if (!current) return out
    let k = 0
    for (let i = 0; i < running.length; i++) {
      k = i > 0 && pct(current, running[i].along) - pct(current, running[i - 1].along) < 4 ? k + 1 : 0
      out.set(running[i].key, Math.min(k, 2))
    }
    return out
  })

  function pct(d: LineDirection, along: number): number {
    return Math.min(100, Math.max(0, (along / Math.max(1, d.length)) * 100))
  }

  function where(d: LineDirection, v: RibbonVehicle): string {
    if (v.offRoute) return t('mimo trasy', 'off the route')
    if (v.along < AT_END_M) return t(`na konečnej ${d.from}`, `at the terminus ${d.from}`)
    if (v.along > d.length - AT_END_M) return t(`na konečnej ${d.headsign}`, `at the terminus ${d.headsign}`)
    const stop = d.stops[v.lastStop]?.name ?? ''
    return t(`za zastávkou ${stop}`, `past ${stop}`)
  }

  function summary(d: LineDirection): string {
    const s = d.summary
    const parts = [count(s.count, ['vozidlo', 'vozidlá', 'vozidiel'], ['vehicle', 'vehicles']) + t(` smer ${d.headsign}`, ` towards ${d.headsign}`)]
    if (s.medianDelay != null) {
      const med = delayText(s.medianDelay, false, regional)
      parts.push(s.medianDelay < 120 ? t('väčšinou načas', 'mostly on time') : t(`medián meškania ${med}`, `median delay ${med}`))
    }
    if (s.biggestGap) {
      const g = s.biggestGap
      const gap = minutes(g.s)
      parts.push(
        g.fromStop && g.fromStop !== g.afterStop
          ? t(`medzera ≈${gap} na úseku ${g.fromStop} – ${g.afterStop}`, `a ≈${gap} gap between ${g.fromStop} and ${g.afterStop}`)
          : t(`medzera ≈${gap} pri zastávke ${g.afterStop}`, `a ≈${gap} gap at ${g.afterStop}`),
      )
    }
    else if (s.bunched)
      parts.push(
        s.bunched === 1
          ? t('dve vozidlá idú tesne za sebou', 'two vehicles running close together')
          : t(`${s.bunched}× vozidlá tesne za sebou`, `${s.bunched}× vehicles running close together`),
      )
    return parts.join(', ')
  }

  function openVehicle(key: string) {
    navigate({ kind: 'vehicle', key })
  }

  const unmatchedText = (r: string): string =>
    ({
      to_depot: t('do depa', 'to the depot'),
      no_destination: t('bez cieľa', 'no destination'),
      unknown_direction: t('neznámy smer', 'unknown direction'),
      unknown_trip: t('spoj nie je v cestovnom poriadku', 'trip not in the timetable'),
      unknown_line: t('linka nie je v cestovnom poriadku', 'line not in the timetable'),
    })[r] ?? r
</script>

<Panel tall label={t(`Linka ${line}`, `Line ${line}`)}>
  {#snippet header()}
    <LineBadge {line} size="lg" />
    <div class="head-text">
      <strong>{t(`Linka ${line}`, `Line ${line}`)}</strong>
      <span class="muted">{regional ? t('regionálny autobus', 'regional bus') + (info.operator ? ` · ${info.operator}` : '') : info ? typeLabel(info.type) : ''}</span>
    </div>
    {#if info}<FavButton kind="line" ref={line} label={t(`linka ${line}`, `line ${line}`)} />{/if}
  {/snippet}

  {#if !lv}
    {#if app.lineViewError}
      <p class="note error">
        {app.lineViewError.startsWith('unknown line')
          ? t(`Linka ${line} neexistuje.`, `Line ${line} doesn't exist.`)
          : t(`Linku sa nepodarilo načítať (${app.lineViewError}).`, `Couldn't load the line (${app.lineViewError}).`)}
      </p>
    {:else}
      <div class="skeleton" aria-busy="true">
        <div></div>
        <div></div>
        <div></div>
      </div>
    {/if}
  {:else if !current}
    <p class="note">{t(`Linka ${line} nemá v cestovnom poriadku žiadnu trasu.`, `Line ${line} has no route in the timetable.`)}</p>
  {:else}
    {#if lv.directions.length > 1}
      <div class="tabs" class:many={lv.directions.length > 2} role="group" aria-label={t('Smer', 'Direction')}>
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

    <p class="summary">{summary(current).replace(/\.?$/, '.')}</p>
    <p class="interval">
      {#if current.interval}
        {t('Podľa cestovného poriadku teraz každých', 'Timetabled now every')} <strong class="nowrap">{minutes(current.interval)}</strong>
      {:else}
        {t('Podľa cestovného poriadku teraz nepremáva', 'Not timetabled to run now')}
      {/if}
    </p>

    <div class="ribbon" aria-hidden="true">
      <div class="track" style:background={lv.color}></div>
      {#each current.stops as s, i (i)}
        <div class="tick" class:end={i === 0 || i === current.stops.length - 1} style:left="{pct(current, s.dist)}%"></div>
      {/each}
      {#each running as v, i (v.key)}
        {#if v.gapAhead?.flag && running[i + 1]}
          <div
            class="seg {v.gapAhead.flag}"
            style:left="{pct(current, v.along)}%"
            style:width="{pct(current, running[i + 1].along) - pct(current, v.along)}%"
          ></div>
        {/if}
      {/each}
      {#each running as v (v.key)}
        <button
          class="dot"
          style:left="{pct(current, v.along)}%"
          style:top="{14 - 13 * (row.get(v.key) ?? 0)}px"
          style:background={bandColor(delayBand(v.delay))}
          tabindex="-1"
          aria-label={t('Vozidlo', 'Vehicle') + ' ' + vehicleName(v.key, v.tripNo)}
          onclick={() => openVehicle(v.key)}
        ></button>
      {/each}
    </div>
    <div class="ends">
      <span>{current.from}</span>
      <span>{current.headsign}</span>
    </div>

    <button class="reliability" onclick={() => navigate({ kind: 'reliability', line, dir: current.id, weekends: false })}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h4v4H4zM10 4h4v4h-4zM16 4h4v4h-4zM4 10h4v4H4zM10 10h4v4h-4zM4 16h4v4H4z" /></svg>
      <span class="row-main">
        <span>{t('Kde a kedy linka mešká', 'Where and when the line runs late')}</span>
        <span class="muted small">{t('spoľahlivosť za posledné 4 týždne', 'reliability over the last 4 weeks')}</span>
      </span>
      <span class="chev" aria-hidden="true">›</span>
    </button>

    {#if running.length}
      <h3 class="section">{t('Poradie vozidiel od začiatku trasy', 'Vehicles in order from the start of the route')}</h3>
      <ol class="order">
        {#each running as v, i (v.key)}
          <li>
            <button class="row" onclick={() => openVehicle(v.key)}>
              <span class="pip" style:background={bandColor(delayBand(v.delay))}></span>
              <span class="row-main">
                <span class="where">{where(current, v)}</span>
                <span class="muted small">{vehicleName(v.key, v.tripNo)}</span>
              </span>
              <span class="delay" class:late={(v.delay ?? 0) >= 300}>{delayText(v.delay, false, regional)}</span>
            </button>
            {#if v.gapAhead && i < running.length - 1}
              <div class="between {v.gapAhead.flag ?? ''}">
                <span class="gap-line" aria-hidden="true"></span>
                {#if v.gapAhead.s != null}≈{minutes(v.gapAhead.s)}{/if}
                <span class="muted">· {(v.gapAhead.m / 1000).toLocaleString(locale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 })} km</span>
                {#if v.gapAhead.flag === 'gap'}<span class="flag">{t('medzera', 'gap')}</span>{/if}
                {#if v.gapAhead.flag === 'bunched'}<span class="flag">{t('tesne za sebou', 'bunched')}</span>{/if}
              </div>
            {/if}
          </li>
        {/each}
      </ol>
    {:else}
      <p class="note">{t('V tomto smere teraz nejde žiadne vozidlo.', 'No vehicle is running in this direction now.')}</p>
    {/if}

    {#if parked.length}
      <h3 class="section">{t('Stojace alebo mimo trasy', 'Standing or off the route')}</h3>
      <ul class="unmatched">
        {#each parked as v (v.key)}
          <li>
            <button class="row" onclick={() => openVehicle(v.key)}>
              <span class="pip" style:background="var(--stale)"></span>
              <span class="row-main">
                <span class="where">{where(current, v)}</span>
                <span class="muted small">{vehicleName(v.key, v.tripNo)}{v.stale ? t(' · poloha sa nemení 10+ min', ' · not moved for 10+ min') : ''}</span>
              </span>
              <span class="delay muted">{delayText(v.delay, false, regional)}</span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}

    {#if lv.unmatched.length}
      <h3 class="section">{t('Mimo poradia', 'Not in the order')}</h3>
      <ul class="unmatched">
        {#each lv.unmatched as u (u.key)}
          <li>
            <button class="row" onclick={() => openVehicle(u.key)}>
              <span class="row-main"
                ><span>{vehicleName(u.key, null)}</span><span class="muted small">{u.dest ?? t('bez cieľa', 'no destination')} · {unmatchedText(u.reason)}</span></span
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
    border: 2.5px solid var(--surface);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
    padding: 0;
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
  .reliability {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    margin: 4px 0 2px;
    padding: 8px 12px;
    border-radius: 10px;
    background: var(--chip);
    text-align: left;
    min-height: 48px;
  }
  .reliability:hover {
    background: var(--hover);
  }
  .reliability svg {
    width: 20px;
    height: 20px;
    flex: none;
    fill: var(--accent);
  }
  .reliability .row-main span:first-child {
    font-weight: 600;
  }
  .chev {
    font-size: 1.4rem;
    color: var(--muted);
    line-height: 1;
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
    background: var(--rail);
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
