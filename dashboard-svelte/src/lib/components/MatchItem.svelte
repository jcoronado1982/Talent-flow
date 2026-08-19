<script>
    let { match } = $props();
</script>

<div class="bg-[#252525] p-3 rounded-lg flex justify-between items-center border border-gray-800 hover:border-accent transition-colors">
    <div>
        <strong class="text-gray-100">{match.company}</strong> 
        <span class="text-sm text-gray-400">({match.location})</span><br>
        <small class="text-gray-400">{match.role || 'Unknown'}</small> • 
        <small class="text-yellow-500">{match.date || 'Unknown'}</small><br>
        <small class="text-gray-400">{match.work_mode}</small> • 
        <small class="text-blue-400">{match.language || '?'}</small> • 
        <small class="text-gray-500 font-mono">[{match.created_at ? match.created_at.split(' ')[1] : '-'}]</small>
    </div>
    <div class="text-right">
        <div class="font-bold text-success">{match.match_score}% (DS)</div>
        <div class="font-mono text-[0.8em] text-accent">ID: {match.id}</div>
    </div>
</div>
