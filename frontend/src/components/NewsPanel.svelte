<script lang="ts">
  import { onMount } from 'svelte'
  import { isNew, markSeen, news, NEWS, openItem, type NewsItem } from '../lib/news.svelte'
  import { locale, t } from '../lib/i18n'
  import Panel from './Panel.svelte'

  // Entries new on opening keep their badge while the panel is open; the top bar's dot goes.
  const seenBefore = news.seen
  onMount(markSeen)

  const fmt = $derived(new Intl.DateTimeFormat(locale(), { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }))
  // Entries of one day under one date heading.
  const days = new Map<string, { item: NewsItem; i: number }[]>()
  NEWS.forEach((item, i) => days.set(item.date, [...(days.get(item.date) ?? []), { item, i }]))
</script>

<Panel tall label={t('Čo je nové', "What's new")}>
  {#snippet header()}
    <svg class="head-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" /></svg>
    <strong>{t('Čo je nové', "What's new")}</strong>
  {/snippet}

  {#each [...days] as [date, entries] (date)}
    <h3 class="section"><time datetime={date}>{fmt.format(new Date(date))}</time></h3>
    <ul class="news">
      {#each entries as { item, i } (item.title)}
        <li>
          <h4>
            {item.title}
            {#if isNew(i, seenBefore)}<span class="badge">{t('Nové', 'New')}</span>{/if}
          </h4>
          {#each item.paragraphs as p, k (k)}<p>{p}</p>{/each}
          {#if item.open}
            <button class="open" onclick={() => openItem(item)}>{item.open.label} <span aria-hidden="true">›</span></button>
          {/if}
        </li>
      {/each}
    </ul>
  {/each}
</Panel>

<style>
  .head-icon {
    width: 20px;
    height: 20px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linejoin: round;
  }
  .news {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  h4 {
    margin: 0 0 2px;
    font-size: 0.98rem;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  p {
    margin: 0 0 6px;
    font-size: 0.92rem;
    line-height: 1.5;
  }
  .badge {
    background: var(--accent);
    color: #fff;
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-radius: 6px;
    padding: 1px 6px;
  }
  .open {
    margin-top: 4px;
    min-height: 36px;
    padding: 0 10px;
    margin-left: -10px;
    border-radius: 8px;
    color: var(--accent);
    font-weight: 600;
    font-size: 0.9rem;
  }
  .open:hover {
    background: var(--hover);
  }
</style>
