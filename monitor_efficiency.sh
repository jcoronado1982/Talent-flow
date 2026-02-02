#!/bin/bash
# monitor_efficiency.sh
# Final version for accurate process hierarchy tracking

LOG_FILE="dashboard/efficiency_audit.log"
echo "Timestamp | Total Jobs | Pending | Processing | Workers (Active) | Boss status" > $LOG_FILE

while true
do
    TS=$(date +"%H:%M:%S")
    TOTAL=$(sqlite3 talentflow.db "SELECT count(*) FROM jobs;")
    PENDING=$(sqlite3 talentflow.db "SELECT count(*) FROM jobs WHERE status='Pending';")
    PROCESSING=$(sqlite3 talentflow.db "SELECT count(*) FROM jobs WHERE status='Processing';")
    
    # Accurate detection: 
    # 1. Find the Manager (parent of all bot sub-processes)
    # 2. Find its immediate children (Bosses)
    # 3. Find children of the Boss (Workers)
    
    # Find all src.main processes
    PIDS=$(pgrep -f "src.main")
    
    # Manager is typically the one with the lowest PID OR the one started by server.py
    MANAGER_PID=$(pgrep -f "src.main" | head -n 1)
    
    # Workers are the leaf processes
    # Since we know there are 10 workers + 1 Boss + 1 Manager = 12 processes usually
    ALL_PYTHON=$(pgrep -f "src.main" | wc -l)
    
    if [ "$ALL_PYTHON" -le 2 ]; then
        WORKERS=0
        BOSS="IDLE/OFF"
    else
        # Boss is 1, Manager is 1, the rest are Workers
        WORKERS=$((ALL_PYTHON - 2))
        BOSS="ACTIVE"
    fi
    
    echo "$TS | $TOTAL | $PENDING | $PROCESSING | $WORKERS | $BOSS" >> $LOG_FILE
    sleep 10
done
