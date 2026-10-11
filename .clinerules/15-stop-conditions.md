# Stop Conditions

STOP and diagnose before modifying source code when:

- command is malformed;
- shell quoting is suspicious;
- Python code was incorrectly passed to python -c;
- imports fail unexpectedly;
- test output contradicts the command;
- test did not reach intended code;
- environment appears inconsistent;
- acceptance criteria cannot be verified reliably;
- previous phase appears to regress;
- source-of-truth conflict exists;
- test evidence is incomplete.

When uncertain whether the failure originates from the test mechanism or implementation:

DO NOT GUESS.

Reproduce using:
- pytest;
- a clean temporary Python script;
- or another reliable project-native verification mechanism.

Establish the failure boundary first.