<script lang="ts">
  import { compareLines, isNight, plural } from '../lib/format'
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
      { title: 'Električky', items: dpb.filter((l) => l.type === 'tram') },
      { title: 'Trolejbusy', items: dpb.filter((l) => l.type === 'trolleybus' && !isNight(l.line)) },
      { title: 'Autobusy', items: dpb.filter((l) => l.type === 'bus' && !isNight(l.line)) },
      { title: 'Nočné', items: dpb.filter((l) => isNight(l.line)) },
      { title: 'Regionálne autobusy IDS BK', items: lines.filter((l) => l.regional) },
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
        aria-label="Linka {l.line}, {plural(n, 'vozidlo', 'vozidlá', 'vozidiel')}"
        onclick={() => onpick(l.line)}
      >
        <LineBadge line={l.line} />
        <span class="n">{n || ''}</span>
      </button>
    {/each}
  </div>
{:else}
  <p class="note">{Object.keys(app.lines).length ? 'Žiadna linka nezodpovedá hľadaniu.' : 'Načítavam linky…'}</p>
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
    background: #fff;
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
