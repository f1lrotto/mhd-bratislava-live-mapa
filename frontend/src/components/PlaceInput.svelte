<script lang="ts">
  import { t } from '../lib/i18n'
  import { placeLabel, searchStations } from '../lib/places'
  import { app } from '../lib/state.svelte'
  import LineBadge from './LineBadge.svelte'

  let {
    end,
    label,
    value,
    onpick,
    onlocate,
    onmap,
    input = $bindable(),
  }: {
    end: 'from' | 'to'
    label: string
    value: string | null
    onpick: (code: string) => void
    onlocate: () => void
    onmap: () => void
    input?: HTMLInputElement
  } = $props()

  let query = $state('')
  let editing = $state(false)
  let active = $state(0)
  const id = $props.id()

  const hits = $derived(editing ? searchStations(query) : [])
  const shown = $derived(editing ? query : placeLabel(value))
  const picking = $derived(app.pick === end)

  function choose(code: string) {
    editing = false
    query = ''
    onpick(code)
  }

  function key(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' && hits.length) {
      e.preventDefault()
      active = (active + 1) % hits.length
    } else if (e.key === 'ArrowUp' && hits.length) {
      e.preventDefault()
      active = (active - 1 + hits.length) % hits.length
    } else if (e.key === 'Enter' && hits[active]) {
      e.preventDefault()
      choose(hits[active].code)
    } else if (e.key === 'Escape' && editing) {
      // Close the list, not the panel.
      e.stopPropagation()
      editing = false
      query = ''
    }
  }
</script>

<div class="field">
  <span class="mark {end}" aria-hidden="true"></span>
  <input
    bind:this={input}
    type="text"
    placeholder={end === 'from' ? t('Odkiaľ', 'From') : t('Kam', 'To')}
    aria-label={label}
    role="combobox"
    aria-expanded={hits.length > 0}
    aria-controls="{id}-list"
    aria-autocomplete="list"
    aria-activedescendant={hits.length ? `${id}-${active}` : undefined}
    autocomplete="off"
    spellcheck="false"
    value={shown}
    oninput={(e) => {
      editing = true
      active = 0
      query = (e.currentTarget as HTMLInputElement).value
    }}
    onfocus={(e) => (e.currentTarget as HTMLInputElement).select()}
    onblur={() => setTimeout(() => ((editing = false), (query = '')), 150)}
    onkeydown={key}
  />
  <button class="icon" onclick={onlocate} aria-label="{label}: {t('moja poloha', 'my location')}" title={t('Moja poloha', 'My location')}>
    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.5" /><circle cx="12" cy="12" r="7.5" /><path d="M12 1.5v3M12 19.5v3M1.5 12h3M19.5 12h3" /></svg>
  </button>
  <button
    class="icon"
    class:on={picking}
    onclick={onmap}
    aria-label="{label}: {t('vybrať na mape', 'pick on the map')}"
    aria-pressed={picking}
    title={t('Vybrať na mape', 'Pick on the map')}
  >
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11z" /><circle cx="12" cy="10" r="2" /></svg>
  </button>
</div>
{#if editing && query.trim()}
  <ul class="list" id="{id}-list" role="listbox" aria-label={t('Zastávky', 'Stops')}>
    {#each hits as h, i (h.code)}
      <!-- Mouse down, not click, so the pick lands before the input's blur closes the list. -->
      <li
        id="{id}-{i}"
        role="option"
        aria-selected={i === active}
        class:active={i === active}
        onmousedown={(e) => {
          e.preventDefault()
          choose(h.code)
        }}
      >
        <span class="name">{h.name}</span>
        <span class="lines">
          {#each h.lines.slice(0, 3) as l (l)}<LineBadge line={l} size="sm" />{/each}
          {#if h.lines.length > 3}<span class="muted small">+{h.lines.length - 3}</span>{/if}
        </span>
      </li>
    {:else}
      <li class="none muted">{t('Žiadna zastávka s týmto názvom', 'No stop with this name')}</li>
    {/each}
  </ul>
{/if}

<style>
  .field {
    display: flex;
    align-items: center;
    gap: 2px;
    min-width: 0;
  }
  .mark {
    flex: none;
    width: 14px;
    height: 14px;
    margin-right: 8px;
    border-radius: 50%;
    border: 3.5px solid var(--text);
    background: #fff;
  }
  .mark.to {
    border-radius: 3px;
    background: var(--bad);
    border-color: var(--bad);
  }
  input {
    flex: 1;
    min-width: 0;
    height: 42px;
    border-radius: 10px;
    border: 1.5px solid #d4d8dd;
    padding: 0 10px;
    font: inherit;
    font-size: 16px;
    background: #fff;
  }
  input:focus {
    outline: none;
    border-color: var(--accent);
  }
  .icon {
    flex: none;
    width: 38px;
    height: 42px;
    border-radius: 10px;
    display: grid;
    place-items: center;
    color: var(--muted);
  }
  .icon:hover {
    background: var(--hover);
    color: var(--text);
  }
  .icon.on {
    background: var(--accent);
    color: #fff;
  }
  .icon svg {
    width: 20px;
    height: 20px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
  }
  .list {
    list-style: none;
    margin: 4px 0 6px 22px;
    padding: 4px;
    border-radius: 12px;
    background: #fff;
    box-shadow: var(--shadow-sm);
    border: 1px solid #e3e6ea;
  }
  .list li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    min-height: 42px;
    padding: 6px 10px;
    border-radius: 8px;
    cursor: pointer;
  }
  .list li.active,
  .list li:hover {
    background: var(--hover);
  }
  .list li.none {
    cursor: default;
  }
  .name {
    font-weight: 600;
    min-width: 0;
    line-height: 1.25;
  }
  .lines {
    display: flex;
    gap: 3px;
    align-items: center;
    flex: none;
  }
</style>
