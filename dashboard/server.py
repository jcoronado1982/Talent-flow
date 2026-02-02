import http.server
import socketserver
import os
import json

PORT = 8001
import subprocess

# Paths setup
CURRENT_FILE = os.path.abspath(__file__)
DASHBOARD_DIR = os.path.dirname(CURRENT_FILE)
ROOT_DIR = os.path.dirname(DASHBOARD_DIR)

# Ensure checking stop signal in Dashboard dir to match src/main.py
import sys
sys.path.append(ROOT_DIR) # Allow importing src modules
import src.services.storage.database as db
SIGNAL_FILE = os.path.join(DASHBOARD_DIR, "stop.signal")
INTERACTION_FILE = os.path.join(DASHBOARD_DIR, "interaction.json")


# Serve files from the dashboard directory
os.chdir(DASHBOARD_DIR)
print(f"Server working directory set to: {DASHBOARD_DIR}")

# Track active process
active_process = None

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        global active_process
        if self.path.startswith('/status.json'):
            # Health Check: actively check if the process is still running
            if active_process:
                poll = active_process.poll()
                if poll is not None: # Process has finished/died
                    print(f"ℹ️ Process finished with code {poll}. Updating status to Ready.")
                    active_process = None
                    
                    # Update status.json to Ready
                    try:
                        status_path = os.path.join(DASHBOARD_DIR, "status.json")
                        if os.path.exists(status_path):
                            with open(status_path, "r") as f:
                                data = json.load(f)
                        else:
                            data = {}
                        
                        data["status"] = "Ready"
                        
                        with open(status_path, "w") as f:
                            json.dump(data, f, indent=2)
                    except Exception as e:
                        print(f"⚠️ Error updating status.json during GET: {e}")
            
            # Also, if we have NO active_process but the file says Running (e.g. server restart),
            # we should probably trust the file OR treat it as stale. 
            # For now, let's assume if this server instance didn't start it, it's stale.
            # (Limitation: If server restarts while bot is running, we lose track. 
            #  But given the use case, this is acceptable for now to prevent stuck UI).
            #  But given the use case, this is acceptable for now to prevent stuck UI).

        if self.path == '/check_interaction':
            # Check if interaction file exists and needs attention
            if os.path.exists(INTERACTION_FILE):
                try:
                    with open(INTERACTION_FILE, "r") as f:
                        data = json.load(f)
                        # Only return if status is waiting_for_user
                        if data.get("status") == "waiting_for_user":
                            self.send_response(200)
                            self.send_header('Content-type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps(data).encode())
                            return
                except: pass
            
            # Default empty
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({}).encode())
            return
        
        if self.path == '/reports':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            with open(os.path.join(DASHBOARD_DIR, "reports.html"), "rb") as f:
                self.wfile.write(f.read())
            return

        if self.path == '/api/jobs':
                try:
                    jobs = db.get_all_jobs()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(jobs).encode())
                except Exception as e:
                    print(f"API Error: {e}")
                    self.send_error(500)
                return

        if self.path == '/api/stats':
                try:
                    stats = db.get_dashboard_stats()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(stats).encode())
                except Exception as e:
                    print(f"Stats Error: {e}")
                    self.send_error(500)
                return

        return super().do_GET()

    def do_POST(self):
        global active_process
        
        if self.path == '/stop':
            # 1. Create stop signal (Soft Stop)
            with open(SIGNAL_FILE, "w") as f:
                f.write("STOP")
            print(f"🛑 Stop signal created at {SIGNAL_FILE}")
            
            # 2. Wait for Graceful Exit
            if active_process:
                print("⏳ [Server] Waiting for GRACEFUL shutdown (Processing pending jobs)...")
                try:
                    # Give it plenty of time (10 min) to finish pending jobs
                    active_process.wait(timeout=600) 
                    print("✅ [Server] Process exited gracefully.")
                except subprocess.TimeoutExpired:
                    print("⏰ [Server] Graceful timeout reached. Forcing termination...")
                    active_process.terminate() 
                    try:
                         active_process.wait(timeout=10)
                    except:
                         active_process.kill()
                    print("💀 [Server] Process killed.")
                
                active_process = None
            else:
                print("ℹ️ No active process to terminate.")

            # 3. Persist "Ready" state to status.json so UI resets on reload
            try:
                status_path = os.path.join(DASHBOARD_DIR, "status.json")
                if os.path.exists(status_path):
                    with open(status_path, "r") as f:
                        data = json.load(f)
                else:
                    data = {}
                
                data["status"] = "Ready"
                
                with open(status_path, "w") as f:
                    json.dump(data, f, indent=2)
                print(f"✅ status.json updated to Ready")
            except Exception as e:
                print(f"⚠️ Error updating status.json: {e}")
            
            # Response
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "stopped"}).encode())

        elif self.path == '/apply':
            # 0. Concurrency Hack
            if active_process and active_process.poll() is None:
                self.send_response(409)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Another process is already running"}).encode())
                return

            try:
                # 1. Update status
                status_path = os.path.join(DASHBOARD_DIR, "status.json")
                if os.path.exists(status_path):
                    with open(status_path, "r") as f:
                        data = json.load(f)
                else:
                    data = {}
                data["status"] = "Running"
                with open(status_path, "w") as f:
                    json.dump(data, f, indent=2)
                
                # 2. Subprocess Launch
                log_path = os.path.join(DASHBOARD_DIR, "apply_debug.log")
                if os.path.exists(SIGNAL_FILE):
                    os.remove(SIGNAL_FILE)
                
                print(f"Server: Launching apply bot...", flush=True)
                
                proc = subprocess.Popen(
                    ["python3", "-m", "src.apply_bot"],
                    cwd=ROOT_DIR,
                    stdout=open(log_path, "w"),
                    stderr=subprocess.STDOUT,
                    env=os.environ.copy()
                )
                active_process = proc

                # 3. Correct Response
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "running"}).encode())

            except Exception as e:
                print(f"Server Error launching bot: {e}", flush=True)
                self.send_error(500, str(e))
        
        elif self.path == '/search':
            if active_process and active_process.poll() is None:
                self.send_response(409)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Another process is already running"}).encode())
                return

            try:
                # 1. Update status
                status_path = os.path.join(DASHBOARD_DIR, "status.json")
                if os.path.exists(status_path):
                    with open(status_path, "r") as f:
                        data = json.load(f)
                else:
                    data = {}
                data["status"] = "Running"
                with open(status_path, "w") as f:
                    json.dump(data, f, indent=2)
                
                # 2. Launch search
                log_path = os.path.join(DASHBOARD_DIR, "apply.log") 
                if os.path.exists(SIGNAL_FILE):
                    os.remove(SIGNAL_FILE)

                print(f"Server: Launching search process (src.main)...", flush=True)
                
                proc = subprocess.Popen(
                    ["python3", "-m", "src.main"],
                    cwd=ROOT_DIR,
                    stdout=open(log_path, "w"),
                    stderr=subprocess.STDOUT,
                    env=os.environ.copy()
                )
                active_process = proc

                # 3. Correct Response
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "running"}).encode())

            except Exception as e:
                print(f"Server Error launching search: {e}", flush=True)
                self.send_error(500, str(e))

        elif self.path == '/api/clear_jobs':
            try:
                # 0. Kill Active Process if Running
                if active_process:
                    print(f"   [Server] Terminating active process {active_process.pid} before cleanup...")
                    try:
                        active_process.terminate()
                        active_process.wait(timeout=5)
                    except:
                        active_process.kill()
                    active_process = None
                
                # Check for other zombie processes just in case
                os.system("pkill -9 -f 'python3 -m src.main' > /dev/null 2>&1")
                
                # 1. Truncate Database
                db.clear_jobs()
                print("   [Server] Database truncated.")

                # 2. Reset status.json (Activity Log)
                status_path = os.path.join(DASHBOARD_DIR, "status.json")
                reset_state = {
                    "total_combinations": 0,
                    "current_combination_index": 0,
                    "current_role": "Ready",
                    "current_location": "-",
                    "jobs_in_current_batch": 0,
                    "current_job_index": 0,
                    "total_matches": 0,
                    "recent_matches": [],
                    "logs": [],
                    "status": "Ready",
                    "last_updated": 0
                }
                with open(status_path, "w") as f:
                    json.dump(reset_state, f, indent=2)
                print("   [Server] status.json reset.")

                # 3. Wipe Log Files
                # Identify root dir (parent of dashboard)
                # 3. Wipe Log Files
                # Identify root dir (parent of dashboard)
                # Logs in Root
                root_logs = ["activity.log", "app.log", "processor.log"]
                for log_file in root_logs:
                    full_path = os.path.join(ROOT_DIR, log_file)
                    if os.path.exists(full_path):
                        try:
                            with open(full_path, "w") as f: f.write("") # Truncate
                            print(f"   [Server] Wiped {log_file}")
                        except Exception as e:
                            print(f"   [Server] Failed to wipe {log_file}: {e}")

                # Logs in Dashboard
                dash_logs = ["processor_debug.log", "apply.log", "apply_debug.log", "audit.csv"]
                for log_file in dash_logs:
                    full_path = os.path.join(DASHBOARD_DIR, log_file)
                    if os.path.exists(full_path):
                        try:
                            with open(full_path, "w") as f: f.write("") # Truncate
                            print(f"   [Server] Wiped dashboard/{log_file}")
                        except Exception as e:
                            print(f"   [Server] Failed to wipe dashboard/{log_file}: {e}")

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "message": "System fully reset"}).encode())
            except Exception as e:
                print(f"Error clearing system: {e}")
                self.send_error(500)

        elif self.path == '/submit_answer':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data.decode())
                user_answer = payload.get("answer")
                
                if user_answer:
                    # Update interaction.json
                    data = {
                        "status": "answered",
                        "answer": user_answer
                    }
                    with open(INTERACTION_FILE, "w") as f:
                        json.dump(data, f)
                    print(f"   ✅ Received user answer: {user_answer}")
                    
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok"}).encode())
                else:
                    self.send_error(400, "Missing answer")
            except Exception as e:
                print(f"Error handling submit_answer: {e}")
                self.send_error(500)

        elif self.path == '/cancel_interaction':
             # Allow user to skip asking
             data = {"status": "skipped", "answer": ""}
             with open(INTERACTION_FILE, "w") as f:
                json.dump(data, f)
             self.send_response(200)
             self.send_header("Content-type", "application/json")
             self.end_headers()
             self.wfile.write(json.dumps({"status": "skipped"}).encode())

        else:
            self.send_error(404)

# Initialize DB on startup to prevent 500 errors if file is missing
try:
    db.init_db()
except Exception as e:
    print(f"⚠️ Initial DB sync error: {e}")

print(f"Starting Dashboard Server at http://localhost:{PORT}")
print("Use Ctrl+C to stop server.")

# Ensure we are serving from the dashboard directory or current?
# The user usually runs this from 'dashboard' dir or we create it here.
# Let's assume we run it from the 'dashboard' directory context.

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

with ReusableTCPServer(("", PORT), DashboardHandler) as httpd:
    httpd.serve_forever()
