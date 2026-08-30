# Verification Reporting

For every significant verification, report:

- exact command or test invoked;
- whether it actually executed;
- exit status;
- key result;
- failure classification if applicable;
- affected source files, if any;
- whether production code was modified;
- acceptance criterion covered.

Use precise language.

Never say:

"Test failed"

when the actual situation is:

"Verification command was malformed and the test did not execute."

Never say:

"Implementation failed"

until the implementation has actually been exercised by valid verification.