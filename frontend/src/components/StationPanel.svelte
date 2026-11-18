<script lang="ts">
  import { getJson, poll } from '../lib/api'
  import { hm, minsUntil, plural } from '../lib/format'
  import { app, navigate } from '../lib/state.svelte'
  import type { Departure, StationBoard } from '../lib/types'
  import FavButton from './FavButton.svelte'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'

  let { code, stop }: { code: string; stop: string | null } = $props()

  const station = $derived(app.stations[code])

  // An old /zastavka/<stop id> link: show the stop's station with that platform picked.
  $effect(() => {
    const s = app.stops[code]
    if (!app.stations[code] && s?.station) navigate({ kind: 'station', code: s.station, stop: code }, { replace: true })
  })

  let board = $state.raw<StationBoard | null>(null)
  let error = $state<string | null>(null)
  let more = $state(false)

  // Null while an old stop-id link is being redirected to its station.
  const boardCode = $derived(!app.stations[code] && app.stops[code] ? null : code)
  $effect(() => {
    const c = boardCode
    if (!c) return
    board = null
    error = null
    return poll(async () => {
      try {
        const b = await getJson<StationBoard>(`/api/station/${encodeURIComponent(c)}`)
        if (c === code) {
          board = b
          error = null
        }
      } catch (e) {
        if (c === code) error = (e as Error).message
      }
    })
  })

  const platforms = $derived(
    (board?.platforms.filter((p) => p.platform) ?? []).toSorted((a, b) => a.platform!.localeCompare(b.platform!, 'sk')),
  )
  const deps = $derived(board ? board.departures.filter((d) => !stop || d.stopId === stop) : [])
  const shown = $derived(more ? deps : deps.slice(0, 20))
  const now = $derived(app.tick + app.skewMs)
  const name = $derived(board?.name ?? station?.name ?? 'Zastávka')
  const lines = $derived(board?.lines ?? station?.lines ?? [])

  function when(d: Departure): string {
    const m = minsUntil(d.predicted ?? d.scheduled, now)
    if (m < 1) return 'teraz'
    if (m < 60) return `o ${m} min`
    return hm(d.predicted ?? d.scheduled)
  }

  function pickPlatform(id: string | null) {
    more = false
    navigate({ kind: 'station', code, stop: id }, { replace: true })
  }

  function plan(end: 'from' | 'to') {
    navigate({ kind: 'plan', from: end === 'from' ? code : null, to: end === 'to' ? code : null, at: null, opt: null })
  }
</script>

