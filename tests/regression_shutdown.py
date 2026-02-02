import os
import sys
import time
import subprocess
import sqlite3

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config.settings import Settings

def run_graceful_shutdown_test():
    """
    REGRESSION TEST: Graceful Shutdown Coordination
    Ensures that no jobs are left in 'Processing' state after a stop signal.
    """
    db_path = Settings.DB_PATH
    stop_signal = Settings.STOP_SIGNAL
    
    print("🚀 [REGRESSION] Starting Graceful Shutdown Test...")
    
    # 1. Setup: Clean up and Insert 3 fresh jobs
    if os.path.exists(stop_signal): os.remove(stop_signal)
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("DELETE FROM jobs WHERE company='SHUTDOWN_REGRESSION';")
    for i in range(3):
        c.execute("""
            INSERT INTO jobs (company, role, location, status, requirements, url, created_at, updated_at) 
            VALUES ('SHUTDOWN_REGRESSION', 'Test Role', 'Remote', 'Pending', 'Test Requirements', ?, datetime('now'), datetime('now'))
        """, (f"http://test_reg_{i}",))
    conn.commit()
    conn.close()
    
    # 2. Start Bot
    print("🤖 Launching bot...")
    proc = subprocess.Popen(["python3", "-m", "src.main"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 3. Wait for workers to pick up jobs (Approx 15s)
    print("⏳ Waiting for workers to start processing...")
    time.sleep(15)
    
    # Verify they are 'Processing'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM jobs WHERE status='Processing' AND company='SHUTDOWN_REGRESSION';")
    processing_count = c.fetchone()[0]
    conn.close()
    
    if processing_count == 0:
        print("⚠️ Warning: No jobs were picked up in time. Test might be inconclusive.")
    else:
        print(f"✅ Verified: {processing_count} jobs are currently in 'Processing'.")
    
    # 4. Trigger STOP
    print("🛑 Triggering STOP signal...")
    with open(stop_signal, "w") as f: f.write("STOP")
    
    # 5. Wait for graceful exit (Up to 60s)
    print("⏳ Waiting for graceful coordination (Workers -> Boss -> Manager)...")
    try:
        proc.wait(timeout=90)
    except subprocess.TimeoutExpired:
        print("❌ FAILED: Process did not exit within 90s.")
        proc.kill()
        return False
        
    # 6. Final Audit: Verify ZERO orphans
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM jobs WHERE status='Processing';")
    orphans = c.fetchone()[0]
    conn.close()
    
    if orphans == 0:
        print("🎊 SUCCESS: Zero orphaned 'Processing' jobs found.")
        return True
    else:
        print(f"❌ FAILED: {orphans} jobs left in 'Processing' state.")
        return False

if __name__ == "__main__":
    success = run_graceful_shutdown_test()
    if success:
        print("\n✅ GRACEFUL SHUTDOWN LOGIC IS INTACT.")
        exit(0)
    else:
        print("\n🚨 REGRESSION DETECTED: THE SHUTDOWN COORDINATION IS BROKEN.")
        exit(1)
