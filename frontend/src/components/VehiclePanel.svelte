<script lang="ts">
  import { agoText, bandColor, delayText, TYPE_LABELS } from '../lib/format'
  import { app, feedDown, navigate } from '../lib/state.svelte'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'

  let { key }: { key: string } = $props()

  const v = $derived(app.live?.vehicles.find((x) => x.key === key) ?? null)
  const lv = $derived(v?.line && app.lineView?.line === v.line ? app.lineView : null)
  const dir = $derived(lv?.directions.find((d) => d.id === v?.dir) ?? null)
  const rv = $derived(dir?.vehicles.find((x) => x.key === key) ?? null)
  const unmatched = $derived(lv?.unmatched.find((u) => u.key === key) ?? null)
  // movedAgo is relative to the server's `now`; keep counting between polls.
  const movedAgo = $derived(
    v?.movedAgo != null && app.live ? v.movedAgo + (app.tick + app.skewMs - Date.parse(app.live.feed.now)) / 1000 : null,
  )

  const REASONS: Record<string, string> = {
    to_depot: 'Ide do depa, preto nie je v poradí linky.',
    no_destination: 'Vozidlo nehlási cieľ, smer nevieme určiť.',
    unknown_direction: 'Cieľ nepatrí žiadnemu smeru linky v cestovnom poriadku.',
    unknown_line: 'Linka nie je v cestovnom poriadku DPB.',
  }
</script>

<Panel label="Vozidlo {key}">
  {#snippet header()}
    {#if v?.line}<LineBadge line={v.line} size="lg" />{/if}
    <div class="head-text">
      <strong class="dest">{v ? (v.dest ? `→ ${v.dest}` : 'Bez cieľa') : `Vozidlo ${key}`}</strong>
      <span class="muted">{v ? TYPE_LABELS[v.type] : ''} č. {key}</span>
    </div>
  {/snippet}

  {#if !app.live}
    <p class="note">Načítavam polohy…</p>
  {:else if !v}
    <p class="note">Vozidlo č. {key} teraz nie je v prevádzke alebo nehlási polohu.</p>
  {:else}
    <div class="facts">
      <div class="fact">
        <span class="label">Meškanie</span>
        <span class="value" style:color={bandColor(v.band)}>{delayText(v.delay, v.delayCapped)}</span>
      </div>
      <div class="fact">
        <span class="label">Poloha zmenená</span>
        <span class="value small-value">{agoText(movedAgo)}</span>
      </div>
    </div>

    {#if v.delayCapped}
      <p class="note">Systém DPB nehlási viac ako 15 minút, skutočné meškanie môže byť vyššie.</p>
    {/if}
    {#if feedDown()}
      <p class="note warn">Dáta o polohe sú staré, vozidlo už môže byť inde.</p>
    {:else if v.stale}
      <p class="note warn">Poloha sa viac ako 10 minút nezmenila. Vozidlo môže stáť alebo nehlásiť polohu.</p>
    {/if}

    {#if dir && rv}
      <p class="where">
        {#if rv.offRoute}
          Mimo trasy smeru {dir.headsign}.
        {:else}
          Za zastávkou <strong>{dir.stops[rv.lastStop]?.name}</strong>, {Math.round((rv.along / dir.length) * 100)} % trasy.
        {/if}
      </p>
    {:else if unmatched}
      <p class="note">{REASONS[unmatched.reason] ?? ''}</p>
    {/if}

    {#if v.line && app.lines[v.line]}
      <button class="primary" onclick={() => navigate({ kind: 'line', line: v.line!, dir: v.dir })}>
        Celá linka {v.line}: poradie a medzery
      </button>
    {/if}
  {/if}
</Panel>

<style>
  .head-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
    line-height: 1.25;
  }
  .dest {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .facts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin: 4px 0 10px;
  }
  .fact {
    background: var(--chip);
    border-radius: 12px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .label {
    font-size: 0.8rem;
    color: var(--muted);
  }
  .value {
    font-size: 1.35rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .small-value {
    font-size: 1.05rem;
    padding-top: 4px;
  }
  .where {
    margin: 4px 0 14px;
    line-height: 1.4;
  }
</style>
