# Change Boundary

Before editing:

- identify files expected to change;
- identify why each file needs modification;
- identify which acceptance criterion requires the change.

Do not modify unrelated files.

If an unexpected file must be changed:
- explain why it is required;
- verify that the change does not violate previous-phase invariants.

Avoid opportunistic refactoring during a phase.

Do not mix unrelated:
- bug fixes;
- architecture refactors;
- cleanup;
- formatting;
- dependency upgrades;
- feature work

into the current phase unless explicitly required.