<script lang="ts">
  import { compareLines, isNight } from '../lib/format'
  import { count, t } from '../lib/i18n'
  import { app } from '../lib/state.svelte'
  import LineBadge from './LineBadge.svelte'

  let {
    onpick,
    selected = null,
    query = '',
  }: { onpick: (line: string) => void; selected?: string[] | null; query?: string } = $props()

  const counts = $derived.by(() => {
    const c: Record<string, number> = {}
    for (const v of app.live?.vehicles ?? []) if (v.line) c[v.line] = (c[v.line] ?? 0) + 1
    return c
  })

  const groups = $derived.by(() => {
    const q = query.trim().toLowerCase()
    const lines = Object.values(app.lines)
      .filter((l) => !q || l.line.toLowerCase().startsWith(q) || Object.values(l.directions).some((d) => d.headsign.toLowerCase().includes(q)))
      .sort((a, b) => compareLines(a.line, b.line))
    const dpb = lines.filter((l) => !l.regional)
    return [
      { title: t('Električky', 'Trams'), items: dpb.filter((l) => l.type === 'tram') },
      { title: t('Trolejbusy', 'Trolleybuses'), items: dpb.filter((l) => l.type === 'trolleybus' && !isNight(l.line)) },
      { title: t('Autobusy', 'Buses'), items: dpb.filter((l) => l.type === 'bus' && !isNight(l.line)) },
      { title: t('Nočné', 'Night'), items: dpb.filter((l) => isNight(l.line)) },
      { title: t('Regionálne autobusy IDS BK', 'IDS BK regional buses'), items: lines.filter((l) => l.regional) },
    ].filter((g) => g.items.length)
  })
</script>

{#each groups as g (g.title)}
  <h3 class="section">{g.title}</h3>
  <div class="grid">
    {#each g.items as l (l.line)}
      {@const n = counts[l.line] ?? 0}
      <button
        class="cell"
        class:on={selected?.includes(l.line)}
        class:idle={!n}
        aria-pressed={selected ? selected.includes(l.line) : undefined}
        aria-label={t(`Linka ${l.line}`, `Line ${l.line}`) + ', ' + count(n, ['vozidlo', 'vozidlá', 'vozidiel'], ['vehicle', 'vehicles'])}
        onclick={() => onpick(l.line)}
      >
        <LineBadge line={l.line} />
        <span class="n">{n || ''}</span>
      </button>
    {/each}
  </div>
{:else}
  <p class="note">{Object.keys(app.lines).length ? t('Žiadna linka nezodpovedá hľadaniu.', 'No line matches the search.') : t('Načítavam linky…', 'Loading lines…')}</p>
{/each}

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(62px, 1fr));
    gap: 6px;
  }
  .cell {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    height: 44px;
    border-radius: 10px;
    background: var(--chip);
    border: 2px solid transparent;
  }
  .cell:hover {
    background: var(--hover);
  }
  .cell.on {
    border-color: var(--text);
    background: var(--surface);
  }
  .cell.idle :global(.badge) {
    opacity: 0.45;
  }
  .n {
    font-size: 0.8rem;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    min-width: 1ch;
  }
</style>
