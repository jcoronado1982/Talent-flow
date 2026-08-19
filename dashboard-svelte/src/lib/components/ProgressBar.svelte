<script>
    let { label, progress, text, color = 'var(--color-primary)' } = $props();
</script>

<div class="bg-card-bg p-5 rounded-xl mb-5">
    <div class="flex justify-between items-center mb-4">
        <span class="font-medium text-gray-200">{label}</span>
        <span class="text-sm font-mono">{text}</span>
    </div>
    <div class="bg-gray-800 h-2.5 rounded-full overflow-hidden">
        <div 
            class="h-full transition-all duration-500 ease-in-out" 
            style="width: {progress}%; background-color: {color}"
        ></div>
    </div>
</div>
