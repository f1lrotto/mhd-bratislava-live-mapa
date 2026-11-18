<script lang="ts">
  import { BAND_COLORS, bandLabels, NO_DATA_COLOR, STALE_COLOR, typePlural } from '../lib/format'
  import { passes } from '../lib/filter'
  import { t } from '../lib/i18n'
  import { shapeSvg } from '../lib/markers'
  import { app, filtersActive, navigate, NO_FILTERS, regionalDown, setFilters } from '../lib/state.svelte'
  import type { VehicleType } from '../lib/types'
  import LineGrid from './LineGrid.svelte'
  import Panel from './Panel.svelte'

  const TYPES: VehicleType[] = ['tram', 'trolleybus', 'bus']
  const f = $derived(app.filters)
  const total = $derived((app.live?.vehicles ?? []).length)
  const shown = $derived((app.live?.vehicles ?? []).filter((v) => passes(v, f)).length)

  function toggleType(t: VehicleType) {
    // No type filter means all are on; tapping one turns it off.
    const on = f.types.length ? f.types : TYPES
    const next = on.includes(t) ? on.filter((x) => x !== t) : [...on, t]
    setFilters({ types: next.length === TYPES.length ? [] : next })
  }
  function toggleLine(l: string) {
    setFilters({ lines: f.lines.includes(l) ? f.lines.filter((x) => x !== l) : [...f.lines, l] })
  }
  const legend = $derived([...BAND_COLORS, NO_DATA_COLOR].map((c, i) => ({ c, label: bandLabels()[i] })))
</script>

<Panel tall label={t('Filtre', 'Filters')}>
  {#snippet header()}
    <strong>{t('Filtre a legenda', 'Filters and legend')}</strong>
  {/snippet}

  <h3 class="section">{t('Druh', 'Type')}</h3>
  <div class="toggles">
    {#each TYPES as ty (ty)}
      <button class="toggle" aria-pressed={!f.types.length || f.types.includes(ty)} onclick={() => toggleType(ty)}>
        {@html shapeSvg(ty, '#5b6470', 16)}
        {typePlural(ty)}
      </button>
    {/each}
    <button class="toggle" aria-pressed={f.regional} onclick={() => setFilters({ regional: !f.regional })}>
      {@html shapeSvg('regional', '#5b6470', 16)}
      {t('Regionálne autobusy', 'Regional buses')}
    </button>
  </div>
  {#if f.regional && regionalDown()}
    <p class="count empty">{t('Polohy regionálnych autobusov (IDS BK) sa teraz nedajú načítať.', "Regional bus (IDS BK) positions can't be loaded right now.")}</p>
  {/if}
  <label class="switch">
    <input type="checkbox" checked={f.late} onchange={(e) => setFilters({ late: e.currentTarget.checked })} />
    {t('Len meškajúce 5+ min', 'Only 5+ min late')}
  </label>
  <label class="switch">
    <input type="checkbox" checked={!f.parked} onchange={(e) => setFilters({ parked: !e.currentTarget.checked })} />
    {t('Skryť odstavené vozidlá', 'Hide parked vehicles')}
  </label>

  <p class="count" class:empty={!shown && total}>
    {#if total && !shown}{t('Filtrom nezodpovedá žiadne vozidlo.', 'No vehicle matches the filters.')}{:else}{t(`Zobrazených ${shown} z ${total} vozidiel.`, `Showing ${shown} of ${total} vehicles.`)}{/if}
  </p>

  {#if filtersActive()}
    <button class="secondary" onclick={() => setFilters(NO_FILTERS)}>{t('Zrušiť filtre', 'Clear filters')}</button>
  {/if}

  <h3 class="section">{t('Legenda', 'Legend')}</h3>
  <ul class="legend">
    {#each legend as l (l.label)}
      <li><span class="sw" style:background={l.c}></span>{l.label}</li>
    {/each}
    <li><span class="sw" style:background={STALE_COLOR}></span>{t('stojí 10+ min', 'standing 10+ min')}</li>
  </ul>
  <ul class="legend">
    {#each TYPES as ty (ty)}
      <li>{@html shapeSvg(ty, '#5b6470', 16)} {typePlural(ty).toLowerCase()}</li>
    {/each}
    <li>{@html shapeSvg('regional', '#5b6470', 16)} {t('regionálne autobusy IDS BK', 'IDS BK regional buses')}</li>
  </ul>
  <p class="muted small">{t('Šípka pri značke ukazuje smer jazdy.', 'The arrow by a marker shows the direction of travel.')}</p>

  <h3 class="section">{t('Linky', 'Lines')} {f.lines.length ? `(${f.lines.length})` : ''}</h3>
  <LineGrid selected={f.lines} onpick={toggleLine} />

  <button class="secondary" onclick={() => navigate({ kind: 'privacy' })}>{t('Ochrana súkromia a cookies', 'Privacy and cookies')}</button>
</Panel>

<style>
  .toggles {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 40px;
    padding: 0 12px;
    border-radius: 999px;
    background: var(--chip);
    border: 2px solid transparent;
    font-weight: 600;
    font-size: 0.9rem;
  }
  .toggle[aria-pressed='true'] {
    background: #fff;
    border-color: var(--text);
  }
  .count {
    margin: 8px 0 0;
    font-size: 0.9rem;
    color: var(--muted);
  }
  .count.empty {
    color: var(--bad-text);
    font-weight: 600;
  }
  .switch {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 44px;
    margin-top: 6px;
    font-weight: 600;
  }
  .switch input {
    width: 20px;
    height: 20px;
    accent-color: var(--text);
  }
  .legend {
    list-style: none;
    padding: 0;
    margin: 0 0 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px 14px;
    font-size: 0.85rem;
  }
  .legend li {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .sw {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 1.5px solid #fff;
    box-shadow: 0 0 0 1px #d4d8dd;
  }
</style>
