---
description: Verify the graceful shutdown coordination and prevent orphaned processes
---

To ensure that the multi-stage shutdown logic (Manager -> Boss -> Worker) is still functional and that no jobs are left in the "Processing" state, follow these steps:

1. Ensure no other bot processes are running.
2. Run the dedicated regression test:
```bash
python3 /home/jcoronado/Desktop/dev/TalentFlow/tests/regression_shutdown.py
```
// turbo
3. If the test returns a non-zero exit code or reports "REGRESSION DETECTED", do NOT commit your changes. Revert any modifications to the following critical files:
   - [manager.py](file:///home/jcoronado/Desktop/dev/TalentFlow/src/app/bots/search/manager.py)
   - [processor.py](file:///home/jcoronado/Desktop/dev/TalentFlow/src/app/bots/search/processor.py)
   - [database.py](file:///home/jcoronado/Desktop/dev/TalentFlow/src/services/storage/database.py)

4. Verify the logs in `dashboard/processor_debug.log` to see the coordination sequence.
