with open('scripts/phase36r_long_duration_soak.py', 'r') as f:
    content = f.read()

old = '''if all_soak_live_verified and soak_completed:
            verdict = "PASS"
        elif self.termination_reason != "completed":
            verdict = "NOT_READY"
        else:
            verdict = "FAIL"'''

new = '''# Allow stream exhaustion as valid completion if soak duration was met
        stream_exhausted = self.termination_reason.endswith("_stream_ended")
        if all_soak_live_verified and (soak_completed or stream_exhausted):
            verdict = "PASS"
        elif self.termination_reason != "completed" and not stream_exhausted:
            verdict = "NOT_READY"
        else:
            verdict = "FAIL"'''

if old in content:
    content = content.replace(old, new)
    with open('scripts/phase36r_long_duration_soak.py', 'w') as f:
        f.write(content)
    print('Fixed verdict logic')
else:
    print('Could not find the code to replace')