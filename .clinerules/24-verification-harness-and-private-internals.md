# Verification Harness and Private Internals Safety

## 1. Do Not Use Large Inline Verification

NEVER use a large multiline python -c command for verification.

If a verification requires:
- multiple imports;
- multiple object constructions;
- multiple assertions;
- queue manipulation;
- locks;
- callbacks;
- state inspection;
- more than a few statements;
- complex control flow;

use a proper pytest test or a standalone .py verification script.

Prefer:

python -m pytest tests/unit/test_output.py -q

or:

python scripts/verify_output.py

Do NOT embed the entire verification into:

python -c "..."

## 2. Prefer Existing Tests

Before creating a manual verification command:

1. Search for existing tests covering the behavior.
2. Search for existing fixtures.
3. Search for existing test helpers.
4. Search for existing acceptance scripts.
5. Reuse the existing project-native verification mechanism whenever possible.

Do not duplicate an existing test inside a python -c command.

## 3. Private Internals Are Not Public Contracts

Do NOT use private implementation details as the primary basis for acceptance verification.

Treat names beginning with "_" as private unless the current acceptance criterion explicitly requires testing the private implementation.

Examples:

_subscriber_lock
_subscribers
state.lock
state.queue
events_dropped

Accessing these fields may be useful for targeted white-box diagnostics, but it does NOT by itself prove the public contract.

## 4. Public Behavior Must Be Verified Through Public APIs

When verifying a component, prefer:

- public methods;
- public properties;
- documented return values;
- documented exceptions;
- observable events;
- public counters;
- public state transitions;
- public serialization;
- externally observable behavior.

For a publisher/event bus, prefer verifying:

publish(event)
subscribe(...)
unsubscribe(...)
delivery behavior
backpressure behavior
observable delivery status
public metrics
public API results

Do not make internal queue contents the only evidence that backpressure behavior works.

## 5. White-Box Verification Exception

Private state MAY be inspected when necessary to diagnose or supplement a test.

If private internals are used:

1. Clearly identify the verification as WHITE_BOX.
2. Do not claim that private state inspection alone proves the public contract.
3. Also verify the corresponding externally observable behavior whenever possible.
4. Do not modify production code merely to expose private state for a test unless the current architecture explicitly requires it.

Example:

WHITE_BOX:
state.queue contains event3

is not sufficient by itself to claim:

PUBLIC CONTRACT:
DROP_OLDEST behavior is correct.

The public behavior must also be established.

## 6. Do Not Mutate Internal State Unless Required

NEVER directly mutate private internal state merely to manufacture a test condition when a public API can establish the same condition.

Avoid patterns such as:

state.queue.append(event)
state._queue.append(event)
bus._subscribers["id"] = ...
state.events_dropped = ...

Prefer using the public API to fill queues or trigger state transitions.

Direct mutation of private state can invalidate the behavior being tested.

## 7. Backpressure Testing

When testing queue backpressure:

Do NOT assume that manually appending events to an internal queue is equivalent to publishing events through the public API.

The preferred test sequence is:

1. Configure the subscriber through the public API.
2. Publish events through the public API.
3. Allow the queue to reach capacity through real behavior.
4. Publish the event that should trigger the backpressure policy.
5. Observe the resulting public behavior.
6. Inspect internal state only as supplementary evidence when necessary.

For DROP_OLDEST:

The test must establish that:
- queue capacity is respected;
- the oldest queued event is discarded;
- the newest event is retained;
- the drop counter/metric is updated;
- publish returns the expected result;
- subscriber behavior remains consistent with the contract.

Do not prove DROP_OLDEST solely by manually appending to state.queue.

## 8. Lock Safety

Do NOT manually acquire private locks unless the purpose of the test is specifically to verify synchronization internals.

Avoid:

with bus._subscriber_lock:
    ...

and:

with state.lock:
    ...

when the public API can establish or observe the required condition.

If a lock must be inspected for a concurrency test:

- document why;
- keep the test isolated;
- avoid holding the lock while invoking public methods that may require the same lock;
- ensure the test cannot deadlock.

## 9. No Deadlock-Prone Verification

Never construct a verification that:

1. manually acquires a private lock;
2. calls a public method;
3. expects the public method to acquire the same lock.

Before running concurrency tests:

- inspect lock ownership;
- inspect lock acquisition paths;
- determine whether the lock is reentrant;
- avoid nested acquisition unless explicitly supported.

If uncertain:

STOP.

Inspect the implementation before executing the test.

## 10. Callback Safety

When testing subscriber delivery, do not use a callback that hides behavior unless intentionally testing a no-op subscriber.

Prefer a callback that records observable delivery.

Example:

received = []

def callback(event):
    received.append(event.event_id)

Then verify:

received == [...]

A callback such as:

lambda e: None

may be acceptable for a queue/backpressure setup test, but it is insufficient as the only evidence of successful delivery.

