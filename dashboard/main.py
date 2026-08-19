import os
import json
import subprocess
import asyncio
import time
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import sys
# Paths setup
CURRENT_FILE = os.path.abspath(__file__)
DASHBOARD_DIR = os.path.dirname(CURRENT_FILE)
ROOT_DIR = os.path.dirname(DASHBOARD_DIR)
sys.path.insert(0, ROOT_DIR)

import src.services.storage.database as db
from src.application.use_cases.dashboard_actions import (
    ClearJobsUseCase, StopProcessesUseCase, SubmitAnswerUseCase, 
    ExecuteApplyBotUseCase, StartSearchUseCase, AuditDecisionUseCase
)
from src.application.use_cases.reanalyze_job import ReanalyzeJobUseCase
from src.services.ai.client import JobAnalyzer
from src.monitor import SearchMonitor
from src.services.storage.database import get_pending_job_count

app = FastAPI(title=" Dashboard API")

# Signal Files
SIGNAL_FILE = os.path.join(DASHBOARD_DIR, "stop.signal")
INTERACTION_FILE = os.path.join(DASHBOARD_DIR, "interaction.json")
STATUS_FILE = os.path.join(DASHBOARD_DIR, "status.json")

# Infrastructure/App setup
monitor = SearchMonitor(STATUS_FILE)
clear_use_case = ClearJobsUseCase(monitor)
stop_use_case = StopProcessesUseCase(monitor, SIGNAL_FILE)
answer_use_case = SubmitAnswerUseCase(monitor, INTERACTION_FILE)
apply_use_case = ExecuteApplyBotUseCase(monitor)
start_search_use_case = StartSearchUseCase(monitor)
audit_use_case = AuditDecisionUseCase(db.get_connection(), None, monitor)
reanalyze_use_case = ReanalyzeJobUseCase(JobAnalyzer(), monitor)

# Mount Old Static (Legacy/Reports)
app.mount("/static", StaticFiles(directory=os.path.join(DASHBOARD_DIR, "static")), name="static")

# TEMPLATES SETUP (Jinja2)
templates = Jinja2Templates(directory=os.path.join(DASHBOARD_DIR, "templates"))

# Mount Svelte Build Assets
SVELTE_BUILD_DIR = os.path.join(ROOT_DIR, "dashboard-svelte/build")
if os.path.exists(SVELTE_BUILD_DIR):
    app.mount("/_app", StaticFiles(directory=os.path.join(SVELTE_BUILD_DIR, "_app")), name="svelte_assets")

# Global State
class GlobalState:
    active_process: Optional[subprocess.Popen] = None

state = GlobalState()

# Helpers
def nuke_orphans():
    """Aggressively kills any orphan bot or chrome processes from previous sessions."""
    print("   [Process Guard] 🧹 Cleaning up orphan processes for a fresh start...")
    try:
        # Use pkill for broad cleanup based on naming patterns
        os.system("pkill -9 -f inspect_apply.py > /dev/null 2>&1")
        os.system("pkill -9 -f 'python3 -m src.main' > /dev/null 2>&1")
        os.system("pkill -9 -f 'python3 -m src.apply_bot' > /dev/null 2>&1")
        # We don't pkill all chrome because user might have other chromes open, 
        # but playwright-initiated ones usually have specific flags. 
        # We'll focus on PGID for current session, and pkill bot processes for the rest.
    except: pass

def update_status_ready():
    try:
        print("   [DB] 🔄 Resetting dashboard status to Ready...")
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, "r") as f:
                data = json.load(f)
        else:
            data = {}
        
        data["status"] = "Ready"
        data["last_updated"] = time.time()
        # Reset transient progress
        data["current_role"] = "Ready"
        data["current_location"] = "-"
        data["current_job_index"] = 0
        data["jobs_in_current_batch"] = 0
        data["target_resume"] = "-"
        data["actual_resume"] = "-"
        
        # KEY FIX: Clear diagnostic phantom state
        data["diagnostics"] = {
            "active": False,
            "schema": [],
            "answers": {},
            "traffic_in": None,
            "traffic_out": None,
            "last_event": "Ready"
        }
        
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print("   [DB] ✅ Dashboard and Diagnostics are now Ready.")
    except Exception as e:
        print(f"Error updating status.json: {e}")

