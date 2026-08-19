<script>
    let { value, label, borderColor = 'var(--color-accent)' } = $props();
</script>

<div class="bg-card-bg p-5 rounded-xl border-l-5" style="border-color: {borderColor}">
    <div class="text-3xl font-bold">{value}</div>
    <div class="text-gray-400 text-sm">{label}</div>
</div>
