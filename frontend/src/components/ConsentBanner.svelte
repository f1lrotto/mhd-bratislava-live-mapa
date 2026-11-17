<script lang="ts">
  import { ANALYTICS, consent, setConsent } from '../lib/analytics.svelte'
  import { app, navigate } from '../lib/state.svelte'

  // Both answers look the same and are one tap away: refusing must be as easy as agreeing.
  // Hidden on the privacy page, which has the same two buttons.
</script>

{#if ANALYTICS && !consent.choice && app.view.kind !== 'privacy'}
  <div class="consent" role="dialog" aria-labelledby="consent-title" aria-describedby="consent-text">
    <h2 id="consent-title">Súkromie a cookies</h2>
    <p id="consent-text">
      Návštevnosť meriame anonymne a bez cookies. Ak súhlasíte, prehliadač si uloží náhodný identifikátor (PostHog, údaje v
      EÚ), aby sme spoznali opakované návštevy. Svoju voľbu môžete kedykoľvek zmeniť.
      <a
        href="/sukromie"
        onclick={(e) => {
          e.preventDefault()
          navigate({ kind: 'privacy' })
        }}>Ochrana súkromia</a
      >
    </p>
    <div class="actions">
      <button class="primary" onclick={() => setConsent('denied')}>Odmietnuť</button>
      <button class="primary" onclick={() => setConsent('granted')}>Súhlasím</button>
    </div>
  </div>
{/if}

<style>
  .consent {
    position: absolute;
    z-index: 9;
    left: 10px;
    right: 10px;
    bottom: calc(10px + env(safe-area-inset-bottom));
    margin: 0 auto;
    max-width: 460px;
    background: var(--surface);
    border-radius: 18px;
    box-shadow: var(--shadow);
    padding: 16px;
  }
  h2 {
    margin: 0 0 4px;
    font-size: 1.02rem;
  }
  p {
    margin: 0;
    color: var(--muted);
    font-size: 0.9rem;
    line-height: 1.4;
  }
  a {
    color: var(--accent);
  }
  .actions {
    display: flex;
    gap: 8px;
    margin-top: 12px;
  }
  .actions button {
    flex: 1;
  }
</style>
