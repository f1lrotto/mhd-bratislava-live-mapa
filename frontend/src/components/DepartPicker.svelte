<script lang="ts">
  import { tick } from 'svelte'
  import { dayText, fromLocalInput, toLocalInput } from '../lib/format'
  import { locale, t } from '../lib/i18n'
  import TimeStepper from './TimeStepper.svelte'

  /** The departure time of the planner and the reachability map: now, or a Bratislava day and time
   * picked from chips, and a calendar and a time stepper that open under the chips. */
  let {
    at,
    now,
    onchange,
    open = $bindable(false),
  }: {
    at: string | null
    now: number
    onchange: (at: string | null) => void
    /** A picker is open (the phone sheet should grow to show it). */
    open?: boolean
  } = $props()

  const DAY_MS = 86_400_000
  /** How far ahead the calendar goes. */
  const MAX_DAYS = 60
  const addDays = (d: string, n: number) => new Date(Date.parse(d) + n * DAY_MS).toISOString().slice(0, 10)
  const today = $derived(toLocalInput(new Date(now).toISOString()).slice(0, 10))
  const tomorrow = $derived(addDays(today, 1))
  const lastDay = $derived(addDays(today, MAX_DAYS))
  const atDate = $derived(at ? toLocalInput(at).slice(0, 10) : null)
  const atTime = $derived(at ? toLocalInput(at).slice(11, 16) : '')
  const otherDay = $derived(!!atDate && atDate !== today && atDate !== tomorrow)

  let picker = $state<'date' | 'time' | null>(null)
  $effect(() => {
    open = picker !== null
  })
  let dateBtn = $state<HTMLButtonElement>()
  let timeBtn = $state<HTMLButtonElement>()
  let pop = $state<HTMLElement>()

  function setDay(date: string) {
    // Keep the chosen time; without one, the next full 5 minutes.
    const time = atTime || toLocalInput(new Date(Math.ceil((now + 60_000) / 300_000) * 300_000).toISOString()).slice(11, 16)
    onchange(fromLocalInput(`${date}T${time}`))
  }
  function setNow() {
    picker = null
    onchange(null)
  }

  async function toggle(p: 'date' | 'time') {
    if (picker === p) return close()
    if (p === 'date') month = (atDate ?? today).slice(0, 7)
    picker = p
    await tick()
    pop?.scrollIntoView({ block: 'nearest' })
    pop?.querySelector<HTMLButtonElement>('.grid button[tabindex="0"], .stepper button')?.focus({ preventScroll: true })
  }
  function close() {
    const back = picker === 'date' ? dateBtn : timeBtn
    picker = null
    back?.focus()
  }

  // --- calendar ------------------------------------------------------------------------------------
  // Weeks start on Monday in both languages.
  const WEEKDAYS = $derived(t('po ut st št pi so ne', 'Mo Tu We Th Fr Sa Su').split(' '))
  const MONTH = $derived(new Intl.DateTimeFormat(locale(), { month: 'long', year: 'numeric', timeZone: 'UTC' }))
  const FULL_DAY = $derived(new Intl.DateTimeFormat(locale(), { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' }))
  /** The month shown, "2026-11". */
  let month = $state('')
  const days = $derived.by(() => {
    if (!month) return []
    const [y, m] = month.split('-').map(Number)
    const lead = (new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 6) % 7
    const count = new Date(Date.UTC(y, m, 0)).getUTCDate()
    return [
      ...Array<null>(lead).fill(null),
      ...Array.from({ length: count }, (_, i) => `${month}-${String(i + 1).padStart(2, '0')}`),
    ]
  })
  const selectable = (d: string) => d >= today && d <= lastDay
  // The one day in the tab order: the chosen day, else today, else the first one that can be picked.
  const focusDay = $derived(
    [atDate, today].find((d) => d && d.startsWith(month) && selectable(d)) ??
      days.find((d): d is string => !!d && selectable(d)) ??
      null,
  )
  function shiftMonth(n: number) {
    const [y, m] = month.split('-').map(Number)
    month = new Date(Date.UTC(y, m - 1 + n, 1)).toISOString().slice(0, 7)
  }
  function pickDay(d: string) {
    setDay(d)
    close()
  }

  /** Arrow keys move between the cells of a grid of `cols` columns (blank cells included). */
  function gridKeys(e: KeyboardEvent, cols: number) {
    const step = ({ ArrowLeft: -1, ArrowRight: 1, ArrowUp: -cols, ArrowDown: cols } as Record<string, number>)[e.key]
    if (!step) return
    const cells = [...(e.currentTarget as HTMLElement).children]
    const next = cells[cells.indexOf(document.activeElement as Element) + step]
    e.preventDefault()
    if (next instanceof HTMLButtonElement && !next.disabled) next.focus()
  }
</script>

<div class="chips" role="group" aria-label={t('Čas odchodu', 'Departure time')}>
  <button class:active={!at} aria-pressed={!at} onclick={setNow}>{t('Teraz', 'Now')}</button>
  <button class:active={atDate === today} aria-pressed={atDate === today} onclick={() => setDay(today)}>{t('Dnes', 'Today')}</button>
  <button class:active={atDate === tomorrow} aria-pressed={atDate === tomorrow} onclick={() => setDay(tomorrow)}>{t('Zajtra', 'Tomorrow')}</button>
  <button
    class="trigger"
    class:active={otherDay}
    class:open={picker === 'date'}
    aria-expanded={picker === 'date'}
    aria-controls="depart-pop"
    aria-label={otherDay && at ? t(`Deň odchodu: ${dayText(at)}`, `Departure day: ${dayText(at)}`) : t('Vybrať iný deň', 'Choose another day')}
    bind:this={dateBtn}
    onclick={() => toggle('date')}
  >
    <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5.5" width="16" height="14.5" rx="2.5" /><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" /></svg>
    {otherDay && at ? dayText(at) : t('Iný deň', 'Other day')}
  </button>
  {#if at}
    <button
      class="trigger time"
      class:open={picker === 'time'}
      aria-expanded={picker === 'time'}
      aria-controls="depart-pop"
      aria-label={t(`Čas odchodu: ${atTime}`, `Departure time: ${atTime}`)}
      bind:this={timeBtn}
      onclick={() => toggle('time')}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>
      {atTime}
    </button>
  {/if}
</div>

{#if picker}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    class="pop"
    id="depart-pop"
    role="group"
    aria-label={picker === 'date' ? t('Deň odchodu', 'Departure day') : t('Čas odchodu', 'Departure time')}
    tabindex="-1"
    bind:this={pop}
    onkeydown={(e) => e.key === 'Escape' && (e.stopPropagation(), close())}
  >
    {#if picker === 'date'}
      <div class="month">
        <button class="nav" onclick={() => shiftMonth(-1)} disabled={month <= today.slice(0, 7)} aria-label={t('Predchádzajúci mesiac', 'Previous month')}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 6l-6 6 6 6" /></svg>
        </button>
        <strong aria-live="polite">{MONTH.format(new Date(`${month}-01T00:00:00Z`))}</strong>
        <button class="nav" onclick={() => shiftMonth(1)} disabled={month >= lastDay.slice(0, 7)} aria-label={t('Ďalší mesiac', 'Next month')}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.5 6l6 6-6 6" /></svg>
        </button>
      </div>
      <div class="weekdays" aria-hidden="true">
        {#each WEEKDAYS as w (w)}<span>{w}</span>{/each}
      </div>
      <!-- svelte-ignore a11y_interactive_supports_focus -->
      <div class="grid days" role="group" aria-label={t('Dni', 'Days')} onkeydown={(e) => gridKeys(e, 7)}>
        {#each days as d, i (d ?? `blank${i}`)}
          {#if d}
            <button
              class:sel={d === atDate}
              class:today={d === today}
              disabled={!selectable(d)}
              tabindex={d === focusDay ? 0 : -1}
              aria-pressed={d === atDate}
              aria-current={d === today ? 'date' : undefined}
              aria-label={FULL_DAY.format(new Date(`${d}T00:00:00Z`))}
              onclick={() => pickDay(d)}>{+d.slice(8)}</button
            >
          {:else}<span></span>{/if}
        {/each}
      </div>
    {:else if at}
      <TimeStepper
        value={Date.parse(at)}
        min={Date.parse(fromLocalInput(`${today}T00:00`)!)}
        max={Date.parse(fromLocalInput(`${lastDay}T23:59`)!)}
        onchange={(ms) => onchange(fromLocalInput(toLocalInput(new Date(ms).toISOString())))}
      />
    {/if}
  </div>
{/if}

<style>
  .chips {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .chips button {
    height: 34px;
    padding: 0 12px;
    border-radius: 999px;
    background: var(--chip);
    font-weight: 600;
    font-size: 0.88rem;
  }
  .chips button:hover:not(.active) {
    background: var(--hover);
  }
  .chips button.active {
    background: var(--text);
    color: var(--on-text);
  }
  .trigger {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .chips .trigger {
    padding-left: 10px;
  }
  .trigger.open {
    box-shadow: inset 0 0 0 2px var(--accent);
  }
  .trigger.active.open {
    box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px var(--accent);
  }
  .time {
    font-variant-numeric: tabular-nums;
  }
  .chips .time {
    font-size: 0.95rem;
  }
  svg {
    width: 17px;
    height: 17px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .pop {
    margin-top: 8px;
    max-width: 340px;
    padding: 10px 12px 12px;
    border-radius: 14px;
    background: var(--surface);
    border: 1px solid var(--line);
    box-shadow: var(--shadow-sm);
  }
  .pop:focus {
    outline: none;
  }
  .month {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
  }
  .month strong {
    text-transform: capitalize;
  }
  .nav {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: var(--muted);
  }
  .nav:hover:not(:disabled) {
    background: var(--hover);
    color: var(--text);
  }
  .nav:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .nav svg {
    width: 20px;
    height: 20px;
  }
  .weekdays,
  .days {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 2px;
  }
  .weekdays span {
    text-align: center;
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--muted);
    padding: 2px 0 4px;
  }
  .grid button {
    height: 36px;
    border-radius: 10px;
    font-weight: 600;
    font-size: 0.9rem;
    font-variant-numeric: tabular-nums;
  }
  .days button {
    border-radius: 50%;
    width: 36px;
    justify-self: center;
  }
  .grid button:hover:not(:disabled):not(.sel) {
    background: var(--hover);
  }
  .grid button.today:not(.sel) {
    color: var(--accent);
    box-shadow: inset 0 0 0 1.5px var(--accent);
  }
  .grid button.sel {
    background: var(--text);
    color: var(--on-text);
  }
  .grid button:disabled {
    color: var(--stale);
    font-weight: 400;
    cursor: default;
  }
</style>
