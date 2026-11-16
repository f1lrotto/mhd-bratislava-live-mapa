<script lang="ts">
  import { navigate } from '../lib/state.svelte'
  import LineGrid from './LineGrid.svelte'
  import Panel from './Panel.svelte'

  let query = $state('')
</script>

<Panel label="Linky">
  {#snippet header()}
    <strong>Vyberte linku</strong>
  {/snippet}
  <input
    class="search"
    type="search"
    placeholder="Číslo linky alebo cieľ"
    aria-label="Hľadať linku"
    bind:value={query}
    inputmode="search"
    autocomplete="off"
  />
  <p class="hint muted small">Číslo pri linke je počet jej vozidiel na mape.</p>
  <LineGrid {query} onpick={(line) => navigate({ kind: 'line', line, dir: null })} />
</Panel>

<style>
  .search {
    width: 100%;
    height: 44px;
    border-radius: 10px;
    border: 1.5px solid #d4d8dd;
    padding: 0 12px;
    font: inherit;
    font-size: 16px;
  }
  .search:focus {
    outline: none;
    border-color: var(--accent);
  }
  .hint {
    margin: 6px 0 0;
  }
</style>
