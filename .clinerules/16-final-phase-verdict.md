# Final Phase Verdict

A phase may only be marked PASS when:

- all required acceptance criteria are verified;
- verification commands were valid;
- tests actually executed;
- relevant assertions actually ran;
- evidence exists for every criterion;
- no unresolved infrastructure/test-harness failures are being counted as implementation failures;
- relevant regression tests pass;
- no previous-phase invariant was silently weakened;
- final implementation matches phase scope;
- no acceptance criterion was bypassed or weakened.

If verification is incomplete because of infrastructure, command, environment, or test-harness problems:

mark the result BLOCKED or UNVERIFIED.

Do NOT mark PASS.