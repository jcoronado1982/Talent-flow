<script>
	import { onMount } from 'svelte';
	import StatsCard from '$lib/components/StatsCard.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import MatchItem from '$lib/components/MatchItem.svelte';
	import Console from '$lib/components/Console.svelte';
	import InteractionModal from '$lib/components/InteractionModal.svelte';

	// State
	let status = $state({
		status: 'Ready',
		current_role: 'Ready',
		current_location: '-',
		total_combinations: 0,
		current_combination_index: 0,
		jobs_in_current_batch: 0,
		current_job_index: 0,
		processing_count: 0,
		target_resume: '-',
		actual_resume: '-',
		logs: []
	});

	let stats = $state({
		total_matches: 0,
		recent_matches: []
	});

	let interaction = $state({
		status: 'none',
		question: ''
	});

	let isActionPending = $state(false);

	// Derived values
	let globalPct = $derived(
		(status.current_combination_index / Math.max(status.total_combinations, 1)) * 100
	);
	let batchPct = $derived(
		(status.current_job_index / Math.max(status.jobs_in_current_batch, 1)) * 100
	);
	let isRunning = $derived(status.status?.toLowerCase().includes('running'));
	let isClosing = $derived(status.status?.toLowerCase().includes('closing'));

	// API Actions
	function initSSE() {
		const evtSource = new EventSource('/events');

		evtSource.onmessage = (event) => {
			try {
				const data = JSON.parse(event.data);
				if (data.status) status = data.status;
				if (data.stats) stats = data.stats;
			} catch (e) {
				console.error('SSE parse error:', e);
			}
		};

		evtSource.onerror = (err) => {
			console.error('SSE error:', err);
			evtSource.close();
			setTimeout(initSSE, 5000);
		};

		return evtSource;
	}

	async function checkInteraction() {
		try {
			const res = await fetch('/check_interaction');
			const data = await res.json();
			interaction = data;
		} catch (e) {
			console.error('Interaction error:', e);
		}
	}

	async function startSearch() {
		isActionPending = true;
		try {
			await fetch('/search', { method: 'POST' });
		} catch (e) {
			alert('Error: ' + e);
		} finally {
			isActionPending = false;
		}
	}

	async function stopSearch() {
		isActionPending = true;
		try {
			// Optimistic UI update if possible, though SSE will handle it eventually
			const res = await fetch('/stop', { method: 'POST' });
			const data = await res.json();
			if (data.status === 'stopping') {
				console.log('Stop request sent successfully');
			}
		} catch (e) {
			alert('Error: ' + e);
		} finally {
			// We keep isActionPending true for a bit to avoid rapid clicks
			setTimeout(() => { isActionPending = false; }, 1000);
		}
	}

	async function startApply() {
		isActionPending = true;
		try {
			await fetch('/apply', { method: 'POST' });
		} catch (e) {
			alert('Error: ' + e);
		} finally {
			isActionPending = false;
		}
	}

	/** @param {string} answer */
	async function handleAnswer(answer) {
		try {
			await fetch('/submit_answer', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ answer })
			});
			interaction = { status: 'none', question: '' };
		} catch (e) {
			alert('Error: ' + e);
		}
	}

	onMount(() => {
		const evtSource = initSSE();
		const interactionInterval = setInterval(checkInteraction, 3000);
		checkInteraction();

		return () => {
			evtSource.close();
			clearInterval(interactionInterval);
		};
	});
</script>

