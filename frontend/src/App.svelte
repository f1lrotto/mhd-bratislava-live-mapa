<script lang="ts">
  import { onMount, untrack } from 'svelte'
  import AccountPanel from './components/AccountPanel.svelte'
  import ConsentBanner from './components/ConsentBanner.svelte'
  import FavoritesPanel from './components/FavoritesPanel.svelte'
  import FiltersPanel from './components/FiltersPanel.svelte'
  import InstallPrompt from './components/InstallPrompt.svelte'
  import LinePanel from './components/LinePanel.svelte'
  import LinesPanel from './components/LinesPanel.svelte'
  import StatusPanel from './components/StatusPanel.svelte'
  import PlanPanel from './components/PlanPanel.svelte'
  import NearbyPanel from './components/NearbyPanel.svelte'
  import NewsPanel from './components/NewsPanel.svelte'
  import PrivacyPanel from './components/PrivacyPanel.svelte'
  import ReachPanel from './components/ReachPanel.svelte'
  import ReliabilityPanel from './components/ReliabilityPanel.svelte'
  import ReplayPanel from './components/ReplayPanel.svelte'
  import SpeedCard from './components/SpeedCard.svelte'
  import StationPanel from './components/StationPanel.svelte'
  import VehiclePanel from './components/VehiclePanel.svelte'
  import { standalone, track } from './lib/analytics.svelte'
  import { loadStatic, poll, refreshLine, refreshLive, refreshSpeeds, refreshStatus, speedQuery } from './lib/api'
  import { passes } from './lib/filter'
  import { t } from './lib/i18n'
  import { prefs } from './lib/prefs.svelte'
  import { loadProfile, profile, setLang } from './lib/profile.svelte'
  import { app, closePanel, feedAgeS, feedDown, filtersActive, navigate, NO_FILTERS, parseUrl, setFilters, syncBack, SLOW_POLL_MS } from './lib/state.svelte'
  import MapView from './Map.svelte'

  const initial = parseUrl()
  app.view = initial.view
  app.filters = initial.filters
  app.speed = initial.speed
  syncBack()

  let staticError = $state<string | null>(null)

  onMount(() => {
    loadStatic().catch((e) => (staticError = (e as Error).message))
    // The installed app opens to the user's favourites, unless they chose the map in their profile
    // (a link to a panel still opens that panel).
    const launch = standalone && app.view.kind === 'none'
    // loadProfile() resolves once an attempt succeeds or every retry failed.
    loadProfile().then(() => {
      const start = profile.preferences.start ?? 'favorites'
      if (launch && profile.user && start === 'favorites' && app.view.kind === 'none') {
        navigate({ kind: 'favorites' }, { replace: true })
        track('opened_to_favorites')
      }
    })
    // Back in the app (another tab, the phone unlocked): favourites pinned on another device show up.
    const onVisible = () => !document.hidden && profile.loaded && loadProfile()
    document.addEventListener('visibilitychange', onVisible)
    const stopLive = poll(refreshLive)
    const tick = setInterval(() => (app.tick = Date.now()), 1000)
    const onPop = () => {
      const s = parseUrl()
      const wasOpen = app.view.kind !== 'none'
      app.view = s.view
      app.filters = s.filters
      app.speed = s.speed
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
      document.removeEventListener('visibilitychange', onVisible)
    }
  })

  // The line whose route is drawn: the open line, or the open vehicle's line.
  const activeLine = $derived.by(() => {
    const v = app.view
    if (v.kind === 'line' || v.kind === 'reliability') return v.line
    if (v.kind === 'vehicle') return app.live?.vehicles.find((x) => x.key === v.key)?.line ?? null
    return null
  })
  const selectedDir = $derived.by(() => {
    const v = app.view
    // With no direction in the URL the first one is shown, as in the panel and route overlay.
    if (v.kind === 'line' || v.kind === 'reliability') return v.dir ?? (app.lineView?.line === v.line ? (app.lineView.directions[0]?.id ?? null) : null)
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

  const speedQ = $derived(app.speed ? speedQuery(app.speed) : null)
  $effect(() => {
    if (speedQ) return poll(refreshSpeeds, SLOW_POLL_MS)
  })

  const age = $derived(feedAgeS())
  const down = $derived(feedDown())
  const freshText = $derived.by(() => {
    if (age == null) return t('Načítavam…', 'Loading…')
    const d = age < 60 ? `${Math.round(age)} s` : `${Math.floor(age / 60)} min`
    return t(`pred ${d}`, `${d} ago`)
  })
  const nFilters = $derived(filtersActive())

  // On phones the nav buttons sit in a menu behind a burger button.
  let menuOpen = $state(false)

  function toggle(kind: 'favorites' | 'account' | 'lines' | 'filters' | 'status' | 'plan' | 'reach' | 'replay') {
    menuOpen = false
    if (app.view.kind === kind) closePanel()
    else if (kind === 'plan') navigate({ kind, from: null, to: null, at: null, opt: null })
    else if (kind === 'reach') navigate({ kind, from: null, at: null, min: 30 })
    else if (kind === 'replay') navigate({ kind, at: null })
    else navigate({ kind })
  }

  // The page's language follows the preference (screen readers, hyphenation, the browser's translate offer).
  $effect(() => {
    document.documentElement.lang = prefs.lang
  })

  function toggleLang() {
    menuOpen = false
    // Signed in, the profile keeps the choice too; offline, this device still switches.
    setLang(prefs.lang === 'en' ? 'sk' : 'en').catch(() => {})
  }

  // Picking a point belongs to the planner and the reachability map; leaving them cancels the pick.
  $effect(() => {
    if (app.view.kind !== 'plan' && app.view.kind !== 'reach') untrack(() => (app.pick = null))
  })
</script>

<main class:has-panel={app.view.kind !== 'none'}>
  <MapView {activeLine} {selectedDir} />

  <header class="topbar">
    <button class="brand" onclick={() => ((menuOpen = false), closePanel())} aria-label={t('MHD naživo, zavrieť panel', 'MHD naživo, close panel')}>
      <img class="logo" src="/favicon.svg" alt="" width="22" height="22" />
      <span class="brand-text">MHD <b>naživo</b></span>
    </button>
    {#if app.view.kind === 'replay'}
      <!-- The map shows the past: no live freshness. -->
      <div class="fresh rec" title={t('Mapa prehráva záznam, nie živé polohy', 'The map is playing back a recording, not live positions')}>
        <span class="pulse" aria-hidden="true"></span>
        <span class="fresh-text">{t('Záznam', 'Replay')}</span>
      </div>
    {:else}
      <div class="fresh" class:bad={down} title={t('Kedy server naposledy načítal polohy z DPB', 'When the server last loaded positions from DPB')}>
        <span class="pulse" aria-hidden="true"></span>
        <span class="fresh-text"><span class="hide-sm">{t('Aktualizované', 'Updated')}&nbsp;</span>{freshText}</span>
      </div>
    {/if}
    <button class="burger" onclick={() => (menuOpen = !menuOpen)} aria-expanded={menuOpen} aria-controls="menu" aria-label="Menu">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d={menuOpen ? 'M6 6l12 12M18 6L6 18' : 'M4 7h16M4 12h16M4 17h16'} />
      </svg>
      {#if nFilters && !menuOpen}<span class="count" aria-label={t(`${nFilters} aktívne filtre`, `${nFilters} active filters`)}>{nFilters}</span>{/if}
    </button>
    <nav id="menu" class:open={menuOpen}>
      <button class:active={app.view.kind === 'favorites'} onclick={() => toggle('favorites')} aria-pressed={app.view.kind === 'favorites'} aria-label={t('Obľúbené', 'Favourites')} title={t('Obľúbené', 'Favourites')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l2.6 5.3 5.9.9-4.25 4.1 1 5.8L12 16.9l-5.25 2.7 1-5.8L3.5 9.7l5.9-.9z" /></svg>
        <span class="label">{t('Obľúbené', 'Favourites')}</span>
      </button>
      <button class:active={app.view.kind === 'plan'} onclick={() => toggle('plan')} aria-pressed={app.view.kind === 'plan'} aria-label={t('Trasa', 'Trip planner')} title={t('Trasa', 'Trip planner')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="6" r="2.5" /><path d="M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5" /></svg>
        <span class="label">{t('Trasa', 'Trip')}</span>
      </button>
      <button class:active={app.view.kind === 'reach'} onclick={() => toggle('reach')} aria-pressed={app.view.kind === 'reach'} aria-label={t('Kam sa dostanem', 'Where can I get to')} title={t('Kam sa dostanem', 'Where can I get to')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="2" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="10" /></svg>
        <span class="label">{t('Dosah', 'Reach')}</span>
      </button>
      <button class:active={app.view.kind === 'lines'} onclick={() => toggle('lines')} aria-pressed={app.view.kind === 'lines'} aria-label={t('Linky', 'Lines')} title={t('Linky', 'Lines')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10" /></svg>
        <span class="label">{t('Linky', 'Lines')}</span>
      </button>
      <button class:active={app.view.kind === 'filters'} onclick={() => toggle('filters')} aria-pressed={app.view.kind === 'filters'} aria-label={t('Filtre a legenda', 'Filters and legend')} title={t('Filtre a legenda', 'Filters and legend')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16l-6 7v5l-4 2v-7z" /></svg>
        <span class="label">{t('Filtre', 'Filters')}</span>
        {#if nFilters}<span class="count" aria-label={t(`${nFilters} aktívne`, `${nFilters} active`)}>{nFilters}</span>{/if}
      </button>
      <button class:active={app.view.kind === 'status'} onclick={() => toggle('status')} aria-pressed={app.view.kind === 'status'} aria-label={t('Stav dopravy', 'Service status')} title={t('Stav dopravy', 'Service status')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19V11M12 19V5M19 19v-6" /></svg>
        <span class="label">{t('Stav', 'Status')}</span>
      </button>
      <button class:active={app.view.kind === 'replay'} onclick={() => toggle('replay')} aria-pressed={app.view.kind === 'replay'} aria-label={t('Záznam jázd', 'Replay of past journeys')} title={t('Záznam jázd', 'Replay of past journeys')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 12a8.5 8.5 0 1 0 2.5-6" /><path d="M3 4v4h4" /><path d="M12 8v4l3 2" /></svg>
        <span class="label">{t('Záznam', 'Replay')}</span>
      </button>
      <!-- The profile: the user's initial when signed in. Icon only on wide screens, labelled in the phone menu. -->
      <button
        class="acct"
        class:active={app.view.kind === 'account'}
        onclick={() => toggle('account')}
        aria-pressed={app.view.kind === 'account'}
        aria-label={profile.user ? `${t('Profil', 'Profile')} (${profile.user.email})` : profile.failed ? t('Profil', 'Profile') : t('Prihlásiť sa', 'Sign in')}
        title={profile.user ? `${t('Profil', 'Profile')}: ${profile.user.email}` : profile.failed ? t('Profil', 'Profile') : t('Prihlásiť sa', 'Sign in')}
      >
        {#if profile.user}
          <span class="initial" aria-hidden="true">{profile.user.email[0].toUpperCase()}</span>
        {:else}
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></svg>
        {/if}
        <span class="label acct-label">{profile.user || profile.failed ? t('Profil', 'Profile') : t('Prihlásiť sa', 'Sign in')}</span>
      </button>
      <!-- Named in the language it switches to, so a visitor who can't read the current one finds it. -->
      <button
        onclick={toggleLang}
        lang={prefs.lang === 'en' ? 'sk' : 'en'}
        aria-label={prefs.lang === 'en' ? 'Slovenčina' : 'English'}
        title={prefs.lang === 'en' ? 'Prepnúť do slovenčiny' : 'Switch to English'}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z" /></svg>
        <span class="lang-short" aria-hidden="true">{prefs.lang === 'en' ? 'SK' : 'EN'}</span>
        <span class="lang-long" aria-hidden="true">{prefs.lang === 'en' ? 'Slovenčina' : 'English'}</span>
      </button>
    </nav>
  </header>
  {#if menuOpen}<div class="menu-backdrop" onpointerdown={() => (menuOpen = false)} aria-hidden="true"></div>{/if}

  {#if (app.view.kind !== 'replay' && (down || (app.fetchError && !app.live))) || staticError}
    <div class="banner" role="alert">
      {#if staticError}
        {t(`Nepodarilo sa načítať linky a zastávky (${staticError}).`, `Couldn't load the lines and stops (${staticError}).`)}
      {:else if app.live}
        {age != null
          ? t(`Polohy vozidiel sa ${Math.floor(age / 60)} min neaktualizovali.`, `Vehicle positions haven't updated for ${Math.floor(age / 60)} min.`)
          : t('Polohy vozidiel sa neaktualizujú.', "Vehicle positions aren't updating.")}
        {t('Zobrazujeme posledné známe polohy (sivé).', 'Showing the last known positions (grey).')}
      {:else}
        {t('Polohy vozidiel sa nedajú načítať. Skúšame znova.', "Vehicle positions can't be loaded. Trying again.")}
      {/if}
    </div>
  {/if}

  {#if app.pick}
    <div class="banner pick" role="status">
      {#if prefs.lang === 'en'}
        <span>Tap the map or a stop: where you're <b>{app.pick === 'from' ? (app.view.kind === 'reach' ? 'starting' : 'starting from') : 'going'}</b>.</span>
      {:else}
        <span>Ťuknite na mapu alebo zastávku: <b>{app.pick === 'from' ? 'odkiaľ' : 'kam'}</b> {app.view.kind === 'reach' ? 'začínate' : 'idete'}.</span>
      {/if}
      <button onclick={() => (app.pick = null)}>{t('Zrušiť', 'Cancel')}</button>
    </div>
  {:else if app.view.kind === 'none' && app.live && !down}
    {#if nFilters && !app.live.vehicles.some((v) => passes(v, app.filters))}
      <button class="hint-pill" onclick={() => setFilters(NO_FILTERS)}
        >{t('Filtre skryli všetky vozidlá · Zrušiť', 'Filters hide every vehicle · Clear')}</button
      >
    {:else}
      <button class="hint-pill" onclick={() => navigate({ kind: 'lines' })}>{t('Vyberte vozidlo alebo linku', 'Pick a vehicle or a line')}</button>
    {/if}
  {/if}

  {#key app.view.kind === 'line' || app.view.kind === 'reliability' ? `${app.view.kind}-${app.view.line}` : app.view.kind}
    {#if app.view.kind === 'line'}
      <LinePanel line={app.view.line} dir={app.view.dir} />
    {:else if app.view.kind === 'reliability'}
      <ReliabilityPanel line={app.view.line} dir={app.view.dir} weekends={app.view.weekends} />
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
    {:else if app.view.kind === 'favorites'}
      <FavoritesPanel />
    {:else if app.view.kind === 'account'}
      <AccountPanel />
    {:else if app.view.kind === 'news'}
      <NewsPanel />
    {/if}
  {/key}

  {#if app.speed}<SpeedCard />{/if}

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
    color: var(--on-text);
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
  .burger,
  .lang-long {
    display: none;
  }
  .initial {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: var(--text);
    color: var(--on-text);
    display: grid;
    place-items: center;
    font-size: 0.78rem;
    font-weight: 700;
  }
  nav button.active .initial {
    background: var(--surface);
    color: var(--text);
  }
  @media (min-width: 768px) {
    .acct-label {
      display: none;
    }
    nav .acct {
      padding: 0 10px;
    }
  }
  /* Narrow desktops: the nav's eight buttons fit as icons only (each has a tooltip). */
  @media (min-width: 768px) and (max-width: 1279.98px) {
    nav .label {
      display: none;
    }
    nav button {
      padding: 0 11px;
    }
  }
  /* Narrow desktops: the nav needs the room of "Aktualizované". */
  @media (max-width: 1023.98px) {
    .hide-sm {
      display: none;
    }
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
    border: 1px solid var(--bad-line);
    border-radius: 12px;
    padding: 10px 14px;
    font-weight: 600;
    font-size: 0.9rem;
    box-shadow: var(--shadow-sm);
  }
  .banner.pick {
    background: var(--text);
    color: var(--on-text);
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
    background: rgba(128, 128, 128, 0.28);
    font-weight: 700;
  }
  .hint-pill {
    position: absolute;
    z-index: 4;
    left: 50%;
    transform: translateX(-50%);
    bottom: calc(52px + env(safe-area-inset-bottom));
    background: var(--text);
    color: var(--on-text);
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
    .hide-sm,
    .lang-short {
      display: none;
    }
    .lang-long {
      display: inline;
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
