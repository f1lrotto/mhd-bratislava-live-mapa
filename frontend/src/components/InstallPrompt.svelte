<script module lang="ts">
  interface BeforeInstallPromptEvent extends Event {
    prompt(): Promise<void>
    userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
  }

  // Chromium fires this once the app can be installed; listened to at import, before the app
  // mounts, so the event isn't missed. Holding it back keeps the browser's own banner away.
  let deferred = $state<BeforeInstallPromptEvent | null>(null)
  addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()
    deferred = e as BeforeInstallPromptEvent
  })
</script>

<script lang="ts">
  import { onMount } from 'svelte'
  import { ANALYTICS, consent, standalone, track } from '../lib/analytics.svelte'
  import { t } from '../lib/i18n'

  // "Teraz nie" hides the offer for two weeks; installing hides it for good.
  const KEY = 'install-dismissed'
  const SNOOZE_MS = 14 * 24 * 3600_000

  const phone = matchMedia('(pointer: coarse)').matches
  // iPadOS reports itself as a Mac.
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1)

  function dismissedRecently() {
    try {
      return Date.now() - Number(localStorage.getItem(KEY) ?? 0) < SNOOZE_MS
    } catch {
      return false
    }
  }

  let closed = $state(standalone || !phone || dismissedRecently())
  // Safari can't be asked to install: it gets the steps instead of a button.
  // It waits until the cookie banner is answered: both sit at the bottom of the screen.
  const mode = $derived(closed || (ANALYTICS && !consent.choice) ? null : ios ? 'ios' : deferred ? 'prompt' : null)
  let shown = false
  $effect(() => {
    if (mode && !shown) {
      shown = true
      track('install_prompt_shown', { mode })
    }
  })

  function dismiss(choice: string) {
    track('install_prompt_answered', { choice })
    closed = true
    try {
      localStorage.setItem(KEY, String(Date.now()))
    } catch {
      // Private mode: it shows again next time.
    }
  }

  async function install() {
    const e = deferred
    if (!e) return
    deferred = null // the event prompts only once
    await e.prompt()
    const { outcome } = await e.userChoice
    if (outcome === 'dismissed') dismiss('dismissed')
    else {
      track('install_prompt_answered', { choice: 'accepted' })
      closed = true
    }
  }

  onMount(() => {
    // Chromium only, whichever way the app was installed (this card or the browser menu). Safari
    // has no such event: there, pageviews with display_mode "standalone" show the installs in use.
    const done = () => {
      track('pwa_installed')
      closed = true
      deferred = null
    }
    addEventListener('appinstalled', done)
    return () => removeEventListener('appinstalled', done)
  })
</script>

{#if mode}
  <div class="install" role="dialog" aria-labelledby="install-title" aria-describedby="install-text">
    <div class="head">
      <img src="/apple-touch-icon.png" alt="" width="48" height="48" />
      <div>
        <h2 id="install-title">{t('Pridajte si MHD naživo na plochu', 'Add MHD naživo to your home screen')}</h2>
        <p id="install-text">{t('Mapa sa otvorí jedným ťuknutím, na celú obrazovku ako aplikácia.', 'The map opens with one tap, full screen like an app.')}</p>
      </div>
      <button class="x" onclick={() => dismiss('closed')} aria-label={t('Zavrieť', 'Close')}>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
          ><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" /></svg
        >
      </button>
    </div>
    {#if mode === 'ios'}
      <ol>
        <li>
          {t('Ťuknite na', 'Tap')} <b>{t('Zdieľať', 'Share')}</b>
          <svg class="share" viewBox="0 0 24 24" aria-hidden="true"
            ><path d="M12 15V3M8 7l4-4 4 4M7 10H5v11h14V10h-2" /></svg
          >
          <span class="muted">{t('(v Safari aj cez ⋯)', '(in Safari also under ⋯)')}</span>
        </li>
        <li>{t('Vyberte', 'Choose')} <b>{t('Pridať na plochu', 'Add to Home Screen')}</b></li>
      </ol>
      <div class="actions">
        <button class="primary" onclick={() => dismiss('ios_understood')}>{t('Rozumiem', 'Got it')}</button>
      </div>
    {:else}
      <div class="actions">
        <button class="secondary" onclick={() => dismiss('not_now')}>{t('Teraz nie', 'Not now')}</button>
        <button class="primary" onclick={install}>{t('Pridať na plochu', 'Add to home screen')}</button>
      </div>
    {/if}
  </div>
{/if}

<style>
  .install {
    position: absolute;
    z-index: 8;
    left: 10px;
    right: 10px;
    bottom: calc(10px + env(safe-area-inset-bottom));
    margin: 0 auto;
    max-width: 420px;
    background: var(--surface);
    border-radius: 18px;
    box-shadow: var(--shadow);
    padding: 16px;
    animation: rise 0.25s ease-out;
  }
  @keyframes rise {
    from {
      transform: translateY(16px);
      opacity: 0;
    }
  }
  .head {
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }
  img {
    flex: none;
    border-radius: 12px;
  }
  h2 {
    margin: 2px 0 2px;
    font-size: 1.02rem;
    line-height: 1.25;
  }
  p {
    margin: 0;
    color: var(--muted);
    font-size: 0.9rem;
  }
  .x {
    flex: none;
    width: 32px;
    height: 32px;
    margin: -6px -6px 0 auto;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: var(--muted);
  }
  ol {
    margin: 14px 0 0;
    padding: 12px 14px 12px 32px;
    background: var(--chip);
    border-radius: 12px;
    font-size: 0.92rem;
  }
  li + li {
    margin-top: 6px;
  }
  .share {
    width: 18px;
    height: 18px;
    vertical-align: -3px;
    fill: none;
    stroke: var(--accent);
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .actions {
    display: flex;
    gap: 8px;
    margin-top: 6px;
  }
  .actions button {
    flex: 1;
  }
</style>
