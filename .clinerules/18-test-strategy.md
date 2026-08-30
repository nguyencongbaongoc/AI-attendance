# Test Strategy

Choose the smallest reliable verification that directly proves the changed behavior.

Priority:

1. Existing targeted pytest test.
2. Existing relevant regression test.
3. New focused pytest test when coverage is missing.
4. Project-native integration test.
5. Manual smoke test.
6. Temporary Python script only when no suitable test mechanism exists.
7. python -c only for genuinely trivial checks.

Do not replace a reliable pytest test with an ad-hoc python -c command.

Do not run the entire test suite when a targeted test can reliably establish the result, unless:
- the phase acceptance criteria require full-suite verification;
- the change has broad cross-module impact;
- regression verification requires it.

After targeted tests pass, determine whether broader regression testing is required based on the dependency surface of the change.