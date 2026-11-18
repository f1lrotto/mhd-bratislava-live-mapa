<script lang="ts">
  import { onDestroy } from 'svelte'
  import { toLocalInput } from '../lib/format'

  /** A Bratislava time set with hour and minute arrows (held, they repeat) and quick shifts. A change
   * reaches `onchange` once stepping pauses, so a held arrow doesn't refetch on every step. */
  let {
    value,
    min = -Infinity,
    max = Infinity,
    onchange,
  }: {
    /** Epoch milliseconds. */
    value: number
    min?: number
    max?: number
    onchange: (ms: number) => void
  } = $props()

  const MINUTE = 60_000
  const QUICK: [number, string][] = [
    [-60, '−1 h'],
    [-15, '−15 min'],
    [15, '+15 min'],
    [60, '+1 h'],
  ]

  let draft = $state<number | null>(null)
  const shown = $derived(draft ?? value)
  const hm = $derived(toLocalInput(new Date(shown).toISOString()).slice(11, 16))
  const can = (d: number) => (d > 0 ? shown < max : shown > min)

  let commitTimer: ReturnType<typeof setTimeout> | undefined
  function commit() {
    clearTimeout(commitTimer)
    if (draft == null) return
    const v = draft
    draft = null
    if (v !== value) onchange(v)
  }
  // Commits wait until a held arrow is released and stepping has paused.
  function later() {
    clearTimeout(commitTimer)
    if (!holding) commitTimer = setTimeout(commit, 400)
  }
  function step(d: number) {
    draft = Math.min(max, Math.max(min, shown + d * MINUTE))
    later()
  }

  let holding = false
  let holdTimer: ReturnType<typeof setTimeout> | undefined
  let repeat: ReturnType<typeof setInterval> | undefined
  function press(e: PointerEvent, d: number) {
    if (e.button !== 0) return
    holding = true
    step(d)
    holdTimer = setTimeout(() => (repeat = setInterval(() => step(d), 70)), 400)
  }
  function release() {
    clearTimeout(holdTimer)
    clearInterval(repeat)
    if (!holding) return
    holding = false
    later()
  }
  onDestroy(() => {
    release()
    commit()
  })
</script>

<svelte:window onpointerup={release} onpointercancel={release} />

{#snippet arrow(d: number, label: string, path: string)}
  <!-- Pointer presses step (and repeat while held); keyboard clicks (detail 0) step once. -->
  <button
    class="arrow"
    aria-label={label}
    disabled={!can(d)}
    onpointerdown={(e) => press(e, d)}
    onpointerleave={release}
    onclick={(e) => e.detail === 0 && step(d)}
    oncontextmenu={(e) => e.preventDefault()}
  >
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d={path} /></svg>
  </button>
{/snippet}

<div class="stepper" role="group" aria-label="Čas {hm}">
  <div class="col">
    {@render arrow(60, 'O hodinu neskôr', 'M6 15l6-6 6 6')}
    <span class="big">{hm.slice(0, 2)}</span>
    {@render arrow(-60, 'O hodinu skôr', 'M6 9l6 6 6-6')}
  </div>
  <span class="big">:</span>
  <div class="col">
    {@render arrow(1, 'O minútu neskôr', 'M6 15l6-6 6 6')}
    <span class="big">{hm.slice(3, 5)}</span>
    {@render arrow(-1, 'O minútu skôr', 'M6 9l6 6 6-6')}
  </div>
</div>
<div class="quick">
  {#each QUICK as [d, label] (d)}
    <button disabled={!can(d)} onclick={() => step(d)}>{label}</button>
  {/each}
</div>
<p class="hint">Podržte šípku pre rýchly posun</p>

<style>
  .stepper {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
  }
  .col {
    display: grid;
    justify-items: center;
  }
  .big {
    font-size: 40px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    line-height: 1.1;
  }
  .arrow {
    width: 64px;
    height: 40px;
    border-radius: 10px;
    display: grid;
    place-items: center;
    color: var(--muted);
    touch-action: manipulation;
    user-select: none;
    -webkit-user-select: none;
    -webkit-touch-callout: none;
  }
  .arrow svg {
    width: 24px;
    height: 24px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2.2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .quick {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 4px;
    margin-top: 10px;
  }
  .quick button {
    height: 34px;
    padding: 0 10px;
    border-radius: 999px;
    background: var(--chip);
    font-weight: 600;
    font-size: 0.88rem;
  }
  @media (hover: hover) {
    .arrow:hover:not(:disabled),
    .quick button:hover:not(:disabled) {
      background: var(--hover);
      color: var(--text);
    }
  }
  button:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .hint {
    margin: 8px 0 0;
    font-size: 0.82rem;
    color: var(--muted);
    text-align: center;
  }
</style>
