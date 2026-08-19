<script>
    let { logs = [] } = $props();
</script>

<div class="bg-black text-green-400 font-mono p-4 rounded-lg h-[200px] overflow-y-auto text-lg leading-relaxed border border-gray-800">
    {#each logs as log}
        <div>&gt; {log}</div>
    {:else}
        <div class="text-gray-600 italic">Esperando conexión...</div>
    {/each}
</div>
