<script lang="ts">
  import { TYPE_LABELS } from '../lib/format'
  import { endLabel, favoriteView, HERE, profile, routeEnds, type Favorite } from '../lib/profile.svelte'
  import { app, navigate } from '../lib/state.svelte'
  import FavButton from './FavButton.svelte'
  import LineBadge from './LineBadge.svelte'
  import Panel from './Panel.svelte'

  const of = (kind: Favorite['kind']) => profile.favorites.filter((f) => f.kind === kind)
  const stations = $derived(of('station'))
  const lines = $derived(of('line').toSorted((a, b) => a.ref.localeCompare(b.ref, 'sk', { numeric: true })))
  const routes = $derived(of('route'))

  /** "Hlavná stanica – Dúbravka": the line's distinct headsigns. */
  function lineText(line: string): string {
    const info = app.lines[line]
    if (!info) return ''
    const heads = [...new Set(Object.values(info.directions).map((d) => d.headsign))]
    return heads.slice(0, 2).join(' – ') || TYPE_LABELS[info.type]
  }

  let busy = $state<string | null>(null)
  async function open(f: Favorite) {
    if (f.kind === 'route' && f.ref.split('>').includes(HERE)) busy = f.ref
    const view = await favoriteView(f)
    busy = null
    navigate(view)
  }
  const routeLabel = (f: Favorite) => `${endLabel(f, 'from')} → ${endLabel(f, 'to')}`
</script>

<Panel tall label="Obľúbené">
  {#snippet header()}
    <svg class="head-icon" viewBox="0 0 24 24" aria-hidden="true"
      ><path d="M12 3.5l2.6 5.3 5.9.9-4.25 4.1 1 5.8L12 16.9l-5.25 2.7 1-5.8L3.5 9.7l5.9-.9z" /></svg
    >
    <strong>Obľúbené</strong>
  {/snippet}

  {#if !profile.loaded}
    <div class="skeleton" aria-busy="true"><div></div><div></div></div>
  {:else if !profile.user && profile.failed}
    <p class="note error">Obľúbené sa teraz nedajú načítať. Skontrolujte pripojenie; skúsime to znova, keď sa vrátite do aplikácie.</p>
  {:else if !profile.user}
    <p class="note">
      Prihláste sa a pripnite si zastávky, linky a trasy, ktoré používate najčastejšie. Uvidíte ich tu na každom zariadení,
      kde sa prihlásite, a nainštalovaná aplikácia sa otvorí rovno na nich.
    </p>
    <button class="primary" onclick={() => navigate({ kind: 'account' })}>Prihlásiť sa alebo vytvoriť účet</button>
  {:else}
    {#if !profile.favorites.length}
      <p class="note">
        Zatiaľ nemáte nič pripnuté. Ťuknite na hviezdičku pri zastávke, linke alebo nájdenej trase a pridá sa sem.
      </p>
    {/if}

    {#if stations.length}
      <h3 class="section">Zastávky</h3>
      <ul class="favs">
        {#each stations as f (f.ref)}
          {@const st = app.stations[f.ref]}
          <li>
            <button class="row" onclick={() => open(f)}>
              <span class="pin" aria-hidden="true"></span>
              <span class="main">
                <span class="name">{st?.name ?? f.ref}</span>
                {#if st}
                  <span class="badges">
                    {#each st.lines.slice(0, 8) as l (l)}<LineBadge line={l} size="sm" />{/each}
                    {#if st.lines.length > 8}<span class="muted small">+{st.lines.length - 8}</span>{/if}
                  </span>
                {:else if Object.keys(app.stations).length}
                  <span class="muted small">Zastávka už nie je v cestovnom poriadku</span>
                {/if}
              </span>
            </button>
            <FavButton kind="station" ref={f.ref} label={st?.name ?? f.ref} />
          </li>
        {/each}
      </ul>
    {/if}

    {#if lines.length}
      <h3 class="section">Linky</h3>
      <ul class="favs">
        {#each lines as f (f.ref)}
          <li>
            <button class="row" onclick={() => open(f)}>
              <LineBadge line={f.ref} />
              <span class="main"><span class="name">{lineText(f.ref) || `Linka ${f.ref}`}</span></span>
            </button>
            <FavButton kind="line" ref={f.ref} label="linka {f.ref}" />
          </li>
        {/each}
      </ul>
    {/if}

    {#if routes.length}
      <h3 class="section">Trasy</h3>
      <ul class="favs">
        {#each routes as f (f.ref)}
          <li>
            <button class="row" onclick={() => open(f)} aria-busy={busy === f.ref}>
              <svg class="route-icon" viewBox="0 0 24 24" aria-hidden="true"
                ><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="6" r="2.5" /><path
                  d="M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5"
                /></svg
              >
              <span class="main">
                <span class="name">{endLabel(f, 'from')} <span aria-hidden="true">→</span><span class="sr">do</span> {endLabel(f, 'to')}</span>
                {#if busy === f.ref}<span class="muted small">Zisťujem vašu polohu…</span>{/if}
              </span>
            </button>
            <FavButton kind="route" ref={f.ref} names={f.names} label={routeLabel(f)} />
          </li>
        {/each}
      </ul>
    {/if}

    <p class="who muted small">
      Prihlásený ako {profile.user.email} ·
      <button class="link" onclick={() => navigate({ kind: 'account' })}>Účet</button>
    </p>
  {/if}
</Panel>

<style>
  .head-icon {
    width: 22px;
    height: 22px;
    fill: #e6a700;
    stroke: #e6a700;
    stroke-width: 1.8;
    stroke-linejoin: round;
  }
  .favs {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .favs li {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .row {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 12px;
    text-align: left;
    padding: 8px 8px 8px 6px;
    margin-left: -6px;
    border-radius: 10px;
    min-height: 52px;
  }
  .row:hover {
    background: var(--hover);
  }
  .main {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  .name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .badges {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
    align-items: center;
  }
  .pin {
    flex: none;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: #fff;
    border: 2.5px solid var(--text);
    box-shadow: inset 0 0 0 3px #fff, inset 0 0 0 8px var(--text);
  }
  .route-icon {
    flex: none;
    width: 24px;
    height: 24px;
    fill: none;
    stroke: var(--text);
    stroke-width: 2;
    stroke-linecap: round;
  }
  .who {
    margin: 20px 0 0;
  }
  .link {
    color: var(--accent);
    font-weight: 600;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  .skeleton div {
    height: 48px;
    border-radius: 10px;
    background: var(--chip);
    margin-top: 8px;
  }
</style>
