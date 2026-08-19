<script>
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';

	let logs = $state([]);
	let selectedJob = $state(null);
	let isLoading = $state(true);

	async function fetchLogs() {
		try {
			isLoading = true;
			const res = await fetch('/api/audit/logs');
			logs = await res.json();
		} catch (e) {
			console.error(e);
		} finally {
			isLoading = false;
		}
	}

	function selectJob(job) {
		selectedJob = job;
	}

	onMount(() => {
		fetchLogs();
	});
</script>

<div class="mx-auto max-w-[1400px] p-5">
	<header class="mb-10 flex items-center justify-between">
		<h1 class="flex items-center gap-2 text-3xl font-bold text-primary">
			<a href="/" class="text-primary no-underline transition-opacity hover:opacity-80">Talent</a>
			<span class="text-xl text-gray-500">/ Inspección de IA</span>
		</h1>
		<div class="flex gap-3">
			<button
				onclick={fetchLogs}
				class="rounded-lg bg-secondary px-4 py-2 font-bold text-white transition-colors hover:bg-gray-700"
			>
				🔄 Refrescar
			</button>
			<a
				href="/"
				class="rounded-lg bg-gray-800 px-5 py-2.5 font-bold text-white no-underline transition-colors hover:bg-gray-700"
			>
				🏠 Volver al Dashboard
			</a>
		</div>
	</header>

	<div class="grid h-[calc(100vh-180px)] gap-6 lg:grid-cols-12">
		<!-- Sidebar: List of Jobs -->
		<div
			class="flex flex-col overflow-hidden rounded-xl border border-white/5 bg-card-bg lg:col-span-4"
		>
			<div class="border-b border-white/10 bg-black/20 p-4 font-bold">Últimos Registros</div>
			<div class="flex-1 overflow-y-auto">
				{#if isLoading}
					<div class="p-10 text-center text-gray-500 italic">Cargando registros...</div>
				{:else if logs.length === 0}
					<div class="p-10 text-center text-gray-500 italic">No hay registros procesados aún.</div>
				{:else}
					{#each logs as job}
						<button
							onclick={() => selectJob(job)}
							class="w-full border-b border-white/5 p-4 text-left transition-colors hover:bg-white/5 {selectedJob?.id ===
							job.id
								? 'border-l-4 border-l-primary bg-primary/20'
								: ''}"
						>
							<div class="mb-1 flex items-start justify-between">
								<span class="text-sm font-bold">ID: {job.id}</span>
								<div class="flex items-center gap-2">
									{#if job.processing_time}
										<span class="text-[9px] text-gray-400">⏱️ {job.processing_time}s</span>
									{/if}
									<span
										class="rounded px-2 py-0.5 text-[10px] {job.status === 'Matched'
											? 'bg-success/20 text-success'
											: 'bg-red-500/20 text-red-400'}"
									>
										{job.status}
									</span>
								</div>
							</div>
							<div class="truncate text-xs font-semibold text-gray-300">{job.company}</div>
							<div class="truncate text-[10px] text-gray-500">{job.role}</div>
							<div class="mt-2 text-[9px] text-gray-600">{job.updated_at || job.created_at}</div>
						</button>
					{/each}
				{/if}
			</div>
		</div>

		<!-- Main Content: LLM Interaction -->
		<div class="flex flex-col space-y-4 overflow-hidden lg:col-span-8">
			{#if selectedJob}
				<div class="grid flex-1 grid-rows-2 gap-4 overflow-hidden" in:fade>
					<!-- Prompt Area -->
					<div class="flex flex-col overflow-hidden rounded-xl border border-white/5 bg-card-bg">
						<div
							class="flex items-center justify-between border-b border-white/10 bg-blue-900/20 p-3 text-xs font-bold text-blue-400"
						>
							<span>📤 ENVIADO AL LLM (PROMPT)</span>
							<span class="rounded bg-blue-900/40 px-2 py-1 text-[10px]"
								>Tokens estimados: {Math.round((selectedJob.raw_prompt?.length || 0) / 4)}</span
							>
						</div>
						<pre
							class="flex-1 overflow-auto bg-black/30 p-4 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-gray-300 select-all">
                            {selectedJob.raw_prompt ||
								'No hay prompt registrado para este registro.'}
                        </pre>
					</div>

					<!-- Response Area -->
					<div class="flex flex-col overflow-hidden rounded-xl border border-white/5 bg-card-bg">
						<div
							class="flex items-center justify-between border-b border-white/10 bg-green-900/20 p-3 text-xs font-bold text-green-400"
						>
							<span>📥 RECIBIDO DEL LLM (RESPONSE)</span>
							<div class="flex gap-3">
								{#if selectedJob.processing_time}
									<span class="rounded bg-black/40 px-2 py-1 text-[10px] text-gray-300"
										>⏱️ Tiempo: {selectedJob.processing_time}s</span
									>
								{/if}
								{#if selectedJob.match_score}
									<span class="rounded bg-green-900/40 px-2 py-1 text-[10px]"
										>Score Final: {selectedJob.match_score}%</span
									>
								{/if}
							</div>
						</div>
						<pre
							class="flex-1 overflow-auto bg-black/30 p-4 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-green-300 select-all">
                            {(() => {
								try {
									return JSON.stringify(JSON.parse(selectedJob.raw_analysis), null, 2);
								} catch (e) {
									return (
										selectedJob.raw_analysis ||
										'No hay respuesta registrada o tiene formato inválido.'
									);
								}
							})()}
                        </pre>
					</div>
				</div>
			{:else}
				<div
					class="flex flex-1 items-center justify-center rounded-xl border border-dashed border-white/10 bg-card-bg text-gray-500 italic"
				>
					Selecciona un registro de la izquierda para ver los detalles de la interacción con la IA
				</div>
			{/if}
		</div>
	</div>
</div>

<style>
	:global(body) {
		background-color: #0d1117;
		color: #e6edf3;
	}

	pre::-webkit-scrollbar {
		width: 8px;
	}
	pre::-webkit-scrollbar-track {
		background: transparent;
	}
	pre::-webkit-scrollbar-thumb {
		background: rgba(255, 255, 255, 0.1);
		border-radius: 4px;
	}
	pre::-webkit-scrollbar-thumb:hover {
		background: rgba(255, 255, 255, 0.2);
	}
</style>
