# Evidence Gate

Never declare PASS without concrete evidence.

For every acceptance criterion, maintain this conceptual mapping:

AC-ID
→ Verification
→ Execution status
→ Evidence
→ Result

Every PASS must have:
- exact verification performed;
- successful execution;
- relevant output/assertions;
- exit status;
- correspondence between verification and acceptance criterion.

If evidence is missing:
- mark the criterion UNVERIFIED.

UNVERIFIED criteria cannot count as PASS.

Do NOT infer PASS from:
- code inspection alone;
- file existence;
- successful import;
- compilation;
- absence of errors;
- previous phase PASS;
- agent reasoning;
- expected behavior.