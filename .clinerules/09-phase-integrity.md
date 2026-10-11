# Phase Integrity

This repository uses phased development and acceptance criteria.

For every phase:

1. Read the phase objectives and acceptance criteria.
2. Inspect relevant current implementation before editing.
3. Preserve invariants and behavior established by previously passed phases.
4. Do not silently weaken, remove, bypass, or rewrite acceptance criteria.
5. Do not make unrelated refactors merely because they appear desirable.
6. Keep changes within current phase scope unless a dependency is demonstrably required.
7. Verify every applicable acceptance criterion with valid evidence.
8. Run relevant regression tests for previously completed phases.

A phase must NEVER be declared PASS based solely on:
- compilation;
- import success;
- one smoke test;
- command exit code;
- incorrectly constructed verification;
- code inspection.