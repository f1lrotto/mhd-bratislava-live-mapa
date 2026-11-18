<script lang="ts">
  import { onMount, type Snippet } from 'svelte'
  import { t } from '../lib/i18n'
  import { app, closePanel } from '../lib/state.svelte'

  let {
    label,
    header,
    children,
    tall = false,
    expand = false,
    onback,
  }: {
    label: string
    header: Snippet
    children: Snippet
    tall?: boolean
    /** Keep the phone sheet at full height (e.g. while a text field has focus). */
    expand?: boolean
    /** Replaces the history back of the back button (and shows it) when set. */
    onback?: { label: string; go: () => void }
  } = $props()

  let section: HTMLElement
  // Keyboard focus moves into every panel that opens; closePanel() returns it to the opener.
  onMount(() => section.focus({ preventScroll: true }))

  // On phones the panel is a bottom sheet: half height, or nearly full when expanded.
  let expanded = $state(false)
  let startY: number | null = null

  function down(e: PointerEvent) {
    startY = e.clientY
  }
  function up(e: PointerEvent) {
    if (startY == null) return
    const dy = e.clientY - startY
    startY = null
    if (dy < -30) expanded = true
    // Swiping down only shrinks the sheet; closing is the ✕ button, so a line isn't lost by accident.
    else if (dy > 30) expanded = false
  }
</script>

<section class="panel" class:expanded={expanded || expand} class:tall aria-label={label} tabindex="-1" bind:this={section}>
  <!-- The handle button is the accessible control; the swipe area is a touch shortcut for it. -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="sheet-top" onpointerdown={down} onpointerup={up} onpointercancel={() => (startY = null)}>
    <button
      class="grab"
      onclick={() => (expanded = !expanded)}
      aria-label={expanded ? t('Zmenšiť panel', 'Shrink panel') : t('Zväčšiť panel', 'Expand panel')}
      aria-expanded={expanded}
    ></button>
    <header>
      {#if onback || app.canBack}
        <!-- Returns to the panel this one was opened from (e.g. the plan behind a vehicle). -->
        <button
          class="close back"
          onclick={() => (onback ? onback.go() : history.back())}
          aria-label={onback?.label ?? t('Späť', 'Back')}
          title={onback?.label ?? t('Späť', 'Back')}
        >
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"
            ><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" /></svg
          >
        </button>
      {/if}
      <div class="title">{@render header()}</div>
      <button class="close" onclick={closePanel} aria-label={t('Zavrieť', 'Close')}>
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"
          ><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" /></svg
        >
      </button>
    </header>
  </div>
  <div class="body">{@render children()}</div>
</section>

<style>
  .panel:focus {
    outline: none;
  }
  .panel {
    position: absolute;
    z-index: 5;
    background: var(--surface);
    box-shadow: var(--shadow);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 8px 8px 16px;
  }
  .title {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .close {
    flex: none;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: var(--muted);
  }
  .back {
    margin-left: -10px;
  }
  .close:hover {
    background: var(--hover);
    color: var(--text);
  }
  .body {
    flex: 1;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 0 16px 16px;
  }
  .grab {
    display: none;
  }

  @media (min-width: 768px) {
    .panel {
      left: 12px;
      top: 68px;
      bottom: 12px;
      width: 384px;
      border-radius: 16px;
      max-height: calc(100% - 80px);
    }
    header {
      padding-top: 12px;
    }
  }

  @media (max-width: 767.98px) {
    .panel {
      left: 0;
      right: 0;
      bottom: 0;
      max-height: min(50dvh, 460px);
      border-radius: 18px 18px 0 0;
      transition: height 0.22s ease, max-height 0.22s ease;
      padding-bottom: env(safe-area-inset-bottom);
    }
    .panel.tall {
      height: min(50dvh, 460px);
    }
    .panel.expanded {
      height: calc(100dvh - 64px);
      max-height: calc(100dvh - 64px);
    }
    .sheet-top {
      touch-action: none;
    }
    .grab {
      display: block;
      width: 100%;
      height: 22px;
      position: relative;
    }
    .grab::after {
      content: '';
      position: absolute;
      left: 50%;
      top: 9px;
      width: 40px;
      height: 5px;
      margin-left: -20px;
      border-radius: 3px;
      background: #c9ced5;
    }
  }
</style>
