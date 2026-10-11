import sys
sys.path.insert(0, 'C:/Users/Nguyen Cong Thong/Desktop/AI attendance')

from scripts.phase33_live_health_failover import Phase33Acceptance

a = Phase33Acceptance()
r = a.run_all_checks()
print('VERDICT:', r['verdict'])