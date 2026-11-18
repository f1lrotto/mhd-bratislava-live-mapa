<script lang="ts">
  import { t } from '../lib/i18n'
  import { app, navigate } from '../lib/state.svelte'
  import LineGrid from './LineGrid.svelte'
  import Panel from './Panel.svelte'

  let query = $state('')
</script>

<Panel tall label={t('Linky', 'Lines')}>
  {#snippet header()}
    <strong>{t('Vyberte linku', 'Pick a line')}</strong>
  {/snippet}
  <input
    class="search"
    type="search"
    placeholder={t('Číslo linky alebo cieľ', 'Line number or destination')}
    aria-label={t('Hľadať linku', 'Search lines')}
    bind:value={query}
    inputmode="search"
    autocomplete="off"
    onkeydown={(e) => {
      const q = query.trim().toUpperCase()
      if (e.key === 'Enter' && app.lines[q]) navigate({ kind: 'line', line: q, dir: null })
    }}
  />
  <p class="hint muted small">{t('Číslo pri linke je počet jej vozidiel na mape.', 'The number by a line is how many of its vehicles are on the map.')}</p>
  <LineGrid {query} onpick={(line) => navigate({ kind: 'line', line, dir: null })} />
</Panel>

<style>
  .search {
    width: 100%;
    height: 44px;
    border-radius: 10px;
    border: 1.5px solid var(--border);
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
