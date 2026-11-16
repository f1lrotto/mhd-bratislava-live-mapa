<script lang="ts">
  import { app, navigate } from '../lib/state.svelte'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'

  let { id }: { id: string } = $props()
  const stop = $derived(app.stops[id])
</script>

<Panel label="Zastávka">
  {#snippet header()}
    <div class="head-text">
      <strong>{stop?.name ?? 'Zastávka'}</strong>
      {#if stop?.platform}<span class="muted">nástupište {stop.platform}</span>{/if}
    </div>
  {/snippet}

  {#if !stop}
    <p class="note">Zastávku sme nenašli.</p>
  {:else}
    <h3 class="section">Linky</h3>
    <div class="chips">
      {#each stop.lines as line (line)}
        <button class="chip-btn" onclick={() => navigate({ kind: 'line', line, dir: null })} aria-label="Linka {line}">
          <LineBadge {line} />
        </button>
      {/each}
    </div>
    <p class="note">Predpokladané príchody zatiaľ neukazujeme. Odchody z tejto zastávky nájdete v Ubiane.</p>
    <a class="secondary" href="https://www.ubian.sk/odchody" target="_blank" rel="noopener">Odchody v Ubiane ↗</a>
  {/if}
</Panel>

<style>
  .head-text {
    display: flex;
    flex-direction: column;
    line-height: 1.25;
  }
</style>
