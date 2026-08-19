let isActionPending = false;

async function startSearchProcess() {
    if (isActionPending) return;

    const searchBtn = document.getElementById('searchBtn');
    const matchBtn  = document.getElementById('matchBtn');
    const applyBtn  = document.getElementById('applyBtn');

    isActionPending = true;

    // Lock all buttons during transition
    searchBtn.disabled = true;
    matchBtn.disabled  = true;
    applyBtn.disabled  = true;
    searchBtn.innerText = "Iniciando...";

    try {
        await fetch('/search?mode=scan', { method: 'POST' });

        // Optimistic UI: switch search to Stop state
        searchBtn.innerText = "🛑 Detener Búsqueda";
        searchBtn.onclick = stopSearch;
        searchBtn.className = "btn-stop";
        searchBtn.disabled = false;
        applyBtn.style.display = 'none';
        matchBtn.style.display = 'none';
    } catch (e) {
        alert("Error al iniciar búsqueda: " + e);
        searchBtn.innerText = "🔍 Iniciar Búsqueda";
        searchBtn.className = "btn-apply";
        searchBtn.disabled = false;
    } finally {
        isActionPending = false;
    }
}

async function startMatchProcess() {
    const matchBtn = document.getElementById('matchBtn');
    if (isActionPending || matchBtn.disabled) return;
    if (!confirm("¿Iniciar el análisis de matching sobre los trabajos pendientes?")) return;

    const searchBtn = document.getElementById('searchBtn');
    const applyBtn  = document.getElementById('applyBtn');

    isActionPending = true;
    searchBtn.disabled = true;
    matchBtn.disabled  = true;
    applyBtn.disabled  = true;
    matchBtn.innerText = "⏳ Procesando...";

    try {
        // Now calling with mode=match to only process pending items
        await fetch('/search?mode=match', { method: 'POST' });

        searchBtn.innerText = "🛑 Detener";
        searchBtn.onclick = stopSearch;
        searchBtn.className = "btn-stop";
        searchBtn.disabled = false;
        applyBtn.style.display = 'none';
        matchBtn.style.display = 'none';
    } catch (e) {
        alert("Error al iniciar match: " + e);
        matchBtn.innerText = "⚡ Procesar Match";
        matchBtn.disabled = false;
    } finally {
        isActionPending = false;
    }
}

async function startAutoApply() {
    if (isActionPending) return;
    if (!confirm("¿Iniciar Auto-Apply con el último reporte generado?")) return;

    const searchBtn = document.getElementById('searchBtn');
    const applyBtn = document.getElementById('applyBtn');

    isActionPending = true;

    // Disable BOTH buttons
    searchBtn.disabled = true;
    applyBtn.disabled = true;

    applyBtn.innerText = "Iniciando...";
    try {
        await fetch('/apply', { method: 'POST' });
        alert("Se ha iniciado el proceso de Auto-Apply.");
    } catch (e) {
        alert("Error al iniciar Auto-Apply: " + e);
    } finally {
        isActionPending = false;
    }
}

async function stopSearch() {
    if (!confirm("¿Seguro que deseas detener la búsqueda? Se guardará el reporte actual.")) return;
    const btn = document.getElementById('searchBtn');
    isActionPending = true;
    btn.disabled = true;
    btn.innerText = "Deteniendo...";

    try {
        await fetch('/stop', { method: 'POST' });
        alert("Se ha enviado la señal de parada.");
    } catch (e) {
        alert("Error al enviar señal: " + e);
    } finally {
        isActionPending = false;
    }
}

