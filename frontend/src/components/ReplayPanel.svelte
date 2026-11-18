<script lang="ts">
  import { onMount, untrack } from 'svelte'
  import { track } from '../lib/analytics.svelte'
  import { passes } from '../lib/filter'
  import { bandColor, dayText, delayText, fromLocalInput, percent, toLocalInput, TZ, vehicleName } from '../lib/format'
  import { count, locale, t } from '../lib/i18n'
  import { frame, latest, loadRange, pause, play, ready, replay, seek, SPEEDS } from '../lib/replay.svelte'
  import { app, navigate } from '../lib/state.svelte'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'
  import TimeStepper from './TimeStepper.svelte'

  let { at }: { at: string | null } = $props()

  // 24-hour Bratislava time in both languages; the weekday follows the language.
  const CLOCK = $derived(new Intl.DateTimeFormat(locale(), { timeZone: TZ, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }))
  const WEEKDAY = $derived(new Intl.DateTimeFormat(locale(), { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'numeric' }))

  const iso = (s: number) => new Date(s * 1000).toISOString()
  /** A `cas` value as a Unix time; a hand-typed "+01:00" arrives as " 01:00". */
  function parseAt(v: string | null): number | null {
    const s = v ? Date.parse(v.replace(' ', '+')) / 1000 : NaN
    return Number.isNaN(s) ? null : s
  }
  /** A Bratislava calendar day "2026-11-13" of a Unix time. */
  const localDay = (s: number) => toLocalInput(iso(s)).slice(0, 10)
  const wallTime = (day: string, hm: string) => Date.parse(fromLocalInput(`${day}T${hm}`)!) / 1000
  function nextDay(day: string): string {
    const [y, m, d] = day.split('-').map(Number)
    return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10)
  }

  onMount(() => {
    track('replay_opened', { linked: at != null })
    // Opened without a time: an hour ago, which the log surely has if the server ran.
    seek(parseAt(at) ?? latest() - 3600)
    loadRange().then(() => seek(replay.t))
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (e.key !== ' ' || tag === 'INPUT' || tag === 'BUTTON' || tag === 'TEXTAREA') return
      e.preventDefault()
      toggle()
    }
    addEventListener('keydown', onKey)
    return () => {
      removeEventListener('keydown', onKey)
      pause()
      replay.sel = null
    }
  })

  // A link to another time (back/forward) moves there; the URL this panel writes itself doesn't.
  let written: string | null = null
  $effect(() => {
    const s = at !== written ? parseAt(at) : null
    if (s != null) untrack(() => Math.abs(s - replay.t) >= 60 && seek(s))
  })

  // The URL follows the replayed minute while paused, so it can be shared ("Friday at 17:00").
  $effect(() => {
    const s = replay.t
    if (replay.playing || !s) return
    const timer = setTimeout(() => {
      const v = fromLocalInput(toLocalInput(iso(s)))
      if (app.view.kind === 'replay' && v !== app.view.at) {
        written = v
        navigate({ kind: 'replay', at: v }, { replace: true })
      }
    }, 400)
    return () => clearTimeout(timer)
  })

  let timeOpen = $state(false)

  function toggle() {
    if (replay.playing) pause()
    else play()
  }

  const day = $derived(replay.t ? localDay(replay.t) : null)
  const dayStart = $derived(day ? wallTime(day, '00:00') : 0)
  const dayEnd = $derived(day ? wallTime(nextDay(day), '00:00') : 0)
  const hours = $derived(replay.range?.hours ?? [])

  // Logged hours of the shown day, merged into spans, as fractions of the day.
  const covered = $derived.by(() => {
    const spans: [number, number][] = []
    for (const h of hours) {
      if (h + 3600 <= dayStart || h >= dayEnd) continue
      const a = Math.max(h, dayStart), b = Math.min(h + 3600, dayEnd, latest())
      const s = spans.at(-1)
      if (s && s[1] >= a) s[1] = b
      else spans.push([a, b])
    }
    const len = dayEnd - dayStart
    return spans.map(([a, b]) => ({ left: ((a - dayStart) / len) * 100, width: ((b - a) / len) * 100 }))
  })

  // Every day from the oldest logged one to today, newest first; days without logs can't be picked.
  const days = $derived.by(() => {
    if (!hours.length) return []
    const has = new Set(hours.map(localDay))
    const today = localDay(latest())
    const out: { day: string; label: string; has: boolean }[] = []
    for (let d = localDay(hours[0]); d <= today; d = nextDay(d)) out.push({ day: d, label: '', has: has.has(d) })
    const yesterday = out.at(-2)?.day
    for (const x of out) x.label = x.day === today ? t('dnes', 'today') : x.day === yesterday ? t('včera', 'yesterday') : dayText(`${x.day}T12:00:00Z`)
    return out.reverse()
  })

  function pickDay(d: string) {
    // The same time of day on the other day.
    seek(wallTime(d, '00:00') + (replay.t - dayStart))
  }

  const vehicles = $derived.by(() => {
    void replay.loaded
    return replay.t ? frame(replay.t) : []
  })
  const isReady = $derived.by(() => {
    void replay.loaded
    return ready(replay.t)
  })
  const shown = $derived(vehicles.filter((v) => passes(v, app.filters)))
  const running = $derived(shown.filter((v) => v.service === 'running' && v.delay != null))
  const lateShare = $derived(running.length ? running.filter((v) => v.delay! >= 300).length / running.length : null)
  const sel = $derived(replay.sel ? vehicles.find((v) => v.key === replay.sel) : null)
  const atLatest = $derived(replay.t >= latest() - 1)
