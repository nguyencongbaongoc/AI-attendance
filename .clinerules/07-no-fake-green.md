# No Fake Green

Never modify tests, fixtures, assertions, thresholds, mocks, expected values, acceptance criteria, or verification logic merely to make an implementation pass.

If a test fails after a legitimate implementation change:
- determine whether implementation or test expectation is incorrect;
- only modify the test when it is objectively inconsistent with the intended current contract;
- document why the test modification is valid.

Never:
- weaken an assertion;
- remove an assertion;
- increase tolerance without justification;
- skip a failing test;
- mark a failing test xfail merely to obtain PASS;
- change expected output merely to match incorrect implementation;
- bypass a failing code path;
- suppress relevant errors.