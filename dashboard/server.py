import http.server
import socketserver
import os
import json

PORT = 8000
SIGNAL_FILE = os.path.abspath("stop.signal")

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/stop':
            # Create stop signal
            with open(SIGNAL_FILE, "w") as f:
                f.write("STOP")
            print(f"🛑 Stop signal created at {SIGNAL_FILE}")
            
            # Response
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "stopping"}).encode())
        else:
            self.send_error(404)

print(f"Starting Dashboard Server at http://localhost:{PORT}")
print("Use Ctrl+C to stop server.")

# Ensure we are serving from the dashboard directory or current?
# The user usually runs this from 'dashboard' dir or we create it here.
# Let's assume we run it from the 'dashboard' directory context.

with socketserver.TCPServer(("", PORT), DashboardHandler) as httpd:
    httpd.serve_forever()
