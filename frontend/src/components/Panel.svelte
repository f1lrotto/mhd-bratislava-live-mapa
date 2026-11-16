<script lang="ts">
  import type { Snippet } from 'svelte'
  import { closePanel } from '../lib/state.svelte'

  let { label, header, children }: { label: string; header: Snippet; children: Snippet } = $props()

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
    else if (dy > 30) {
      if (expanded) expanded = false
      else closePanel()
    }
  }
</script>

<section class="panel" class:expanded aria-label={label}>
  <!-- The handle button is the accessible control; the swipe area is a touch shortcut for it. -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="sheet-top" onpointerdown={down} onpointerup={up} onpointercancel={() => (startY = null)}>
    <button
      class="grab"
      onclick={() => (expanded = !expanded)}
      aria-label={expanded ? 'Zmenšiť panel' : 'Zväčšiť panel'}
      aria-expanded={expanded}
    ></button>
    <header>
      <div class="title">{@render header()}</div>
      <button class="close" onclick={closePanel} aria-label="Zavrieť">
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"
          ><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" /></svg
        >
      </button>
    </header>
  </div>
  <div class="body">{@render children()}</div>
</section>

<style>
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
      height: min(50dvh, 460px);
      border-radius: 18px 18px 0 0;
      transition: height 0.22s ease;
      padding-bottom: env(safe-area-inset-bottom);
    }
    .panel.expanded {
      height: calc(100dvh - 64px);
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
