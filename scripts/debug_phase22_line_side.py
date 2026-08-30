import sys
sys.path.insert(0, '.')

from scripts.phase22_in_out_geometry import Phase22Validator

v = Phase22Validator()

print('=== Testing line_side_calculation ===')
try:
    result = v.test_line_side_calculation()
    print(f'Passed: {result.passed}')
    print(f'Message: {result.message}')
    print(f'Details: {result.details}')
except Exception as e:
    import traceback
    traceback.print_exc()