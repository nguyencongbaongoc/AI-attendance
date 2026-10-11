import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from scripts.phase33_live_health_failover import Phase33Acceptance

a = Phase33Acceptance()
r = a.run_all_checks()
print('VERDICT:', r['verdict'])