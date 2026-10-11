import sys
sys.path.insert(0, '.')
from scripts.phase36r_long_duration_soak import SoakTestRunner
runner = SoakTestRunner(duration_minutes=0.1, warmup_seconds=1)
results = runner._run_regression_tests()
for k, v in results.items():
    print(f'{k}: passed={v.get("passed")}, exit_code={v.get("exit_code")}')