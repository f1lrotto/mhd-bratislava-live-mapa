<script lang="ts">
  import { onMount } from 'svelte'
  import { getJson, poll } from '../lib/api'
  import { hm, minsUntil } from '../lib/format'
  import { crowM, DETOUR, here, locate, nearestM, stopLocating, walkS } from '../lib/nearby.svelte'
  import { app, closePanel, navigate } from '../lib/state.svelte'
  import type { Departure, StationBoard } from '../lib/types'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'

  // Opened from a link (/blizko) rather than the map's button: locate now. Back from a station or
  // vehicle: show you and the nearby stations again.
  onMount(() => {
    if (here.status === 'off') locate()
    else here.fitSeq++
  })

  let boards = $state.raw<Record<string, StationBoard>>({})
  let error = $state<string | null>(null)
  let more = $state(false)
  /** One station's departures only, or all of them. */
  let only = $state<string | null>(null)

  // The nearby stations' boards, refreshed with the live positions. Only their codes reach the server.
  const codes = $derived(here.nearby.map((s) => s.code).join(','))
  $effect(() => {
    const list = codes ? codes.split(',') : []
    if (!list.length) return
    return poll(async () => {
      const res = await Promise.allSettled(list.map((c) => getJson<StationBoard>(`/api/station/${encodeURIComponent(c)}`)))
      if (codes !== list.join(',')) return // the stations changed while loading
      const next: Record<string, StationBoard> = {}
      let failed: string | null = null
      res.forEach((r, i) => {
        if (r.status === 'fulfilled') next[list[i]] = r.value
        else failed = (r.reason as Error).message
      })
      // A station whose refresh failed keeps its last board.
      for (const c of list) if (!next[c] && boards[c]) next[c] = boards[c]
      boards = next
      error = Object.keys(next).length ? null : failed
    })
  })
  $effect(() => {
    if (only && !here.nearby.some((s) => s.code === only)) only = null
  })

  const pos = $derived(here.pos)
  const now = $derived(app.tick + app.skewMs)
  const loaded = $derived(here.nearby.some((s) => boards[s.code]))

  type Row = Departure & { code: string; station: string; walk: number; t: number }

  /** Seconds to spare: when the departure leaves minus the walk to its platform. */
  const spare = (r: Row) => (r.t - now) / 1000 - r.walk

  const rows = $derived.by(() => {
    if (!pos) return []
    // A trip that stops at two nearby stations is listed once: where you can catch it with the shortest walk.
    const best = new Map<string, Row>()
    const out: Row[] = []
    for (const st of here.nearby) {
      if (only && st.code !== only) continue
      for (const d of boards[st.code]?.departures ?? []) {
        const p = app.stops[d.stopId] ?? st
        const r: Row = { ...d, code: st.code, station: st.name, walk: walkS(crowM(pos, p)), t: Date.parse(d.predicted ?? d.scheduled) }
        if (!d.trip) {
          out.push(r)
          continue
        }
        const o = best.get(d.trip)
        // Prefer where it can still be caught, then the shorter walk.
        const ok = spare(r) >= 0
        if (!o || (ok && spare(o) < 0) || (ok === spare(o) >= 0 && r.walk < o.walk)) best.set(d.trip, r)
      }
    }
    // Departures missed by over 3 minutes are left out; the rest stay, the missed ones greyed.
    return [...out, ...best.values()].filter((r) => spare(r) > -180).sort((a, b) => a.t - b.t || a.line.localeCompare(b.line))
  })
  const shown = $derived(more ? rows : rows.slice(0, 20))

  function when(r: Row): string {
    const m = minsUntil(r.predicted ?? r.scheduled, now)
    if (m < 1) return 'teraz'
    if (m < 60) return `o ${m} min`
    return hm(r.predicted ?? r.scheduled)
  }

  function leave(r: Row): string {
    const s = spare(r)
    if (s < 0) return 'nestihnete'
    if (s < 60) return 'vyrazte hneď'
    return `vyrazte o ${Math.floor(s / 60)} min`
  }

  const walkMin = (s: number) => `${Math.max(1, Math.ceil(s / 60))} min`
  const dist = (crow: number) => {
    const m = crow * DETOUR
    return m < 1000 ? `${Math.max(10, Math.round(m / 10) * 10)} m` : `${(m / 1000).toFixed(1).replace('.', ',')} km`
  }

  function hide() {
    stopLocating()
    closePanel()
  }