## 11. Event Identity Verification

When testing event queues or backpressure:

Track event IDs explicitly.

Prefer:

event1.event_id
event2.event_id
event3.event_id

and verify the expected ordering.

For DROP_OLDEST with queue size 2:

Before:
[event1, event2]

Publish event3.

Expected queue:
[event2, event3]

Expected dropped event:
event1

Expected dropped count:
previous_count + 1

Do not infer this behavior from a successful return value alone.

## 12. Contract Versus Implementation Verification

Every verification must distinguish:

PUBLIC CONTRACT
from
IMPLEMENTATION DETAIL

Before claiming PASS, ask:

1. What behavior does the acceptance criterion require?
2. What public API exposes that behavior?
3. What observable result proves it?
4. Are private internals being used only as supplementary evidence?
5. Could the implementation change while preserving the contract?

If the test only proves the current implementation structure:

mark it as WHITE_BOX / IMPLEMENTATION DETAIL.

Do not present it as full contract verification.

## 13. Test Harness Must Not Change Production Semantics

A verification harness must not alter production behavior merely to make the test easier.

Do not:
- monkey-patch production logic without explicit justification;
- replace queue implementations;
- replace locks;
- manually modify internal counters;
- inject fake state into private structures;
- bypass public APIs;
- disable validation;
- disable backpressure;
- disable synchronization.

If mocking is required:

- mock only the external dependency being isolated;
- document why the mock is required;
- preserve the behavior under test.

## 14. Existing Acceptance Scripts

If a canonical acceptance script exists:

- inspect it first;
- run it directly;
- do not recreate its logic inside python -c;
- do not create a second competing acceptance mechanism unless required.

If the canonical script is incomplete:

- identify the missing acceptance criterion;
- modify the script only when justified;
- preserve existing verification;
- run the resulting script;
- verify its exit status and output.

## 15. Test Result Integrity

A test must fail when the required behavior is incorrect.

Do not create verification code that merely prints:

[PASS]

without assertions.

Bad:

print("[PASS] DROP_OLDEST works")

Good:

assert queue_ids == ["IEV-test002", "IEV-test003"]
assert events_dropped == previous_dropped + 1
print("[PASS] DROP_OLDEST behavior verified")

The assertion must execute before reporting PASS.

## 16. No Hardcoded PASS

Never generate a verification script that reports PASS independently of actual assertions.

Do NOT do:

result = True
print("[PASS]")

Do NOT do:

status = "PASS"
json.dump({"status": status}, ...)

unless status is derived from actual executed verification results.

PASS must be evidence-derived.

## 17. Verification Script Design

For non-trivial verification, prefer this structure:

SETUP
-> EXECUTE PUBLIC API
-> CAPTURE RESULT
-> ASSERT EXPECTED BEHAVIOR
-> INSPECT SUPPLEMENTARY STATE
-> REPORT RESULT

Avoid:

SETUP
-> MODIFY PRIVATE STATE
-> PRINT INTERNAL STATE
-> CLAIM PASS

## 18. Failure Classification

If the verification fails because:

- the command was malformed;
- quoting was incorrect;
- a Windows path was not quoted;
- python -c parsing failed;
- an import failed;
- a private attribute does not exist;
- a private implementation changed;
- the test harness is incorrect;

DO NOT immediately classify it as ACTUAL_CODE_FAILURE.

Apply the existing failure-triage rules.

Determine whether the intended application behavior was actually exercised.

## 19. Contract Changes

If a public contract changes:

1. update or create a focused pytest test;
2. verify public behavior;
3. update relevant integration tests;
4. inspect affected callers;
5. inspect serialization/deserialization when applicable;
6. run regression tests.

Do not rely on manually inspecting private fields to validate a public contract change.

## 20. Required Verification Priority

Use this priority:

1. Existing targeted pytest.
2. New focused pytest.
3. Existing project-native acceptance script.
4. Existing standalone verification script.
5. Manual white-box diagnostic.
6. python -c only for trivial checks.

Large multiline python -c verification is prohibited.

## 21. Required Default

For complex event-bus, queue, backpressure, concurrency, or state-machine verification:

- use pytest or a dedicated .py script;
- use public APIs as the primary verification path;
- use private internals only as supplementary white-box evidence;
- do not manually mutate private queues or counters unless explicitly testing internal mechanics;
- use assertions;
- derive PASS from actual assertions;
- preserve event ordering;
- verify observable behavior;
- avoid deadlock-prone manual lock acquisition;
- classify harness failures before modifying production code.

## 22. Final Safety Rule

The verification mechanism must not become less reliable than the system being tested.

If a test requires increasingly complex:

- shell quoting;
- multiline python -c;
- private state mutation;
- private lock manipulation;
- hardcoded expected state;
- manual queue manipulation;

STOP.

Replace the verification with a proper pytest test or dedicated verification script before proceeding.