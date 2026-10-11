@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "REPO_ROOT=C:\Users\Nguyen Cong Thong\Desktop\AI attendance"
python.exe -c "import sys; sys.path.insert(0, r'!REPO_ROOT!'); from scripts.phase33_live_health_failover import Phase33Acceptance; a = Phase33Acceptance(); r = a.run_all_checks(); print('VERDICT:', r['verdict'])"