# Endpoints
# Helpers to serve frontend
def serve_index():
    svelte_index = os.path.join(SVELTE_BUILD_DIR, "index.html")
    if os.path.exists(svelte_index):
        with open(svelte_index, "r", encoding="utf-8") as f:
            return f.read()
    with open(os.path.join(DASHBOARD_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    return serve_index()

@app.get("/inspect", response_class=HTMLResponse)
async def get_inspect():
    return serve_index()

@app.get("/status.json")
async def get_status():
    if state.active_process:
        if state.active_process.poll() is not None:
            print(f"Process {state.active_process.pid} finished.")
            state.active_process = None
            update_status_ready()
            
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            return json.load(f)
    return {"status": "Ready", "logs": []}

@app.get("/api/status")
async def get_api_status():
    """Alias for status.json used by the inspection dashboard."""
    return await get_status()

@app.get("/api/stats")
async def get_stats():
    try:
        return db.get_dashboard_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/pending_count")
async def api_pending_count():
    """Returns the number of jobs waiting to be analyzed (match pending)."""
    try:
        count = get_pending_job_count()
        return {"pending_count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jobs")
async def get_jobs(
    page: int = 1,
    page_size: int = 100,
    q: Optional[str] = None,
    status: Optional[str] = None,
    mode: Optional[str] = None,
    apply_type: Optional[str] = None,
    lang: Optional[str] = None
):
    try:
        offset = (page - 1) * page_size
        jobs = db.get_filtered_jobs(
            limit=page_size,
            offset=offset,
            q=q,
            status=status,
            mode=mode,
            apply_type=apply_type,
            lang=lang
        )
        total = db.get_total_jobs_count(
            q=q,
            status=status,
            mode=mode,
            apply_type=apply_type,
            lang=lang
        )
        return {
            "jobs": jobs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/audit/logs")
async def get_audit_logs():
    try:
        # Returns only analyzed jobs for auditing
        return db.get_audit_jobs()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/check_interaction")
async def check_interaction():
    if os.path.exists(INTERACTION_FILE):
        try:
            with open(INTERACTION_FILE, "r") as f:
                data = json.load(f)
                if data.get("status") == "waiting_for_user":
                    return data
        except: pass
    return {}

class AnswerPayload(BaseModel):
    answer: str

@app.get("/events")
async def events(request: Request):
    async def event_generator():
        last_payload_str = ""
        while True:
            # Check if client is still connected
            if await request.is_disconnected():
                break

            try:
                # 1. Check for status updates
                status_data = {}
                if os.path.exists(STATUS_FILE):
                    try:
                        with open(STATUS_FILE, "r") as f:
                            status_data = json.load(f)
                    except: pass
                
                # 2. Check for process termination
                process_finished = False
                if state.active_process:
                    if state.active_process.poll() is not None:
                        print(f"   [SSE] Process {state.active_process.pid} detected as naturally finished.")
                        state.active_process = None
                        process_finished = True
                
                # 3. GHOST CHECK: If status is 'Running' but no active_process is tracked 
                # (e.g. server restarted or process crashed without reaping), reset to Ready.
                if status_data.get("status") == "Running" and not state.active_process:
                    print("   [SSE] Detected ghost 'Running' status. Resetting to Ready.")
                    update_status_ready()
                    status_data["status"] = "Ready" # Update local copy for immediate emission
                elif process_finished:
                    update_status_ready()
                    status_data["status"] = "Ready"

                stats_data = db.get_dashboard_stats()
                
                # Include real-time pending count (lightweight, not cached)
                try:
                    pending_count = get_pending_job_count()
                except Exception:
                    pending_count = 0
                
                payload = {
                    "status": status_data,
                    "stats": stats_data,
                    "pending_count": pending_count
                }
                
                # Dynamic Change Detection: Only send if data evolved
                payload_str = json.dumps(payload, sort_keys=True)
                if payload_str != last_payload_str:
                    yield f"data: {payload_str}\n\n"
                    last_payload_str = payload_str
                
                # Heartbeat every 15s to keep connection alive even with no data
                # (Optional, but good practice for SSE behind proxies)
                
                # Wait before next check
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Error in SSE generator: {e}")
                await asyncio.sleep(2)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/submit_answer")
async def submit_answer(payload: AnswerPayload):
    try:
        answer_use_case.execute(payload.answer)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search")
async def start_search(mode: Optional[str] = None):
    if state.active_process and state.active_process.poll() is None:
        raise HTTPException(status_code=409, detail="Another process is already running")
    
    try:
        start_search_use_case.execute()
        
        # 1. Update status to Running immediately
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, "r") as f:
                data = json.load(f)
        else:
            data = {}
        data["status"] = "Running"
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f, indent=2)

        if os.path.exists(SIGNAL_FILE):
            os.remove(SIGNAL_FILE)
            
        log_path = os.path.join(DASHBOARD_DIR, "apply.log") 
        nuke_orphans() # Ensure clean slate before starting

        # Build command based on mode
        cmd = ["python3", "-m", "src.main"]
        if mode == "scan":
            cmd.append("--scan")
        elif mode == "match":
            cmd.append("--match")
            cmd.append("--re-analyze")

        proc = subprocess.Popen(
            cmd,
            cwd=ROOT_DIR,
            stdout=open(log_path, "w"),
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
            preexec_fn=os.setsid # Create process group
        )
        state.active_process = proc
        return {"status": "running", "pid": proc.pid, "mode": mode or "full"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/apply")
async def start_apply():
    if state.active_process and state.active_process.poll() is None:
        raise HTTPException(status_code=409, detail="Another process is already running")
    
    try:
        apply_use_case.execute()
        
        # 1. Update status to Running immediately
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, "r") as f:
                data = json.load(f)
        else:
            data = {}
        data["status"] = "Running"
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f, indent=2)

        if os.path.exists(SIGNAL_FILE):
            os.remove(SIGNAL_FILE)
            
        log_path = os.path.join(DASHBOARD_DIR, "apply_debug.log")
        nuke_orphans() # Ensure clean slate
        proc = subprocess.Popen(
            ["python3", "-m", "src.apply_bot"],
            cwd=ROOT_DIR,
            stdout=open(log_path, "w"),
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
            preexec_fn=os.setsid # Create process group
        )
        state.active_process = proc
        return {"status": "running", "pid": proc.pid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/stop")
async def stop_process():
    try:
        # 1. ALWAYS write the stop signal file first
        stop_use_case.execute()
        
        # 2. Force Kill if we have a handle
        if state.active_process:
            import signal
            pid = state.active_process.pid
            print(f"🛑 [Process Guard] 💥 Nuking process group {pid} and its children...")
            
            try:
                # Nuke the entire process group (PGID)
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                time.sleep(0.5)
                if state.active_process.poll() is None:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
            except: pass
            
            state.active_process = None
        
        # 3. Aggressive cleanup fallback
        nuke_orphans()
        
        # 4. Force status reset
        monitor.update(status="Ready")
        return {"status": "stopping"}
    except Exception as e:
        print(f"❌ Error in /stop: {e}")
        # Even on error, try to return something positive to the UI
        monitor.update(status="Ready")
        return {"status": "error_but_stopped"}

@app.get("/inspection", response_class=HTMLResponse)
async def inspection_page(request: Request):
    return templates.TemplateResponse("inspect_live.html", {"request": request})

@app.post("/api/inspection/next")
async def interaction_next():
    try:
        signal_file = os.path.join(DASHBOARD_DIR, "interaction.json")
        with open(signal_file, "w") as f:
            json.dump({"action": "NEXT", "timestamp": time.time()}, f)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/inspection/start")
async def start_inspection():
    try:
        if state.active_process:
             return {"status": "already_running"}
             
        env = os.environ.copy()
        env["MONITOR_MASTER"] = "true"
        # Ensure DISPLAY and XAUTHORITY are passed for Linux GUI
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0" # Default for most Linux desktops
        
        # LOG REDIRECTION: Capture all logs to dashboard/inspector.log
        log_path = os.path.join(DASHBOARD_DIR, "inspector.log")
        log_file = open(log_path, "w")
        
        nuke_orphans() # Fresh start
        
        # KEY FIX: Tell the UI we are actively inspecting
        monitor.update(status="Inspeccionando", diagnostics={"active": True, "last_event": "Iniciando explorador visual..."})
        
        cmd = [sys.executable, "inspect_apply.py", "--step", "--limit", "5"]
        state.active_process = subprocess.Popen(cmd, env=env, stdout=log_file, stderr=log_file, preexec_fn=os.setsid)
        
        return {"status": "started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/inspection/stop")
async def stop_inspection():
    try:
        # 1. Write the general stop signal for a clean exit of the loop
        if not os.path.exists(SIGNAL_FILE):
             with open(SIGNAL_FILE, "w") as f:
                 f.write("STOP")

        # 2. Kill the handle if active
        if state.active_process:
            import signal
            pid = state.active_process.pid
            try:
                # Nuke the entire group (Bot + Chrome)
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                time.sleep(0.5)
                if state.active_process.poll() is None:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
            except: pass
            
            state.active_process = None
        
        # 3. Fallback cleanup
        nuke_orphans()
            
        # 4. ALWAYS Reset monitor diagnostics even if no process handle was found
        # this ensures the UI button changes back to 'Start'
        m = SearchMonitor(STATUS_FILE)
        m.update(status="Ready", diagnostics={"active": False, "schema": [], "answers": {}, "last_event": "Stopped from Dashboard"})

        return {"status": "stopped"}
    except Exception as e:
        print(f"❌ Error in /api/inspection/stop: {e}")
        # Force UI reset anyway
        update_status_ready()
        return {"status": "error_but_stopped"}

@app.post("/api/inspection/clear")
async def clear_inspection_logs():
    """
    Clears ONLY the visual logs and diagnostics from the inspection dashboard.
    Does NOT touch the jobs database.
    """
    try:
        # 1. Reset monitor logs and diagnostics
        monitor.update(
            logs=[f"[{time.strftime('%H:%M:%S')}] 🧹 Logs de inspección limpiados."],
            diagnostics={
                "active": False,
                "schema": [],
                "answers": {},
                "last_event": "Limpiado"
            }
        )
        return {"status": "ok"}
    except Exception as e:
        print(f"❌ Error in /api/inspection/clear: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/reports", response_class=HTMLResponse)
async def get_reports():
    reports_path = os.path.join(DASHBOARD_DIR, "reports.html")
    if os.path.exists(reports_path):
        with open(reports_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>No reports yet</h1>"

@app.post("/api/clear_jobs")
async def clear_jobs():
    import time
    try:
        if state.active_process:
            state.active_process.terminate()
            state.active_process = None
            
        os.system("pkill -9 -f 'python3 -m src.main' > /dev/null 2>&1")
        clear_use_case.execute()
        
        # Clear dashboard state completely
        empty_state = {
            "total_combinations": 0,
            "current_combination_index": 0,
            "current_role": "Ready",
            "current_location": "-",
            "jobs_in_current_batch": 0,
            "current_job_index": 0,
            "processing_count": 0,
            "total_matches": 0,
            "recent_matches": [],
            "logs": [f"[{time.strftime('%H:%M:%S')}] 🧹 Base de datos y panel limpiados."],
            "status": "Ready",
            "diagnostics": {
                "active": False,
                "schema": [],
                "answers": {},
                "last_event": "Limpiado"
            },
            "last_updated": time.time()
        }
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(empty_state, f, indent=2)
            
        # Clear audit and activity logs if they exist
        audit_file = os.path.join(DASHBOARD_DIR, "audit.csv")
        if os.path.exists(audit_file):
            os.remove(audit_file)
            
        activity_file = os.path.join(DASHBOARD_DIR, "activity.log")
        if os.path.exists(activity_file):
            os.remove(activity_file)
            
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/audit/{span_id}")
async def audit_span(span_id: str):
    try:
        is_valid = audit_use_case.execute(span_id)
        return {"status": "ok", "valid": is_valid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jobs/{job_id}/reanalyze")
async def reanalyze_job(job_id: int):
    try:
        result = reanalyze_use_case.execute(job_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Job not found or description too short")
        data = result.get("data") or {}
        return {"status": "ok", "match_score": data.get("match_percentage", 0)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class BulkUpdatePayload(BaseModel):
    job_ids: List[int]
    new_status: str

@app.post("/api/jobs/bulk_update")
async def bulk_update_jobs(payload: BulkUpdatePayload):
    try:
        if not payload.job_ids:
             return {"status": "ok", "message": "No jobs to update"}
        
        # Valid statuses to prevent SQL injection or weird states
        valid_statuses = ['Pending', 'Discarded', 'Matched', 'Applied', 'Failed']
        if payload.new_status not in valid_statuses:
             raise HTTPException(status_code=400, detail=f"Invalid status: {payload.new_status}")
             
        for job_id in payload.job_ids:
             # Sync Match Score and AI Analysis for clarity in reports
             target_score = None
             target_analysis = None
             
             if payload.new_status == 'Matched':
                 target_score = 100
                 job_data = db.get_job_by_id(job_id)
                 if job_data and job_data.get('raw_analysis'):
                     try:
                         analysis = json.loads(job_data['raw_analysis'])
                         analysis['verdict'] = 'APPLY'
                         analysis['reason'] = "Manual Match"
                         target_analysis = json.dumps(analysis)
                     except: pass
                 if not target_analysis:
                     target_analysis = json.dumps({"verdict": "APPLY", "match_percentage": 100, "reason": "Manual Match"})
             
             elif payload.new_status == 'Discarded':
                 target_score = 0
                 job_data = db.get_job_by_id(job_id)
                 if job_data and job_data.get('raw_analysis'):
                     try:
                         analysis = json.loads(job_data['raw_analysis'])
                         analysis['verdict'] = 'REJECT'
                         analysis['reason'] = "Manual Discard"
                         target_analysis = json.dumps(analysis)
                     except: pass
                 if not target_analysis:
                     target_analysis = json.dumps({"verdict": "REJECT", "match_percentage": 0, "reason": "Manual Discard"})

             db.update_job_status(
                 job_id, 
                 payload.new_status, 
                 error="Status changed manually via Bulk Update",
                 match_score=target_score,
                 raw_analysis=target_analysis
             )
             
        # Important: this doesn't automatically trigger an SSE update unless stats change significantly
        # but the frontend loadJobs() will refresh the view immediately.
        
        return {"status": "ok", "updated_count": len(payload.job_ids)}
    except Exception as e:
        print(f"Error in bulk update: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    update_status_ready()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