</script>

<Panel tall label="Odchody v okolí">
  {#snippet header()}
    <span class="me" aria-hidden="true"></span>
    <div class="head-text">
      <strong>V okolí</strong>
      <span class="muted small">
        {#if here.status === 'waiting'}Zisťujem polohu…{:else if pos}Moja poloha, presnosť ±{Math.round(pos.acc)} m{:else}Moja poloha{/if}
      </span>
    </div>
  {/snippet}

  {#if here.status === 'unsupported'}
    <p class="note">Tento prehliadač polohu nepodporuje.</p>
  {:else if here.status === 'denied'}
    <p class="note error">
      Prístup k polohe je zakázaný. Povoľte ho pre túto stránku v nastaveniach prehliadača (na iPhone aj v Nastavenia ›
      Súkromie › Polohové služby) a skúste znova.
    </p>
    <button class="secondary" onclick={locate}>Skúsiť znova</button>
  {:else if !pos && here.status === 'unavailable'}
    <p class="note">Polohu sa zatiaľ nepodarilo zistiť. Skontrolujte, či má telefón zapnuté určovanie polohy.</p>
    <button class="secondary" onclick={locate}>Skúsiť znova</button>
  {:else if !pos}
    <div class="skeleton" aria-busy="true"><div></div><div></div><div></div></div>
  {:else if !here.nearby.length}
    {#if Object.keys(app.stations).length}
      <p class="empty">Do 1,5 km od vás nie je žiadna zastávka MHD ani IDS BK.</p>
    {:else}
      <p class="note">Načítavam zastávky…</p>
    {/if}
  {:else}
    {#if pos.acc > 150}
      <p class="note warn">Poloha je zatiaľ nepresná (±{Math.round(pos.acc)} m), zastávky v okolí nemusia sedieť.</p>
    {/if}

    <h3 class="section">Odchody</h3>
    {#if here.nearby.length > 1}
      <div class="filter" role="group" aria-label="Zastávka">
        <button class:active={!only} aria-pressed={!only} onclick={() => ((only = null), (more = false))}>Všetky</button>
        {#each here.nearby as st (st.code)}
          <button class:active={only === st.code} aria-pressed={only === st.code} onclick={() => ((only = st.code), (more = false))}>
            {st.name}
          </button>
        {/each}
      </div>
    {/if}

    {#if error && !loaded}
      <p class="note error">Odchody sa nepodarilo načítať ({error}).</p>
    {:else if !loaded}
      <div class="skeleton" aria-busy="true"><div></div><div></div><div></div></div>
    {:else if !rows.length}
      <p class="empty">V najbližších 90 minútach odtiaľto nič nejde.</p>
    {:else}
      <ul class="board">
        {#each shown as r (r.trip + r.stopId + r.scheduled)}
          {@const missed = spare(r) < 0}
          <li>
            <svelte:element
              this={r.vehicle ? 'button' : 'div'}
              class="dep"
              class:tap={r.vehicle}
              class:missed
              role={r.vehicle ? undefined : 'group'}
              aria-label={`Linka ${r.line} smer ${r.headsign} zo zastávky ${r.station}, ${when(r)}, ${walkMin(r.walk)} pešo, ${leave(r)}${r.vehicle ? ', otvoriť vozidlo' : ''}`}
              onclick={r.vehicle ? () => navigate({ kind: 'vehicle', key: r.vehicle! }) : undefined}
            >
              <LineBadge line={r.line} />
              <span class="dep-main">
                <span class="headsign">{r.headsign}</span>
                <span class="muted small sub">
                  <span class="stn">{r.station}{r.platform ? ` ${r.platform}` : ''}</span>
                  <span class="walk-chip" title="Pešo k nástupišťu">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="13" cy="4" r="2" /><path d="M9 21l2-6 3 3v3M7 12l3-3 3 1 2 3 3 1M10 9l1 6" /></svg>
                    {walkMin(r.walk)}
                  </span>
                </span>
              </span>
              <span class="dep-time">
                <span class="rel" class:now={when(r) === 'teraz'}>
                  {#if r.live}<span class="live-dot" title="Podľa polohy vozidla" aria-label="naživo"></span>{/if}
                  {when(r)}
                </span>
                <span class="leave small" class:soon={!missed && spare(r) < 120}>{leave(r)}</span>
              </span>
            </svelte:element>
          </li>
        {/each}
      </ul>
      {#if rows.length > shown.length}
        <button class="secondary" onclick={() => (more = true)}>Ďalšie odchody ({rows.length - shown.length})</button>
      {/if}
      <p class="muted small legend">
        <span class="live-dot" aria-hidden="true"></span> čas podľa polohy vozidla. Chôdza je odhad podľa vzdušnej vzdialenosti.
      </p>
    {/if}

    <h3 class="section">Zastávky v okolí</h3>
    <ul class="stations">
      {#each here.nearby as st (st.code)}
        {@const m = nearestM(pos, st.pts)}
        <li>
          <button class="st" onclick={() => navigate({ kind: 'station', code: st.code, stop: null })} aria-label="Zastávka {st.name}, {walkMin(walkS(m))} pešo, {dist(m)}">
            <span class="pin" aria-hidden="true"></span>
            <span class="st-main">
              <span class="name">{st.name}</span>
              <span class="lines">
                {#each st.lines.slice(0, 8) as line (line)}<LineBadge {line} size="sm" />{/each}
                {#if st.lines.length > 8}<span class="muted small">+{st.lines.length - 8}</span>{/if}
              </span>
            </span>
            <span class="st-walk">
              <b>{walkMin(walkS(m))}</b>
              <span class="muted small">{dist(m)}</span>
            </span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  {#if here.status !== 'off'}
    <button class="hide-loc small" onclick={hide}>Skryť moju polohu</button>
  {/if}
</Panel>

<style>
  .head-text {
    display: flex;
    flex-direction: column;
    line-height: 1.25;
    min-width: 0;
  }
  .me {
    flex: none;
    width: 30px;
    height: 30px;
    border-radius: 50%;
    background: rgba(20, 110, 255, 0.16);
    display: grid;
    place-items: center;
  }
  .me::after {
    content: '';
    width: 13px;
    height: 13px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 0 2.5px #fff;
  }
  .filter {
    display: flex;
    gap: 6px;
    margin: 0 -16px 6px;
    padding: 2px 16px;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .filter button {
    flex: none;
    height: 34px;
    padding: 0 12px;
    border-radius: 999px;
    background: var(--chip);
    font-weight: 600;
    font-size: 0.88rem;
    white-space: nowrap;
  }
  .filter button.active {
    background: var(--text);
    color: #fff;
  }
  .board,
  .stations {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .board li + li,
  .stations li + li {
    border-top: 1px solid var(--chip);
  }
  .dep,
  .st {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px;
    margin: 0 -8px;
    width: calc(100% + 16px);
    min-height: 52px;
    text-align: left;
    border-radius: 10px;
  }
  .dep.tap:hover,
  .st:hover {
    background: var(--hover);
  }
  .dep.missed {
    opacity: 0.45;
  }
  .dep-main,
  .st-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    line-height: 1.25;
  }
  .headsign,
  .name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sub {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .stn {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .walk-chip {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 1px;
    font-variant-numeric: tabular-nums;
  }
  .walk-chip svg {
    width: 14px;
    height: 14px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .dep-time,
  .st-walk {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    line-height: 1.25;
  }
  .rel {
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .rel.now {
    color: var(--ok);
  }
  .leave {
    color: var(--muted);
  }
  .leave.soon {
    color: var(--bad-text);
    font-weight: 600;
  }
  .live-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--ok);
    box-shadow: 0 0 0 2.5px rgba(26, 152, 80, 0.2);
  }
  .legend {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 8px 0 0;
  }
  .pin {
    flex: none;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: #fff;
    border: 2.5px solid var(--text);
  }
  .lines {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 3px;
    margin-top: 3px;
  }
  .st-walk b {
    font-weight: 700;
  }
  .empty {
    margin: 12px 0;
    padding: 14px;
    border-radius: 12px;
    background: var(--chip);
    color: var(--muted);
    text-align: center;
  }
  .hide-loc {
    display: block;
    margin-top: 14px;
    color: var(--muted);
    text-decoration: underline;
  }
  .skeleton div {
    height: 18px;
    border-radius: 6px;
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
