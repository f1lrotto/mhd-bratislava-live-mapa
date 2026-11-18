<script lang="ts">
  import { drawnPlanOption } from '../lib/api'
  import { compareLines, hm } from '../lib/format'
  import { count, t } from '../lib/i18n'
  import { duration, routeExtra, routeHops, SLOTS, slotTime, SPEED_COLORS, speedColor, speedLabels, timeSlot } from '../lib/speeds'
  import { app, setSpeed } from '../lib/state.svelte'
  import LineBadge from './LineBadge.svelte'

  const kindText = (k: 'workday' | 'saturday' | 'sunday') =>
    ({ workday: t('pracovné dni', 'working days'), saturday: t('soboty', 'Saturdays'), sunday: t('nedele a sviatky', 'Sundays and holidays') })[k]

  const s = $derived(app.speed!)
  // The data on screen may still be another view's while this one loads.
  const data = $derived(app.speedData?.view === s.view ? app.speedData : null)
  const nowSlot = $derived(timeSlot(hm(new Date(app.tick + app.skewMs).toISOString())))
  // The slider follows the hand while dragged; the overlay loads when it's let go.
  let dragging = $state<number | null>(null)
  const slot = $derived(dragging ?? (s.view === 'typical' && s.at ? timeSlot(s.at) : nowSlot))

  function pickSlot(v: number) {
    dragging = null
    setSpeed({ view: 'typical', at: v === nowSlot ? null : slotTime(v) })
  }

  // In the planner the overlay shows the drawn option only: its hops add up to the route's delay.
  const routeOpt = $derived(drawnPlanOption())
  const route = $derived(routeOpt && data ? routeExtra(routeHops(routeOpt), data) : null)
  const extraMin = $derived(route ? Math.round(route.extraS / 60) : 0)

  const hop = $derived.by(() => {
    const k = app.speedHop
    const g = k ? app.speedGeometry?.hops.find((h) => h.k === k) : null
    if (!k || !g) return null
    const [from, to] = k.split('>')
    return {
      from: app.stops[from]?.name ?? from,
      to: app.stops[to]?.name ?? to,
      lines: [...g.lines].sort(compareLines),
      m: g.m,
      run: data?.hops.find((h) => h.k === k) ?? null,
    }
  })
</script>

