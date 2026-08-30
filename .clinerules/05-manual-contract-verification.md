# Manual Contract Verification

Before constructing manual tests for classes, dataclasses, functions, enums, or serialization contracts:

- inspect the current implementation;
- inspect actual constructor/function signatures;
- inspect required fields and defaults;
- inspect enum values;
- inspect serialization methods such as to_dict();
- inspect current imports;
- use the current API rather than guessing.

Prefer explicit imports over:

from module import *

Do not assume that a symbol exists because a previous plan, phase report, or agent memory mentioned it.

For example, before constructing a GlobalObservation test:
- inspect LocalObservationRef;
- inspect AssociationEvidence;
- inspect AssociationState;
- inspect ReplayTimestamp;
- inspect GlobalObservation;
- inspect to_dict();
- then construct the verification from the actual current contracts.