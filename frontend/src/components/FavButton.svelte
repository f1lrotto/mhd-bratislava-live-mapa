<script lang="ts">
  import { isFavorite, setFavorite, type Favorite, type FavoriteKind } from '../lib/profile.svelte'

  let { kind, ref, names = null, label }: { kind: FavoriteKind; ref: string; names?: Favorite['names']; label: string } =
    $props()

  const on = $derived(isFavorite(kind, ref))
</script>

<button
  class="fav"
  class:on
  onclick={() => setFavorite(kind, ref, !on, names)}
  aria-pressed={on}
  aria-label="Obľúbené: {label}"
  title={on ? 'Odobrať z obľúbených' : 'Pridať do obľúbených'}
>
  <svg viewBox="0 0 24 24" aria-hidden="true"
    ><path d="M12 3.5l2.6 5.3 5.9.9-4.25 4.1 1 5.8L12 16.9l-5.25 2.7 1-5.8L3.5 9.7l5.9-.9z" /></svg
  >
</button>

<style>
  .fav {
    flex: none;
    margin-left: auto;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: var(--muted);
  }
  .fav:hover {
    background: var(--hover);
    color: var(--text);
  }
  svg {
    width: 22px;
    height: 22px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linejoin: round;
  }
  .on {
    color: #e6a700;
  }
  .on:hover {
    color: #c98f00;
  }
  .on svg {
    fill: currentColor;
  }
</style>
