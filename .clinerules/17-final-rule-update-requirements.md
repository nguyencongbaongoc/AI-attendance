# Final Rule-Update Requirements

After creating/updating the Cline rules:

1. Show the exact rule file path(s) created or modified.
2. Summarize the major protections added.
3. Confirm the rules cover:
   - malformed command prevention;
   - failure triage;
   - source-of-truth priority;
   - evidence-gated PASS;
   - no fake green;
   - regression protection;
   - phase integrity;
   - change boundaries;
   - destructive-change safety;
   - forensic root-cause analysis.
4. Confirm that no production/source files were modified.
5. Confirm that the rules were placed in the repository's actual Cline rules mechanism.
6. Do not perform unrelated project changes.
7. Do not claim any phase PASS/FAIL as part of this rule update.
8. Do not modify application behavior.
9. Do not modify acceptance criteria.
10. Do not create speculative fixes.