<div class="mx-auto max-w-[1200px] p-5">
	<header class="mb-10 flex items-center justify-between">
		<h1 class="flex items-center gap-2 text-3xl font-bold text-primary">
			<span>🤖</span>
		</h1>
		<div class="flex gap-3">
			{#if isClosing}
				<button
					disabled
					class="cursor-not-allowed rounded-lg bg-red-900 px-5 py-2.5 font-bold text-white opacity-70"
				>
					⏳ Cerrando...
				</button>
			{:else if isRunning}
				<button
					disabled={isActionPending}
					onclick={stopSearch}
					class="rounded-lg bg-red-600 px-5 py-2.5 font-bold text-white transition-colors hover:bg-red-700"
				>
					🛑 Detener Búsqueda
				</button>
			{:else}
				<button
					disabled={isActionPending}
					onclick={startSearch}
					class="rounded-lg bg-success px-5 py-2.5 font-bold text-white transition-colors hover:bg-green-600"
				>
					🚀 Iniciar Búsqueda
				</button>
				<button
					disabled={isActionPending}
					onclick={startApply}
					class="rounded-lg bg-blue-600 px-5 py-2.5 font-bold text-white transition-colors hover:bg-blue-700"
				>
					📄 Auto Aplicar
				</button>
			{/if}
			<a
				href="/inspect"
				class="flex items-center gap-2 rounded-lg border border-white/10 bg-card-bg px-5 py-2.5 font-bold text-white no-underline transition-colors hover:bg-gray-700"
			>
				🔍 Inspección IA
			</a>
			<a
				href="/reports"
				target="_blank"
				class="rounded-lg bg-primary px-5 py-2.5 font-bold text-white no-underline transition-colors hover:bg-purple-700"
			>
				📊 Reportes
			</a>
		</div>
	</header>

	<!-- Stats Grid -->
	<div class="mb-8 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
		<StatsCard
			value={stats.total_matches}
			label="Coincidencias (>30%)"
			borderColor="var(--color-accent)"
		/>
		<StatsCard
			value={status.current_role || 'Ready'}
			label="Rol Actual"
			borderColor="var(--color-primary)"
		/>
		<StatsCard value={status.current_location || '-'} label="Ubicación" borderColor="#3498DB" />
		<StatsCard
			value={status.processing_count || 0}
			label="⚙️ En Proceso"
			borderColor="var(--color-accent)"
		/>
	</div>

	<!-- Resume Tracking -->
	{#if status.target_resume !== '-' || status.actual_resume !== '-'}
		<div class="mb-8 rounded-xl border border-white/5 bg-card-bg p-6 shadow-xl" in:fade>
			<h3 class="mb-3 text-sm font-bold tracking-wider text-accent uppercase">📄 Resume Status</h3>
			<div class="grid gap-6 md:grid-cols-2">
				<div class="space-y-1">
					<div class="text-xs font-semibold text-gray-500 uppercase">📤 Proposed (Debe enviar)</div>
					<div
						class="truncate rounded border border-white/5 bg-black/30 p-2 font-mono text-sm text-blue-400"
						title={status.target_resume}
					>
						{status.target_resume}
					</div>
				</div>
				<div class="space-y-1">
					<div class="text-xs font-semibold text-gray-500 uppercase">✅ Sent (Envió)</div>
					<div
						class="font-mono text-sm {status.actual_resume !== '-'
							? 'text-success'
							: 'text-gray-600 italic'} truncate rounded border border-white/5 bg-black/30 p-2"
						title={status.actual_resume}
					>
						{status.actual_resume}
					</div>
				</div>
			</div>
		</div>
	{/if}

	<!-- Progress Sections -->
	<div class="mb-8 space-y-4">
		<ProgressBar
			label="Progreso Total (Búsquedas)"
			progress={globalPct}
			text="{status.current_combination_index} / {status.total_combinations}"
		/>
		<ProgressBar
			label="Lote Actual (Ofertas)"
			progress={batchPct}
			color="var(--color-accent)"
			text={status.jobs_in_current_batch > 0
				? `Oferta ${status.current_job_index} de ${status.jobs_in_current_batch}`
				: 'Escaneando...'}
		/>
	</div>

	<!-- Recent Matches & Console -->
	<div class="grid gap-6 lg:grid-cols-2">
		<section class="rounded-xl bg-card-bg p-6">
			<h3 class="mb-4 flex items-center gap-2 text-xl font-bold">🔥 Últimas Coincidencias</h3>
			<div class="max-h-[400px] space-y-3 overflow-y-auto pr-2">
				{#each stats.recent_matches as match}
					<MatchItem {match} />
				{:else}
					<div class="bg-black/20 p-4 rounded-lg text-center text-gray-500 italic">
						Sin coincidencias recientes
					</div>
				{/each}
			</div>
		</section>

		<section class="rounded-xl bg-card-bg p-6">
			<h3 class="mb-4 flex items-center gap-2 text-xl font-bold">🖥️ Log de Actividad</h3>
			<Console logs={status.logs} />
		</section>
	</div>
</div>

<InteractionModal
	show={interaction.status === 'waiting_for_user'}
	question={interaction.question}
	onAnswer={handleAnswer}
/>
