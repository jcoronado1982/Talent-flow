import os
import signal
import psutil
import time

def kill_process_tree(pid):
    """Kills a process and all its children efficiently."""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try: 
                child.send_signal(signal.SIGKILL)
            except psutil.NoSuchProcess: pass
        try:
            parent.send_signal(signal.SIGKILL)
        except psutil.NoSuchProcess: pass
    except psutil.NoSuchProcess:
        pass

def nuke_zombies():
    """Aggressively kills any lingering TalentFlow related processes."""
    print("🧹 [Cleanup] Scanning for zombies...")
    current_pid = os.getpid()
    
    targets = ["processor_worker", "src.main", "chrome", "playwright"]
    count = 0
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.pid == current_pid: continue
            
            cmd = " ".join(proc.info['cmdline'] or [])
            if any(t in cmd for t in targets) and "dashboard/server.py" not in cmd:
                # Double check it is OUR chrome (headless/guest)
                if "chrome" in cmd and "talentflow" not in cmd and "headless" not in cmd:
                    continue 

                print(f"   💀 Killing zombie: {proc.pid} ({proc.info['name']})")
                kill_process_tree(proc.pid)
                count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
            
    if count > 0:
        print(f"✅ [Cleanup] Eliminated {count} ghost processes.")
        time.sleep(1) # Wait for OS to reclaim
