# Source Code Protection

Never change production/source code solely because:

- a shell command was malformed;
- shell quoting was incorrect;
- the wrong working directory was used;
- PYTHONPATH was missing;
- Python code was incorrectly passed to python -c;
- imports were constructed incorrectly;
- the test harness was invalid;
- the verification script never executed;
- the environment was incorrectly configured.

Do not enter a speculative:

fix → run → fail → speculative fix

loop.

Establish the root cause first.