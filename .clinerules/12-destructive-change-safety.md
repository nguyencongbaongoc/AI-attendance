# Destructive Change Safety

Before deleting, replacing, renaming, or substantially restructuring existing code:

1. Inspect current references/usages.
2. Identify dependencies and callers.
3. Identify affected tests.
4. Determine whether the code belongs to a previously passed phase.
5. Preserve behavior unless the current phase explicitly changes it.

Never delete legacy/duplicate code solely because it appears unused without verifying:
- references;
- runtime paths;
- configuration;
- tests.

Never remove:
- invariants;
- validation;
- recovery mechanisms;
- safety checks;
- regression tests;
- fallback behavior

solely because they make the implementation more complex.