<script lang="ts">
  import { onMount, untrack } from 'svelte'
  import ConsentBanner from './components/ConsentBanner.svelte'
  import FiltersPanel from './components/FiltersPanel.svelte'
  import InstallPrompt from './components/InstallPrompt.svelte'
  import LinePanel from './components/LinePanel.svelte'
  import LinesPanel from './components/LinesPanel.svelte'
  import StatusPanel from './components/StatusPanel.svelte'
  import PlanPanel from './components/PlanPanel.svelte'
  import NearbyPanel from './components/NearbyPanel.svelte'
  import PrivacyPanel from './components/PrivacyPanel.svelte'
  import ReachPanel from './components/ReachPanel.svelte'
  import ReplayPanel from './components/ReplayPanel.svelte'
  import StationPanel from './components/StationPanel.svelte'
  import VehiclePanel from './components/VehiclePanel.svelte'
  import { loadStatic, poll, refreshLine, refreshLive, refreshStatus } from './lib/api'
  import { passes } from './lib/filter'
  import { app, closePanel, feedAgeS, feedDown, filtersActive, navigate, NO_FILTERS, parseUrl, setFilters, syncBack, SLOW_POLL_MS } from './lib/state.svelte'
  import MapView from './Map.svelte'

  const initial = parseUrl()
  app.view = initial.view
  app.filters = initial.filters
  syncBack()

  let staticError = $state<string | null>(null)

  onMount(() => {
    loadStatic().catch((e) => (staticError = (e as Error).message))
    const stopLive = poll(refreshLive)
    const tick = setInterval(() => (app.tick = Date.now()), 1000)
    const onPop = () => {
      const s = parseUrl()
      const wasOpen = app.view.kind !== 'none'
      app.view = s.view
      app.filters = s.filters
      syncBack()
      if (wasOpen && s.view.kind === 'none') (document.querySelector('.maplibregl-canvas') as HTMLElement | null)?.focus()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      // Esc first closes the phone menu, cancels picking a point on the map, then closes the panel.
      if (menuOpen) menuOpen = false
      else if (app.pick) app.pick = null
      // In one planner option, Esc first returns to the list of options.
      else if (app.view.kind === 'plan' && app.view.opt != null) navigate({ ...app.view, opt: null }, { replace: true })
      else if (app.view.kind !== 'none') closePanel()
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
    // With no direction in the URL the first one is shown, as in the panel and route overlay.
    if (v.kind === 'line') return v.dir ?? (app.lineView?.line === v.line ? (app.lineView.directions[0]?.id ?? null) : null)
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
    if (statusOpen) return poll(refreshStatus, SLOW_POLL_MS)
  })

  const age = $derived(feedAgeS())
  const down = $derived(feedDown())
  const freshText = $derived(
    age == null ? 'Načítavam…' : age < 60 ? `pred ${Math.round(age)} s` : `pred ${Math.floor(age / 60)} min`,
  )
  const nFilters = $derived(filtersActive())

  // On phones the nav buttons sit in a menu behind a burger button.
  let menuOpen = $state(false)

  function toggle(kind: 'lines' | 'filters' | 'status' | 'plan' | 'reach' | 'replay') {
    menuOpen = false
    if (app.view.kind === kind) closePanel()
    else if (kind === 'plan') navigate({ kind, from: null, to: null, at: null, opt: null })
    else if (kind === 'reach') navigate({ kind, from: null, at: null, min: 30 })
    else if (kind === 'replay') navigate({ kind, at: null })
    else navigate({ kind })
  }

  // Picking a point belongs to the planner and the reachability map; leaving them cancels the pick.
  $effect(() => {
    if (app.view.kind !== 'plan' && app.view.kind !== 'reach') untrack(() => (app.pick = null))
  })
</script>

<main class:has-panel={app.view.kind !== 'none'}>
  <MapView {activeLine} {selectedDir} />

  <header class="topbar">
    <button class="brand" onclick={() => ((menuOpen = false), closePanel())} aria-label="MHD naživo, zavrieť panel">
      <img class="logo" src="/favicon.svg" alt="" width="22" height="22" />
      <span class="brand-text">MHD <b>naživo</b></span>
    </button>
    {#if app.view.kind === 'replay'}
      <!-- The map shows the past: no live freshness. -->
      <div class="fresh rec" title="Mapa prehráva záznam, nie živé polohy">
        <span class="pulse" aria-hidden="true"></span>
        <span class="fresh-text">Záznam</span>
      </div>
    {:else}
      <div class="fresh" class:bad={down} title="Kedy server naposledy načítal polohy z DPB">
        <span class="pulse" aria-hidden="true"></span>
        <span class="fresh-text"><span class="hide-sm">Aktualizované&nbsp;</span>{freshText}</span>
      </div>
    {/if}
    <button class="burger" onclick={() => (menuOpen = !menuOpen)} aria-expanded={menuOpen} aria-controls="menu" aria-label="Menu">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d={menuOpen ? 'M6 6l12 12M18 6L6 18' : 'M4 7h16M4 12h16M4 17h16'} />
      </svg>
      {#if nFilters && !menuOpen}<span class="count" aria-label="{nFilters} aktívne filtre">{nFilters}</span>{/if}
    </button>
    <nav id="menu" class:open={menuOpen}>
      <button class:active={app.view.kind === 'plan'} onclick={() => toggle('plan')} aria-pressed={app.view.kind === 'plan'} aria-label="Trasa">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="6" r="2.5" /><path d="M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5" /></svg>
        <span>Trasa</span>
      </button>
      <button class:active={app.view.kind === 'reach'} onclick={() => toggle('reach')} aria-pressed={app.view.kind === 'reach'} aria-label="Kam sa dostanem">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="2" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="10" /></svg>
        <span>Dosah</span>
      </button>
      <button class:active={app.view.kind === 'lines'} onclick={() => toggle('lines')} aria-pressed={app.view.kind === 'lines'} aria-label="Linky">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10" /></svg>
        <span>Linky</span>
      </button>
      <button class:active={app.view.kind === 'filters'} onclick={() => toggle('filters')} aria-pressed={app.view.kind === 'filters'} aria-label="Filtre a legenda">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16l-6 7v5l-4 2v-7z" /></svg>
        <span>Filtre</span>
        {#if nFilters}<span class="count" aria-label="{nFilters} aktívne">{nFilters}</span>{/if}
      </button>
      <button class:active={app.view.kind === 'status'} onclick={() => toggle('status')} aria-pressed={app.view.kind === 'status'} aria-label="Stav dopravy">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19V11M12 19V5M19 19v-6" /></svg>
        <span>Stav</span>
      </button>
      <button class:active={app.view.kind === 'replay'} onclick={() => toggle('replay')} aria-pressed={app.view.kind === 'replay'} aria-label="Záznam jázd">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 12a8.5 8.5 0 1 0 2.5-6" /><path d="M3 4v4h4" /><path d="M12 8v4l3 2" /></svg>
        <span>Záznam</span>
      </button>
    </nav>
  </header>
  {#if menuOpen}<div class="menu-backdrop" onpointerdown={() => (menuOpen = false)} aria-hidden="true"></div>{/if}

  {#if (app.view.kind !== 'replay' && (down || (app.fetchError && !app.live))) || staticError}
    <div class="banner" role="alert">
      {#if staticError}
        Nepodarilo sa načítať linky a zastávky ({staticError}).
      {:else if app.live}
        {age != null ? `Polohy vozidiel sa ${Math.floor(age / 60)} min neaktualizovali.` : 'Polohy vozidiel sa neaktualizujú.'}
        Zobrazujeme posledné známe polohy (sivé).
      {:else}
        Polohy vozidiel sa nedajú načítať. Skúšame znova.
      {/if}
    </div>
  {/if}

  {#if app.pick}
    <div class="banner pick" role="status">
      <span>Ťuknite na mapu alebo zastávku: <b>{app.pick === 'from' ? 'odkiaľ' : 'kam'}</b> {app.view.kind === 'reach' ? 'začínate' : 'idete'}.</span>
      <button onclick={() => (app.pick = null)}>Zrušiť</button>
    </div>
  {:else if app.view.kind === 'none' && app.live && !down}
    {#if nFilters && !app.live.vehicles.some((v) => passes(v, app.filters))}
      <button class="hint-pill" onclick={() => setFilters(NO_FILTERS)}
        >Filtre skryli všetky vozidlá · Zrušiť</button
      >
    {:else}
      <button class="hint-pill" onclick={() => navigate({ kind: 'lines' })}>Vyberte vozidlo alebo linku</button>
    {/if}
  {/if}

  {#key app.view.kind === 'line' ? `line-${app.view.line}` : app.view.kind}
    {#if app.view.kind === 'line'}
      <LinePanel line={app.view.line} dir={app.view.dir} />
    {:else if app.view.kind === 'vehicle'}
      <VehiclePanel key={app.view.key} />
    {:else if app.view.kind === 'station'}
      <StationPanel code={app.view.code} stop={app.view.stop} />
    {:else if app.view.kind === 'plan'}
      <PlanPanel from={app.view.from} to={app.view.to} at={app.view.at} opt={app.view.opt} />
    {:else if app.view.kind === 'reach'}
      <ReachPanel from={app.view.from} at={app.view.at} min={app.view.min} />
    {:else if app.view.kind === 'nearby'}
      <NearbyPanel />
    {:else if app.view.kind === 'status'}
      <StatusPanel />
    {:else if app.view.kind === 'lines'}
      <LinesPanel />
    {:else if app.view.kind === 'filters'}
      <FiltersPanel />
    {:else if app.view.kind === 'privacy'}
      <PrivacyPanel />
    {:else if app.view.kind === 'replay'}
      <ReplayPanel at={app.view.at} />
    {/if}
  {/key}

  <InstallPrompt />
  <ConsentBanner />
</main>

<style>
  main {
    position: fixed;
    inset: 0;
    overflow: hidden;
  }
  .topbar {
    position: absolute;
    z-index: 7;
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
  .burger,
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
    flex: none;
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
  .fresh.rec {
    color: var(--text);
    font-weight: 600;
  }
  .fresh.rec .pulse {
    border-radius: 2px;
    background: var(--accent);
    box-shadow: 0 0 0 3px rgba(20, 110, 255, 0.2);
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
  .topbar svg {
    width: 20px;
    height: 20px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .burger {
    display: none;
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
  .banner.pick {
    background: var(--text);
    color: #fff;
    border: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    font-weight: 500;
  }
  .banner.pick button {
    flex: none;
    padding: 6px 12px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.16);
    font-weight: 700;
  }
  .hint-pill {
    position: absolute;
    z-index: 4;
    left: 50%;
    transform: translateX(-50%);
    bottom: calc(52px + env(safe-area-inset-bottom));
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
    .banner {
      left: 10px;
      transform: none;
      width: calc(100% - 76px);
    }
    .brand-text {
      display: none;
    }
    .brand {
      padding: 0 12px;
    }
    .hide-sm {
      display: none;
    }
    .burger {
      display: grid;
      place-items: center;
      position: relative;
      margin-left: auto;
      width: 46px;
    }
    .burger .count {
      position: absolute;
      top: 3px;
      right: 3px;
    }
    /* The nav drops down from the burger, under the top bar's right edge. */
    nav {
      display: none;
      position: absolute;
      top: 54px;
      right: 0;
      height: auto;
      min-width: 200px;
      flex-direction: column;
      padding: 6px;
      box-shadow: var(--shadow);
    }
    nav.open {
      display: flex;
    }
    nav button {
      height: 46px;
      font-size: 1rem;
      gap: 12px;
    }
    nav button .count {
      margin-left: auto;
    }
    .menu-backdrop {
      position: absolute;
      inset: 0;
      z-index: 6;
    }
  }
</style>
