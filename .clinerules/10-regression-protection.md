# Regression Protection

When modifying code related to a previously completed phase:

- identify relevant previous-phase invariants;
- identify acceptance criteria that could be affected;
- run targeted regression tests;
- verify existing behavior remains intact.

Never sacrifice a previous PASS to obtain a current PASS.

If a new change causes a previous acceptance criterion to fail:

STOP.

Then:
- report the regression;
- identify the affected invariant;
- diagnose the root cause;
- do not conceal or weaken the previous criterion.