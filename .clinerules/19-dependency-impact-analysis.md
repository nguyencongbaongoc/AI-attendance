# Dependency Impact Analysis

Before changing a public contract, dataclass, enum, serialization format, interface, or shared utility:

1. Find all callers/usages.
2. Find all constructors/instantiations.
3. Find all serializers/deserializers.
4. Find all tests and fixtures.
5. Identify previous-phase consumers.
6. Determine the minimum regression surface.

Do not assume that changing one file means only that file is affected.

For contract changes, verify both:
- producer behavior;
- consumer behavior.

For serialization changes, verify:
- creation;
- serialization;
- deserialization/reading;
- compatibility where applicable.