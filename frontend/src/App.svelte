<script lang="ts">
  import { onMount, untrack } from 'svelte'
  import FiltersPanel from './components/FiltersPanel.svelte'
  import LinePanel from './components/LinePanel.svelte'
  import LinesPanel from './components/LinesPanel.svelte'
  import StatusPanel from './components/StatusPanel.svelte'
  import StopPanel from './components/StopPanel.svelte'
  import VehiclePanel from './components/VehiclePanel.svelte'
  import { loadStatic, poll, refreshLine, refreshLive, refreshStatus } from './lib/api'
  import { app, closePanel, feedAgeS, feedDown, filtersActive, navigate, parseUrl } from './lib/state.svelte'
  import MapView from './Map.svelte'

  const initial = parseUrl()
  app.view = initial.view
  app.filters = initial.filters

  let staticError = $state<string | null>(null)

  onMount(() => {
    loadStatic().catch((e) => (staticError = (e as Error).message))
    const stopLive = poll(refreshLive)
    const tick = setInterval(() => (app.tick = Date.now()), 1000)
    const onPop = () => {
      const s = parseUrl()
      app.view = s.view
      app.filters = s.filters
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && app.view.kind !== 'none') closePanel()
    }
    addEventListener('popstate', onPop)
    addEventListener('keydown', onKey)
    return () => {
      stopLive()
      clearInterval(tick)
      removeEventListener('popstate', onPop)
      removeEventListener('keydown', onKey)
    }
  })

  // The line whose route is drawn: the open line, or the open vehicle's line.
  const activeLine = $derived.by(() => {
    const v = app.view
    if (v.kind === 'line') return v.line
    if (v.kind === 'vehicle') return app.live?.vehicles.find((x) => x.key === v.key)?.line ?? null
    return null
  })
  const selectedDir = $derived.by(() => {
    const v = app.view
    if (v.kind === 'line') return v.dir
    if (v.kind === 'vehicle') return app.live?.vehicles.find((x) => x.key === v.key)?.dir ?? null
    return null
  })

  $effect(() => {
    const line = activeLine
    app.wantLine = line
    untrack(() => {
      if (app.lineView?.line !== line) {
        app.lineView = null
        app.lineViewError = null
      }
    })
    if (line) return poll(() => refreshLine(line))
  })

  const statusOpen = $derived(app.view.kind === 'status')
  $effect(() => {
    if (statusOpen) return poll(refreshStatus)
  })

  const age = $derived(feedAgeS())
  const down = $derived(feedDown())
  const freshText = $derived(
    age == null ? 'Načítavam…' : age < 60 ? `pred ${Math.round(age)} s` : `pred ${Math.floor(age / 60)} min`,
  )
  const nFilters = $derived(filtersActive())

  function toggle(kind: 'lines' | 'filters' | 'status') {
    if (app.view.kind === kind) closePanel()
    else navigate({ kind })
  }
</script>