<Panel tall label="Zastávka {name}">
  {#snippet header()}
    <span class="pin" aria-hidden="true"></span>
    <div class="head-text">
      <strong>{name}</strong>
      <span class="muted small">
        {#if platforms.length > 1}{plural(platforms.length, 'nástupište', 'nástupištia', 'nástupíšť')}{:else}Zastávka{/if}
      </span>
    </div>
    {#if station}<FavButton kind="station" ref={code} label={name} />{/if}
  {/snippet}

  {#if !station && !board && !error}
    {#if Object.keys(app.stations).length}
      <p class="note">Zastávku sme nenašli.</p>
    {:else}
      <p class="note">Načítavam…</p>
    {/if}
  {:else}
    <div class="actions">
      <button class="secondary" onclick={() => plan('from')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v4M12 18v4M2 12h4M18 12h4" /></svg>
        Trasa odtiaľto
      </button>
      <button class="secondary" onclick={() => plan('to')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11z" /><circle cx="12" cy="10" r="2" /></svg>
        Trasa sem
      </button>
    </div>

    <h3 class="section">Odchody</h3>
    {#if platforms.length > 1}
      <div class="plat" role="group" aria-label="Nástupište">
        <button class:active={!stop} aria-pressed={!stop} onclick={() => pickPlatform(null)}>Všetky</button>
        {#each platforms as p (p.stopId)}
          <button
            class:active={stop === p.stopId}
            aria-pressed={stop === p.stopId}
            onclick={() => pickPlatform(p.stopId)}
            title="Linky {p.lines.join(', ')}"
            aria-label="Nástupište {p.platform}, linky {p.lines.join(', ')}"
          >
            {p.platform}
          </button>
        {/each}
      </div>
    {/if}

    {#if error && !board}
      <p class="note error">Odchody sa nepodarilo načítať ({error}).</p>
    {:else if !board}
      <div class="skeleton" aria-busy="true"><div></div><div></div><div></div></div>
    {:else if !deps.length}
      <p class="empty">V najbližších 90 minútach odtiaľto nič nejde.</p>
    {:else}
      <ul class="board">
        {#each shown as d (d.trip + d.stopId + d.scheduled)}
          {@const changed = d.predicted && hm(d.predicted) !== hm(d.scheduled)}
          <li>
            <svelte:element
              this={d.vehicle ? 'button' : 'div'}
              class="dep"
              class:tap={d.vehicle}
              role={d.vehicle ? undefined : 'group'}
              aria-label={d.vehicle ? `Linka ${d.line} smer ${d.headsign}, ${when(d)}, otvoriť vozidlo` : undefined}
              onclick={d.vehicle ? () => navigate({ kind: 'vehicle', key: d.vehicle! }) : undefined}
            >
              <LineBadge line={d.line} />
              <span class="dep-main">
                <span class="headsign">{d.headsign}</span>
                <span class="muted small">
                  {#if d.platform}nástupište {d.platform}{/if}
                  {#if d.uncertain}<span class="late">· 15+ min meškanie</span>{/if}
                </span>
              </span>
              <span class="dep-time">
                <span class="rel" class:now={when(d) === 'teraz'}>{when(d)}</span>
                <span class="abs small" class:hide={!d.live && !changed && when(d) === hm(d.scheduled)}>
                  {#if d.live}<span class="live-dot" title="Podľa polohy vozidla" aria-label="naživo"></span>{/if}
                  {#if changed}
                    <span class:late={d.uncertain}>{hm(d.predicted)}</span>
                    <s class="muted">{hm(d.scheduled)}</s>
                  {:else}
                    <span class="muted">{hm(d.predicted ?? d.scheduled)}</span>
                  {/if}
                </span>
              </span>
            </svelte:element>
          </li>
        {/each}
      </ul>
      {#if deps.length > shown.length}
        <button class="secondary" onclick={() => (more = true)}>Ďalšie odchody ({deps.length - shown.length})</button>
      {/if}
      <p class="muted small legend"><span class="live-dot" aria-hidden="true"></span> čas podľa polohy vozidla, inak podľa cestovného poriadku</p>
    {/if}
    {#if lines.length}
      <h3 class="section">Linky</h3>
      <div class="chips">
        {#each lines as line (line)}
          <button class="chip-btn" onclick={() => navigate({ kind: 'line', line, dir: null })} aria-label="Linka {line}">
            <LineBadge {line} size="sm" />
          </button>
        {/each}
      </div>
    {/if}

    <a class="ubian small" href="https://www.ubian.sk/odchody" target="_blank" rel="noopener">Odchody v Ubiane ↗</a>
  {/if}
</Panel>

<style>
  .head-text {
    display: flex;
    flex-direction: column;
    line-height: 1.25;
    min-width: 0;
  }
  .pin {
    flex: none;
    width: 30px;
    height: 30px;
    border-radius: 50%;
    background: #fff;
    border: 3px solid var(--text);
    box-shadow: inset 0 0 0 4px #fff, inset 0 0 0 10px var(--text);
  }
  .actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  .actions .secondary {
    margin-top: 0;
    gap: 6px;
    min-height: 44px;
    font-size: 0.92rem;
  }
  .actions svg {
    width: 18px;
    height: 18px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
  }
  .plat {
    display: flex;
    gap: 6px;
    margin: 0 -16px 6px;
    padding: 2px 16px;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .plat button {
    flex: none;
    min-width: 40px;
    height: 34px;
    padding: 0 10px;
    border-radius: 999px;
    background: var(--chip);
    font-weight: 600;
    font-size: 0.88rem;
  }
  .plat button.active {
    background: var(--text);
    color: #fff;
  }
  .board {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .board li + li {
    border-top: 1px solid var(--chip);
  }
  .dep {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 8px;
    margin: 0 -8px;
    width: calc(100% + 16px);
    min-height: 52px;
    text-align: left;
    border-radius: 10px;
  }
  .dep.tap:hover {
    background: var(--hover);
  }
  .dep-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    line-height: 1.25;
  }
  .headsign {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dep-time {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    line-height: 1.25;
  }
  .rel {
    font-weight: 700;
  }
  .rel.now {
    color: var(--ok);
  }
  .abs {
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .abs.hide {
    display: none;
  }
  .late {
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
  .empty {
    margin: 12px 0;
    padding: 14px;
    border-radius: 12px;
    background: var(--chip);
    color: var(--muted);
    text-align: center;
  }
  .ubian {
    display: inline-block;
    margin-top: 12px;
    color: var(--muted);
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
