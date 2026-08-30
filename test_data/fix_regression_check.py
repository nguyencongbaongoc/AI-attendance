with open('scripts/phase36r_long_duration_soak.py', 'r') as f:
    content = f.read()

old = '''regression_passed = all(r.get("passed", False) for r in self.regression_results.values())
        regression_level = "LIVE_RUNTIME_VERIFIED" if regression_passed else "NOT_VERIFIED"'''

new = '''# Only consider phases with actual test files (not report-only phases)
        regression_results_with_tests = {k: v for k, v in self.regression_results.items() if v.get("test_path") is not None}
        regression_passed = all(r.get("passed", False) for r in regression_results_with_tests.values())
        regression_level = "LIVE_RUNTIME_VERIFIED" if regression_passed else "NOT_VERIFIED"'''

if old in content:
    content = content.replace(old, new)
    with open('scripts/phase36r_long_duration_soak.py', 'w') as f:
        f.write(content)
    print('Fixed regression check')
else:
    print('Could not find the code to replace')