</script>

<Panel label={t('Záznam', 'Replay')}>
  {#snippet header()}
    <strong>{t('Záznam jázd', 'Journey replay')}</strong>
  {/snippet}

  <div class="clock-row">
    <button class="play" onclick={toggle} disabled={atLatest && !replay.playing} aria-label={replay.playing ? t('Pozastaviť', 'Pause') : t('Prehrať', 'Play')}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        {#if replay.playing}<path d="M8 5v14M16 5v14" />{:else}<path d="M8 5l11 7-11 7z" />{/if}
      </svg>
    </button>
    <div class="clock" aria-live="off">
      <strong>{replay.t ? CLOCK.format(replay.t * 1000) : '–'}</strong>
      <span class="muted">{replay.t ? WEEKDAY.format(replay.t * 1000) : ''}</span>
    </div>
    {#if day}
      <button class="time-btn" class:open={timeOpen} aria-expanded={timeOpen} aria-controls="replay-time" onclick={() => (timeOpen = !timeOpen)}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>
        {t('Čas', 'Time')}
      </button>
    {/if}
  </div>
  {#if timeOpen && day}
    <div class="time-pop" id="replay-time" role="group" aria-label={t('Čas záznamu', 'Replay time')}>
      <TimeStepper value={replay.t * 1000} min={(hours[0] ?? 0) * 1000} max={latest() * 1000} onchange={(ms) => seek(ms / 1000)} />
    </div>
  {/if}

  {#if day}
    <div class="scrub">
      <div class="coverage" aria-hidden="true">
        {#each covered as c, i (i)}<span style:left="{c.left}%" style:width="{c.width}%"></span>{/each}
      </div>
      <input
        type="range"
        min={dayStart}
        max={dayEnd - 1}
        step="15"
        value={replay.t}
        oninput={(e) => seek(+e.currentTarget.value)}
        aria-label={t('Čas záznamu', 'Replay time')}
        aria-valuetext={CLOCK.format(replay.t * 1000)}
      />
      <div class="ticks small muted" aria-hidden="true"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>
    </div>
  {/if}

  <div class="controls">
    <button class="step" onclick={() => seek(replay.t - 600)} aria-label={t('O 10 minút späť', '10 minutes back')}>−10 min</button>
    <button class="step" onclick={() => seek(replay.t + 600)} disabled={atLatest} aria-label={t('O 10 minút dopredu', '10 minutes forward')}>+10 min</button>
    <div class="speeds" role="group" aria-label={t('Rýchlosť prehrávania', 'Playback speed')}>
      {#each SPEEDS as s (s)}
        <button aria-pressed={replay.speed === s} onclick={() => (replay.speed = s)}>{s}×</button>
      {/each}
    </div>
  </div>

  <p class="status" class:empty={isReady && !vehicles.length} role="status">
    {#if replay.error && !isReady}
      {t(`Záznam sa nedá načítať (${replay.error}).`, `Couldn't load the replay (${replay.error}).`)}
    {:else if replay.range && !hours.length}
      {t('Záznam polôh zatiaľ nie je k dispozícii.', 'No position log is available yet.')}
    {:else if !isReady}
      {t('Načítavam záznam…', 'Loading the replay…')}
    {:else if !vehicles.length}
      {t('V tomto čase nemáme záznam polôh.', 'We have no positions logged for this time.')}
    {:else}
      {t('Na mape', 'On the map:')} {count(shown.length, ['vozidlo', 'vozidlá', 'vozidiel'], ['vehicle', 'vehicles'])}{#if lateShare != null}&nbsp;· {t(
          `5+ min mešká ${percent(lateShare)}`,
          `${percent(lateShare)} 5+ min late`,
        )}{/if}
    {/if}
  </p>

  {#if replay.sel}
    <div class="sel">
      {#if sel}
        {#if sel.line}<LineBadge line={sel.line} />{/if}
        <div class="sel-text">
          <strong>{sel.dest ?? t('bez cieľa', 'no destination')}</strong>
          <span class="small muted">{vehicleName(sel.key, null)}</span>
        </div>
        <span class="delay" style:color={sel.band != null ? bandColor(sel.band) : undefined}>
          {sel.service === 'running' ? delayText(sel.delay, sel.delayCapped, sel.regional) : t('mimo spoja', 'not on a trip')}
        </span>
      {:else}
        <span class="sel-text muted"
          >{t(`Vozidlo ${vehicleName(replay.sel, null)} v tomto čase nejazdí.`, `Vehicle ${vehicleName(replay.sel, null)} isn't running at this time.`)}</span
        >
      {/if}
      <button class="close-sel" onclick={() => (replay.sel = null)} aria-label={t('Zrušiť výber vozidla', 'Deselect the vehicle')}>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" /></svg>
      </button>
    </div>
  {:else}
    <p class="small muted hint">{t('Ťuknutím na vozidlo uvidíte jeho linku a meškanie v tom čase.', 'Tap a vehicle to see its line and delay at that time.')}</p>
  {/if}

  {#if days.length}
    <h3 class="section">{t('Deň', 'Day')}</h3>
    <div class="days">
      {#each days as d (d.day)}
        <button aria-pressed={d.day === day} disabled={!d.has} onclick={() => pickDay(d.day)}>{d.label}</button>
      {/each}
    </div>
  {/if}

  <p class="note">
    {t(
      `Polohy vozidiel uchovávame ${replay.range?.rawDays ?? 30} dní, preto sa dá prehrať len posledný mesiac. Farba ukazuje meškanie v danom čase, ako na živej mape.`,
      `We keep vehicle positions for ${replay.range?.rawDays ?? 30} days, so only the last month can be replayed. The colour shows the delay at that time, as on the live map.`,
    )}
  </p>
</Panel>

<style>
  .clock-row {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .play {
    flex: none;
    width: 52px;
    height: 52px;
    border-radius: 50%;
    background: var(--text);
    color: var(--on-text);
    display: grid;
    place-items: center;
  }
  .play:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .play svg {
    width: 24px;
    height: 24px;
    fill: currentColor;
    stroke: currentColor;
    stroke-width: 2.4;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .clock {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    line-height: 1.2;
  }
  .clock strong {
    font-size: 1.6rem;
    font-variant-numeric: tabular-nums;
  }
  .time-btn {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 38px;
    padding: 0 12px 0 10px;
    border-radius: 999px;
    background: var(--chip);
    font-weight: 600;
    font-size: 0.88rem;
  }
  .time-btn:hover {
    background: var(--hover);
  }
  .time-btn.open {
    box-shadow: inset 0 0 0 2px var(--accent);
  }
  .time-btn svg {
    width: 17px;
    height: 17px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .time-pop {
    margin-top: 10px;
    padding: 10px 12px 12px;
    border-radius: 14px;
    border: 1px solid var(--line);
    box-shadow: var(--shadow-sm);
  }
  .scrub {
    position: relative;
    margin-top: 14px;
  }
  .coverage {
    position: absolute;
    left: 0;
    right: 0;
    top: 9px;
    height: 8px;
    border-radius: 4px;
    background: repeating-linear-gradient(-45deg, var(--chip) 0 4px, var(--line) 4px 8px);
    overflow: hidden;
  }
  .coverage span {
    position: absolute;
    top: 0;
    bottom: 0;
    background: #8f98a3;
  }
  .scrub input {
    position: relative;
    width: 100%;
    height: 26px;
    margin: 0;
    background: transparent;
    accent-color: var(--text);
    appearance: none;
    -webkit-appearance: none;
  }
  .scrub input::-webkit-slider-runnable-track {
    height: 8px;
    background: transparent;
  }
  .scrub input::-moz-range-track {
    height: 8px;
    background: transparent;
  }
  .scrub input::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 22px;
    height: 22px;
    margin-top: -7px;
    border-radius: 50%;
    background: var(--text);
    border: 3px solid var(--surface);
    box-shadow: var(--shadow-sm);
  }
  .scrub input::-moz-range-thumb {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--text);
    border: 3px solid var(--surface);
    box-shadow: var(--shadow-sm);
  }
  .ticks {
    display: flex;
    justify-content: space-between;
    font-variant-numeric: tabular-nums;
  }
  .controls {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .step,
  .speeds button,
  .days button {
    height: 38px;
    padding: 0 12px;
    border-radius: 999px;
    background: var(--chip);
    font-weight: 600;
    font-size: 0.88rem;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .step:hover:not(:disabled),
  .speeds button:hover,
  .days button:hover:not(:disabled) {
    background: var(--hover);
  }
  .step:disabled,
  .days button:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .speeds {
    display: flex;
    gap: 2px;
    margin-left: auto;
    padding: 2px;
    border-radius: 999px;
    background: var(--chip);
  }
  .speeds button {
    height: 34px;
    padding: 0 10px;
  }
  .speeds button[aria-pressed='true'],
  .days button[aria-pressed='true'] {
    background: var(--text);
    color: var(--on-text);
  }
  .status {
    margin: 10px 0 0;
    font-size: 0.9rem;
    color: var(--muted);
  }
  .status.empty {
    color: var(--warn-text);
    font-weight: 600;
  }
  .sel {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 10px;
    padding: 8px 6px 8px 10px;
    border-radius: 12px;
    background: var(--chip);
  }
  .sel-text {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    line-height: 1.25;
  }
  .sel-text strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .delay {
    font-weight: 700;
    white-space: nowrap;
  }
  .close-sel {
    flex: none;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: var(--muted);
  }
  .close-sel:hover {
    background: var(--hover);
  }
  .hint {
    margin: 8px 0 0;
  }
  .days {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    padding-bottom: 4px;
    scrollbar-width: thin;
  }
  .days button {
    flex: none;
  }
</style>