<main class:has-panel={app.view.kind !== 'none'}>
  <MapView {activeLine} {selectedDir} />

  <header class="topbar">
    <button class="brand" onclick={closePanel} aria-label="MHD naživo, zavrieť panel">
      <span class="logo" aria-hidden="true"></span>
      <span class="brand-text">MHD <b>naživo</b></span>
    </button>
    <div class="fresh" class:bad={down} role="status" title="Kedy server naposledy načítal polohy z DPB">
      <span class="pulse" aria-hidden="true"></span>
      <span class="fresh-text"><span class="hide-sm">Aktualizované&nbsp;</span>{freshText}</span>
    </div>
    <nav>
      <button class:active={app.view.kind === 'lines'} onclick={() => toggle('lines')} aria-pressed={app.view.kind === 'lines'}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10" /></svg>
        <span>Linky</span>
      </button>
      <button class:active={app.view.kind === 'filters'} onclick={() => toggle('filters')} aria-pressed={app.view.kind === 'filters'}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16l-6 7v5l-4 2v-7z" /></svg>
        <span>Filtre</span>
        {#if nFilters}<span class="count" aria-label="{nFilters} aktívne">{nFilters}</span>{/if}
      </button>
      <button class:active={app.view.kind === 'status'} onclick={() => toggle('status')} aria-pressed={app.view.kind === 'status'}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19V11M12 19V5M19 19v-6" /></svg>
        <span>Stav</span>
      </button>
    </nav>
  </header>

  {#if down || (app.fetchError && !app.live) || staticError}
    <div class="banner" role="alert">
      {#if staticError}
        Nepodarilo sa načítať linky a zastávky ({staticError}).
      {:else if app.live}
        Polohy vozidiel sa {age != null ? `${Math.floor(age / 60)} min` : ''} neaktualizovali. Zobrazujeme posledné známe, sivou.
      {:else}
        Polohy vozidiel sa nedajú načítať. Skúšame znova.
      {/if}
    </div>
  {/if}

  {#if app.view.kind === 'none' && app.live && !down}
    <button class="hint-pill" onclick={() => navigate({ kind: 'lines' })}>Ťuknite na vozidlo alebo vyberte linku</button>
  {/if}

  {#key app.view.kind === 'line' ? `line-${app.view.line}` : app.view.kind}
    {#if app.view.kind === 'line'}
      <LinePanel line={app.view.line} dir={app.view.dir} />
    {:else if app.view.kind === 'vehicle'}
      <VehiclePanel key={app.view.key} />
    {:else if app.view.kind === 'stop'}
      <StopPanel id={app.view.id} />
    {:else if app.view.kind === 'status'}
      <StatusPanel />
    {:else if app.view.kind === 'lines'}
      <LinesPanel />
    {:else if app.view.kind === 'filters'}
      <FiltersPanel />
    {/if}
  {/key}
</main>

<style>
  main {
    position: fixed;
    inset: 0;
    overflow: hidden;
  }
  .topbar {
    position: absolute;
    z-index: 6;
    top: max(10px, env(safe-area-inset-top));
    left: 10px;
    right: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
    pointer-events: none;
  }
  .topbar > * {
    pointer-events: auto;
  }
  .brand,
  .fresh,
  nav {
    background: var(--surface);
    box-shadow: var(--shadow-sm);
    border-radius: 12px;
    height: 46px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 14px 0 10px;
    font-size: 1.05rem;
    white-space: nowrap;
  }
  .logo {
    width: 22px;
    height: 22px;
    border-radius: 7px;
    background: linear-gradient(135deg, #d7263d, #ef6c28);
    box-shadow: inset 0 0 0 5px rgba(255, 255, 255, 0.0);
    position: relative;
  }
  .logo::after {
    content: '';
    position: absolute;
    inset: 6px;
    border-radius: 50%;
    background: #fff;
  }
  .fresh {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    font-size: 0.85rem;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .pulse {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--ok);
    box-shadow: 0 0 0 3px rgba(26, 152, 80, 0.2);
  }
  .fresh.bad {
    color: var(--bad-text);
    font-weight: 600;
  }
  .fresh.bad .pulse {
    background: var(--bad);
    box-shadow: 0 0 0 3px rgba(215, 38, 61, 0.2);
  }
  nav {
    margin-left: auto;
    display: flex;
    padding: 3px;
    gap: 2px;
  }
  nav button {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 12px;
    border-radius: 9px;
    font-weight: 600;
    font-size: 0.9rem;
    position: relative;
  }
  nav button:hover {
    background: var(--hover);
  }
  nav button.active {
    background: var(--text);
    color: #fff;
  }
  nav svg {
    width: 20px;
    height: 20px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .count {
    min-width: 18px;
    height: 18px;
    border-radius: 9px;
    background: var(--accent);
    color: #fff;
    font-size: 0.72rem;
    display: grid;
    place-items: center;
    padding: 0 4px;
  }
  .banner {
    position: absolute;
    z-index: 6;
    top: calc(max(10px, env(safe-area-inset-top)) + 54px);
    left: 50%;
    transform: translateX(-50%);
    width: min(560px, calc(100% - 20px));
    background: var(--bad-bg);
    color: var(--bad-text);
    border: 1px solid #f3b8c0;
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 600;
    font-size: 0.9rem;
    box-shadow: var(--shadow-sm);
  }
  .hint-pill {
    position: absolute;
    z-index: 4;
    left: 50%;
    transform: translateX(-50%);
    bottom: calc(24px + env(safe-area-inset-bottom));
    background: var(--text);
    color: #fff;
    padding: 12px 18px;
    border-radius: 999px;
    font-weight: 600;
    font-size: 0.92rem;
    box-shadow: var(--shadow);
    white-space: nowrap;
  }

  @media (min-width: 768px) {
    main.has-panel .banner {
      left: calc(50% + 200px);
      width: min(520px, calc(100% - 430px));
    }
  }
  @media (max-width: 767.98px) {
    .brand-text {
      display: none;
    }
    .brand {
      padding: 0 12px;
    }
    .hide-sm {
      display: none;
    }
    nav button {
      padding: 0 10px;
    }
  }
  @media (max-width: 400px) {
    nav button span:not(.count) {
      display: none;
    }
    nav button {
      padding: 0 12px;
    }
  }
</style>
