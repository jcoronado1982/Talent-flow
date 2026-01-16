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
SIGNAL_FILE = os.path.join(DASHBOARD_DIR, "stop.signal")

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
            
        return super().do_GET()

    def do_POST(self):
        global active_process
        
        if self.path == '/stop':
            # 1. Create stop signal (Soft Stop)
            with open(SIGNAL_FILE, "w") as f:
                f.write("STOP")
            print(f"🛑 Stop signal created at {SIGNAL_FILE}")
            
            # 2. Wait for Graceful Exit (Allow bot to save FINAL report)
            if active_process:
                print("⏳ Waiting for process to exit gracefully...")
                try:
                    active_process.wait(timeout=30) # Give it 30s (LinkedIn is slow)
                    print("✅ Process exited gracefully.")
                except subprocess.TimeoutExpired:
                    print("⏰ Process stuck. Forcing termination...")
                    active_process.terminate() # SIGTERM
                    try:
                         active_process.wait(timeout=5)
                    except:
                         active_process.kill() # SIGKILL
                    print("💀 Process killed.")
                
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
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}).encode())
            
            # Update status to Running IMMEDIATELY to prevent UI flicker
            try:
                status_path = os.path.join(DASHBOARD_DIR, "status.json")
                if os.path.exists(status_path):
                    with open(status_path, "r") as f:
                        data = json.load(f)
                else:
                    data = {}
                data["status"] = "Running"
                with open(status_path, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                print(f"⚠️ Error updating status.json on start: {e}")

            # Robust Subprocess Launch
            try:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                script_path = os.path.join(base_dir, "src", "apply_bot.py")
                log_path = os.path.join(base_dir, "dashboard", "apply.log")
                
                print(f"Server: Launching {script_path}...", flush=True)
                
                # Pass full environment (DISPLAY, PATH, etc.)
                env = os.environ.copy()
                
                # Launch independent apply bot? Or track it too? 
                # User specifically asked for SEARCH process stop, but good to track apply too?
                # For now let's just track the one we launch.
                proc = subprocess.Popen(
                    ["python3", script_path],
                    cwd=base_dir, # Run from root
                    stdout=open(log_path, "w"),
                    stderr=subprocess.STDOUT,
                    env=env
                )
                active_process = proc # Track it

            except Exception as e:
                print(f"Server Error launching bot: {e}", flush=True)
                # We already sent 200 OK, just log error
        
        elif self.path == '/search':
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}).encode())
            
            # Update status to Running IMMEDIATELY to prevent UI flicker
            try:
                status_path = os.path.join(DASHBOARD_DIR, "status.json")
                if os.path.exists(status_path):
                    with open(status_path, "r") as f:
                        data = json.load(f)
                else:
                    data = {}
                data["status"] = "Running"
                with open(status_path, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                print(f"⚠️ Error updating status.json on start: {e}")
            
            # Robust Subprocess Launch for Search
            try:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                log_path = os.path.join(base_dir, "dashboard", "apply.log") 
                
                print(f"Server: Launching src.main module for SEARCH...", flush=True)
                
                env = os.environ.copy()
                
                proc = subprocess.Popen(
                    ["python3", "-m", "src.main"],
                    cwd=base_dir, # Run from root
                    stdout=open(log_path, "w"),
                    stderr=subprocess.STDOUT,
                    env=env
                )
                active_process = proc # Track it

            except Exception as e:
                print(f"Server Error launching search: {e}", flush=True)
        else:
            self.send_error(404)

print(f"Starting Dashboard Server at http://localhost:{PORT}")
print("Use Ctrl+C to stop server.")

# Ensure we are serving from the dashboard directory or current?
# The user usually runs this from 'dashboard' dir or we create it here.
# Let's assume we run it from the 'dashboard' directory context.

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

with ReusableTCPServer(("", PORT), DashboardHandler) as httpd:
    httpd.serve_forever()
