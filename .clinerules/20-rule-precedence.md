# Rule Precedence

When rules appear to conflict, apply the following priority:

1. Explicit user instruction.
2. Current phase acceptance criteria.
3. Safety and verification integrity rules.
4. Current source-of-truth repository state.
5. Regression protection and previous-phase invariants.
6. Scope/change-boundary rules.
7. Historical documentation and reports.

Never resolve a conflict by silently ignoring one rule.

If two rules genuinely conflict:
- STOP;
- identify the conflict;
- explain which rules conflict;
- preserve the stricter safety/verification requirement;
- ask for clarification when necessary.

No rule may authorize:
- weakening an acceptance criterion;
- hiding a regression;
- modifying tests to obtain PASS;
- bypassing verification;
- changing production code because of an invalid test command.