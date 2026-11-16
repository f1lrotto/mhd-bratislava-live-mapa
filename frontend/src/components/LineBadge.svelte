<script lang="ts">
  import { app } from '../lib/state.svelte'

  let { line, size = 'md' }: { line: string; size?: 'sm' | 'md' | 'lg' } = $props()
  const info = $derived(app.lines[line])
</script>

<span
  class="badge {size}"
  class:night={/^N\d/.test(line)}
  style:background={info?.color ?? '#5b6470'}
  style:color={info?.textColor ?? '#fff'}>{line}</span
>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 2.1em;
    padding: 0 0.4em;
    height: 1.7em;
    border-radius: 0.45em;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 1;
    flex: none;
  }
  .sm {
    font-size: 0.8rem;
  }
  .md {
    font-size: 0.95rem;
  }
  .lg {
    font-size: 1.25rem;
  }
  .night {
    box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.35);
  }
</style>