function updateUI(data) {
    const statusData = data.status || {};
    const statsData  = data.stats  || {};
    const pendingCount = typeof data.pending_count === 'number' ? data.pending_count : 0;

    const searchBtn = document.getElementById('searchBtn');
    const matchBtn  = document.getElementById('matchBtn');
    const applyBtn  = document.getElementById('applyBtn');

    if (!searchBtn || !matchBtn || !applyBtn) return;

    const isRunning = statusData.status && statusData.status.toLowerCase().includes('running');
    const isClosing = statusData.status && statusData.status.toLowerCase().includes('closing');

    if (isClosing) {
        searchBtn.innerText = "⏳ Cerrando (Match terminando...)";
        searchBtn.disabled = true;
        searchBtn.className = "btn-stop";
        applyBtn.style.display = 'none';
        matchBtn.style.display = 'none';
    } else if (isRunning) {
        searchBtn.innerText = "🛑 Detener Búsqueda";
        searchBtn.onclick = stopSearch;
        searchBtn.className = "btn-stop";
        searchBtn.disabled = false;
        applyBtn.style.display = 'none';
        matchBtn.style.display = 'none';
    } else {
        // Idle state — restore all buttons
        searchBtn.innerText = "🔍 Iniciar Búsqueda";
        searchBtn.onclick = startSearchProcess;
        searchBtn.className = "btn-apply";
        searchBtn.disabled = false;

        // Show/Hide apply button based on matched count
        const matchedCount = statsData.status_breakdown ? (statsData.status_breakdown.Matched || 0) : 0;
        if (matchedCount > 0) {
            applyBtn.style.display = 'inline-block';
            applyBtn.disabled = false;
        } else {
            applyBtn.style.display = 'none';
        }

        // Show/Hide match button based on pending count
        const badge = document.getElementById('matchPendingBadge');
        if (pendingCount > 0) {
            matchBtn.style.display = 'inline-block';
            matchBtn.disabled = false;
            matchBtn.title = `${pendingCount} ofertas pendientes de analizar`;
            if (badge) {
                badge.innerText = pendingCount;
                badge.style.display = 'inline-block';
            }
        } else {
            matchBtn.style.display = 'none'; // Hide if nothing to process
            matchBtn.disabled = true;
            if (badge) badge.style.display = 'none';
        }
    }

    document.getElementById('totalMatches').innerText = statsData.total_matches || 0;
    document.getElementById('currentRole').innerText = statusData.current_role || "Ready";
    document.getElementById('currentLocation').innerText = statusData.current_location || "-";
    document.getElementById('processingCount').innerText = statusData.processing_count || 0;

    // Update Resume Section
    const targetRes = statusData.target_resume || '-';
    const actualRes = statusData.actual_resume || '-';
    const resumeSection = document.getElementById('resumeSection');
    if (resumeSection) {
        if (targetRes !== '-' || actualRes !== '-') {
            resumeSection.style.display = 'block';
            document.getElementById('targetResume').innerText = targetRes;
            document.getElementById('actualResume').innerText = actualRes;
            document.getElementById('actualResume').style.color = actualRes !== '-' ? '#27ae60' : '#888';
        } else {
            resumeSection.style.display = 'none';
        }
    }

    const globalPct = (statusData.current_combination_index / Math.max(statusData.total_combinations, 1)) * 100;
    document.getElementById('globalProgressBar').style.width = globalPct + '%';
    document.getElementById('globalProgressText').innerText =
        `${statusData.current_combination_index} / ${statusData.total_combinations}`;

    const batchPct = (statusData.current_job_index / Math.max(statusData.jobs_in_current_batch, 1)) * 100;
    document.getElementById('batchProgressBar').style.width = batchPct + '%';
    document.getElementById('batchProgressText').innerText =
        statusData.jobs_in_current_batch > 0 ? `Oferta ${statusData.current_job_index} de ${statusData.jobs_in_current_batch}` : "Escaneando...";

    const matchesList = document.getElementById('matchesList');
    const recentMatches = statsData.recent_matches || [];
    
    if (recentMatches.length > 0) {
        matchesList.innerHTML = recentMatches.map(m => `
            <div class="match-item">
                <div>
                    <strong>${m.company}</strong> (${m.location})<br>
                    <small>${m.role || 'Unknown'}</small> • <small style="color: #F1C40F;">${m.date || 'Unknown'}</small><br>
                    <small>${m.work_mode}</small> • <small style="color: #aaa; font-family: monospace;">[${m.created_at ? m.created_at.split(' ')[1] : '-'}]</small>
                </div>
                <div style="text-align:right;">
                    <div class="match-score" style="color:#27ae60;">${m.match_score}% (DS)</div>
                    <div style="font-family:monospace; font-size:0.8em; color:var(--accent);">ID: ${m.id}</div>
                </div>
            </div>
        `).join('');
    } else {
        matchesList.innerHTML = '<div class="match-item">Sin coincidencias recientes</div>';
    }

    const consoleDiv = document.getElementById('consoleLog');
    if (consoleDiv) {
        consoleDiv.innerHTML = (statusData.logs || []).join('<br>> ');
    }

    // Update last update timestamp
    const now = new Date();
    const pad = n => String(n).padStart(2, '0');
    const timeStr = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ` +
                  `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    const timeEl = document.getElementById('lastUpdateTime');
    if (timeEl) timeEl.innerText = timeStr;
}

async function checkInteraction() {
    try {
        const response = await fetch('/check_interaction');
        const data = await response.json();
        const modal = document.getElementById('interventionModal');
        if (!modal) return;

        if (data.status === 'waiting_for_user') {
            modal.style.display = 'flex';
            document.getElementById('modalQuestion').innerText = data.question || "Pregunta desconocida";
        } else {
            modal.style.display = 'none';
            const input = document.getElementById('modalAnswer');
            if (input) input.value = '';
        }
    } catch (e) {
        console.log("Error checking interaction:", e);
    }
}

async function submitInteraction() {
    const answer = document.getElementById('modalAnswer').value;
    if (!answer) return alert("Por favor escribe una respuesta.");

    try {
        await fetch('/submit_answer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ answer: answer })
        });
        document.getElementById('interventionModal').style.display = 'none';
    } catch (e) {
        alert("Error enviando respuesta: " + e);
    }
}

function initSSE() {
    console.log("Initializing SSE...");
    const evtSource = new EventSource("/events");

    evtSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateUI(data);
        } catch (e) {
            console.error("SSE parse error:", e);
        }
    };

    evtSource.onerror = (err) => {
        console.error("EventSource failed:", err);
        evtSource.close();
        setTimeout(initSSE, 5000); // Retry in 5s
    };
}

setInterval(checkInteraction, 3000);
initSSE();
