# Input and dependency stress study

These are the two perturbation classes selected in the accepted Compulsory 2
report. The ordinary-WSL Task 017 study met ten declared expectations,
preserved 10,284 pre-existing entries and Git state, and made zero live provider
requests. Its ZIP SHA256 is
`4a944f571092ac306b2a5e44d0d90d7b6044abeb8020f9ca6d0173df285e04d6`.

The real saved-fixture collector, controller, checker and renderer ran in a
copy. The provider was the existing SDKDouble, replaying retained candidate
JSON with synthetic usage. The protocol preceded execution.

## Reproduction

```sh
python3 harness/stress_courses.py --offline
```

This standard-library repository command needs no API key, SDK installation,
Git history or historical out/ directory. It regenerates declared source
variants, verifies retained candidates and the historical checker, and runs in
a fresh ignored out/course-stress/ directory. It retains traces, ledgers,
native artifacts and hashes while preserving normal publication.

The historical checker is frozen experiment data at
fixtures/courses/stress/compulsory2-checker.py.txt, from the immutable
compulsory2-skeleton commit 11e057ecd28387674b64bca96f3687bd1ca15643. Its hash is
fixed by the runner. It serves the historical negative control; normal runs
continue to use eval/check_courses.py.

| Case | Intervention | Observed outcome |
|---|---|---|
| N00 | Real offline CLI with a retained correct candidate | Exit 0; local-copy publication |
| I01 | Identical repeated offering row | Accepted; no distinct offering inferred |
| I02 | S08 unapproved source URL | Rejected before counting/generation |
| I03 | S05 conflicting offerings and bad row selection; historical checker | Bad selection accepted and rendered: failure reproduced |
| I04 | Same source and first candidate; current checker | Three rejections; no rendering |
| I05 | Same source; retained abstaining candidate | Accepted; metadata restored |
| D01 | Generation timeout after reservation | Uncertain allowance retained; ledger blocks later dispatch |
| D02 | Complete-looking response without usage | Same containment; no later dispatch |
| D03 | CLI timeout after a successful publication control | Exit 7; prior JSON/Markdown unchanged |
| S01 | One call slot, then a later case | First accepted; later refused before counting |

Ten expectations met does not mean ten successful production runs. I03 is an
intentionally reproduced failure; rejection or abandonment is required in
several other rows.

## Failure propagation and repair

I03 supplies conflicting offerings without a selected row. The retained candidate
chooses one row's dates. The historical checker verifies quotation membership
without enforcing the offering role, allowing rendering with unsupported precision.

I04 changes only that checker component. Source bytes, first raw response and
first assembled candidate have identical before/after hashes. The current
date-role guard rejects both ambiguous date fields, and bounded attempts expire
before rendering. I05 accepts supported unknown dates on the same source.
This verifies an existing repair; it does not measure improved model behavior.

D01/D02 fail after count and reservation. Missing trustworthy usage prevents
settlement, and the adapter blocks the invocation ledger. A later case sharing
it cannot count or generate. These faults are absorbed by existing containment,
not newly discovered failures or repairs. D03 exercises the normal CLI's
publication boundary. S01 makes the call-limit stopping condition observable.

## Provenance and limits

The candidates are Task 015's S00 final record and baseline S05 attempts 3
(bad selection) and 2 (abstention). Their paths/hashes are in the stress protocol.
They remain unchanged replay data. Existing source/catalog/reference files
remain frozen.

Only the checker is historical in I03; the complete old runtime is not rerun.
No current model inference, live outage, live collection, unseen-course accuracy
or general prompt-injection resistance is measured. The original 144/147 result
is unchanged. Student qualitative confirmation and final paper editing remain
separate responsibilities.