<section class="speed-card" aria-label={t('Rýchlosť jazdy', 'Running speed')}>
  <header>
    <strong>{t('Rýchlosť jazdy', 'Running speed')}</strong>
    <button class="close" onclick={() => setSpeed(null)} aria-label={t('Vypnúť rýchlosť jazdy', 'Turn off running speed')}>
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
        ><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" /></svg
      >
    </button>
  </header>
  <div class="seg" role="group" aria-label={t('Obdobie', 'Period')}>
    <button aria-pressed={s.view === 'live'} onclick={() => setSpeed({ view: 'live' })}>{t('Naživo', 'Live')}</button>
    <button aria-pressed={s.view === 'typical'} onclick={() => s.view !== 'typical' && setSpeed({ view: 'typical', at: null })}
      >{t('Bežne', 'Typical')}</button
    >
  </div>
  {#if s.view === 'typical'}
    <label class="time">
      <span>{t('o', 'at')} {slotTime(slot)}{slot === nowSlot ? t(' (teraz)', ' (now)') : ''}</span>
      <input
        type="range"
        min="0"
        max={SLOTS - 1}
        value={slot}
        oninput={(e) => (dragging = +e.currentTarget.value)}
        onchange={(e) => pickSlot(+e.currentTarget.value)}
        aria-label={t('Čas dňa', 'Time of day')}
        aria-valuetext={slotTime(slot)}
      />
    </label>
  {/if}

  <div class="scale" aria-hidden="true">
    {#each SPEED_COLORS as c, i (c)}
      <span><i style:background={c}></i>{speedLabels()[i]}</span>
    {/each}
  </div>
  <p class="note">
    {#if app.speedError && !data}
      {t(`Nepodarilo sa načítať (${app.speedError}).`, `Couldn't load (${app.speedError}).`)}
    {:else if !data}
      {t('Načítavam…', 'Loading…')}
    {:else if data.view === 'live'}
      {#if data.hops.length}
        {t(
          `Čas jazdy medzi zastávkami za posledných ${data.windowS / 60} min oproti cestovnému poriadku.`,
          `Running time between stops over the last ${data.windowS / 60} min compared with the timetable.`,
        )}
      {:else}
        {t(`Za posledných ${data.windowS / 60} min sme zatiaľ nezmerali žiadnu jazdu.`, `No runs measured in the last ${data.windowS / 60} min yet.`)}
      {/if}
    {:else if !data.days}
      {t('Na porovnanie zatiaľ nemáme dosť dní histórie.', "We don't have enough days of history to compare yet.")}
    {:else}
      {t('Bežný čas jazdy', 'Typical running time')}: {kindText(data.kind)} {data.from}–{data.to}, {t('priemer z', 'average of')}
      {count(data.days, ['dňa', 'dní', 'dní'], ['day', 'days'])}.
    {/if}
  </p>

  {#if routeOpt}
    <div class="route" role="status">
      {#if !route}
        <span class="muted">{t('Vaša trasa…', 'Your route…')}</span>
      {:else if !route.measured}
        <span class="muted">{t('Na vašej trase zatiaľ nemáme namerané jazdy.', 'No runs measured on your route yet.')}</span>
      {:else}
        <span class="dot" style:background={speedColor(route.ratio)}></span>
        <span>
          {data?.view === 'live' ? t('Vaša trasa teraz', 'Your route now') : t('Vaša trasa zvyčajne', 'Your route usually')}
          <b
            >{extraMin > 0
              ? t(`o ${extraMin} min pomalšie`, `${extraMin} min slower`)
              : extraMin < 0
                ? t(`o ${-extraMin} min rýchlejšie`, `${-extraMin} min faster`)
                : t('podľa cestovného poriadku', 'as timetabled')}</b
          >
          <span class="muted small"
            >· {t(`údaje z ${route.measured} z ${route.total} úsekov`, `data from ${route.measured} of ${route.total} sections`)}</span
          >
        </span>
      {/if}
    </div>
  {/if}

  {#if hop}
    <div class="hop">
      <div class="hop-head">
        <span class="hop-name">{hop.from} → {hop.to}</span>
        <button class="close sm" onclick={() => (app.speedHop = null)} aria-label={t('Zrušiť výber úseku', 'Deselect the section')}>
          <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"
            ><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" /></svg
          >
        </button>
      </div>
      <div class="lines">
        {#each hop.lines.slice(0, 8) as l (l)}<LineBadge line={l} size="sm" />{/each}
        {#if hop.lines.length > 8}<span class="muted small">+{hop.lines.length - 8}</span>{/if}
        <span class="muted small">{hop.m < 1000 ? `${hop.m} m` : `${(hop.m / 1000).toFixed(1)} km`}</span>
      </div>
      {#if hop.run}
        <p class="hop-time">
          <span class="dot" style:background={speedColor(hop.run.r)}></span>
          <span
            ><b>{duration(hop.run.a)}</b> {t('namiesto', 'instead of')} {duration(hop.run.s)}
            <span class="muted">· {count(hop.run.n, ['jazda', 'jazdy', 'jázd'], ['run', 'runs'])}</span></span
          >
        </p>
      {:else if data}
        <p class="muted small">{data.view === 'live'
            ? t('Za poslednú polhodinu tadiaľ nič neprešlo.', 'Nothing has run here in the last half hour.')
            : t('V tomto čase tu nemáme dosť jázd.', "We don't have enough runs here at this time.")}</p>
      {/if}
    </div>
  {:else if data?.hops.length && !routeOpt}
    <p class="muted small">{t('Ťuknite na úsek pre podrobnosti.', 'Tap a section for details.')}</p>
  {/if}
</section>

<style>
  .speed-card {
    position: absolute;
    z-index: 4;
    top: calc(max(10px, env(safe-area-inset-top)) + 56px);
    left: 12px;
    width: 300px;
    background: var(--surface);
    border-radius: 14px;
    box-shadow: var(--shadow-sm);
    padding: 8px 12px 10px;
    font-size: 0.88rem;
  }
  :global(main.has-panel) .speed-card {
    left: 408px;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .close {
    width: 32px;
    height: 32px;
    margin-right: -6px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: var(--muted);
  }
  .close.sm {
    width: 26px;
    height: 26px;
    margin: -2px -4px 0 0;
    flex: none;
  }
  .close:hover {
    background: var(--hover);
    color: var(--text);
  }
  .seg {
    display: flex;
    background: var(--chip);
    border-radius: 9px;
    padding: 3px;
    margin: 4px 0 6px;
  }
  .seg button {
    flex: 1;
    height: 32px;
    border-radius: 7px;
    font-weight: 600;
  }
  .seg button[aria-pressed='true'] {
    background: var(--surface);
    box-shadow: 0 1px 3px rgba(16, 24, 40, 0.16);
  }
  .time {
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .time span {
    flex: none;
    min-width: 5.6em;
  }
  .time input {
    flex: 1;
    min-width: 0;
    accent-color: var(--text);
  }
  .scale {
    display: flex;
    margin-top: 6px;
  }
  .scale span {
    flex: 1;
    font-size: 0.74rem;
    color: var(--muted);
    text-align: center;
  }
  .scale i {
    display: block;
    height: 6px;
    margin: 0 1px 3px;
  }
  .scale span:first-child i {
    border-radius: 3px 0 0 3px;
  }
  .scale span:last-child i {
    border-radius: 0 3px 3px 0;
  }
  /* Two lines from the start, so the card doesn't grow when its data arrives (the map fits a
     planned route below it). */
  .note {
    margin: 6px 0 0;
    font-size: 0.8rem;
    line-height: 1.35;
    min-height: 2.7em;
  }
  .route {
    min-height: calc(2.8em + 9px);
    display: flex;
    align-items: baseline;
    gap: 8px;
    border-top: 1px solid var(--hover);
    margin-top: 8px;
    padding-top: 8px;
  }
  .route .dot {
    transform: translateY(1px);
  }
  .hop {
    border-top: 1px solid var(--hover);
    margin-top: 8px;
    padding-top: 8px;
  }
  .hop-head {
    display: flex;
    gap: 6px;
    align-items: flex-start;
  }
  .hop-name {
    flex: 1;
    font-weight: 600;
  }
  .lines {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
    margin: 4px 0;
  }
  .hop-time {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 4px 0 0;
  }
  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex: none;
  }
  p.muted {
    margin: 6px 0 0;
  }

  @media (max-width: 767.98px) {
    .speed-card {
      top: calc(max(10px, env(safe-area-inset-top)) + 54px);
      left: 10px;
      width: auto;
      right: 62px;
      max-width: 340px;
    }
    /* Under the top bar and over a half-height sheet: only the controls and a tapped hop. */
    :global(main.has-panel) .speed-card {
      left: 10px;
    }
    :global(main.has-panel) .speed-card .note,
    :global(main.has-panel) .speed-card > p.muted {
      display: none;
    }
  }
</style>
