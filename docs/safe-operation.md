# Safe operation of the course workflow

This records the implementation and verified evidence available on 10 November
2026. The accepted Compulsory 2 problem and three-course scope are unchanged.

## Permissions and context

The extraction model receives only the approved source view, extraction prompt,
schema and, on a content repair, the preceding candidate and checker feedback.
No tools, shell, filesystem, browser or delegation interface is supplied to it.
Reference answers and evaluation categories are not extraction input. The
trusted host attaches course metadata and checks the returned facts separately.

The collector restricts requests to the three approved HTTPS course URLs and
robots.txt, with constrained redirects, pacing, timeouts, response sizes and
section/contact filtering. The host invokes fixed collector, checker and
renderer programs. These are model/application boundaries, not an OS sandbox
against an attacker controlling the local Python process.

Compulsory 2 used a non-interactive Codex process and permission profile. The
current normal and actual-evaluation paths share the Responses API controller
so one invocation-owned ledger can enforce the requested budget. The four
collection/extraction/validation/rendering stages remain. Model API requests
have no tool surface and do not inherit the coding assistant's repository access.

## Secrets and public inputs

The live client reads OPENAI_API_KEY at runtime, not credential files. The key
is excluded from model input and collector/checker/renderer subprocess
environments. Diagnostic/audit fields are allowlisted; native provider exception
text is not copied into evidence. Runtime credentials are not repository data.

The fixture contains filtered public course information. Recognized staff,
contact, form, navigation and footer material is excluded. Targeted filtering
does not prove that an arbitrary redesigned page contains no personal data;
live-layout/privacy drift remains a limitation requiring source review.

## Budgets and stopping conditions

Actual runs require explicit positive run-token, output-token and generation-call
limits. Both retained corpus trials declared 200,000 total tokens, 12,000 output
tokens per response and at most 21 generations. These are trial settings, not
universal defaults. Content repair allows at most three attempts per case;
SDK automatic retries are disabled.

A counted input and its output ceiling must fit a durable reservation before
generation is marked dispatched. Count/create input identity is hash-bound.
Raw usage must satisfy exact-type and arithmetic checks before settlement.
Missing or uncertain usage retains the allowance and blocks the shared ledger.
The ledger is neither reset between evaluation cases nor resumed from old files.

| Condition | Stopping mechanism | Evidence |
|---|---|---|
| Unapproved course/source URL | Reject before counting or extraction | S07/S08; Task 017 I02 |
| Three completed content rejections | Stop that case without rendering/publication | Task 017 I04 |
| Insufficient token allowance or no call slot | Refuse the next unaffordable request | Budget regressions; Task 017 S01 call-cap control |
| Generation timeout or missing/invalid usage | Retain uncertain reservation; block later cases in the invocation | Task 017 D01/D02 |
| Missing, modified or unwritable required evidence | Abandon and block the ledger before continuation | Task 014/015 infrastructure/integrity regressions |
| Component interruption | Abandon; normal CLI returns 130 | Controller/CLI regressions |

Content rejection and budget refusal differ from permanent abandonment. Three
rejections stop one case; uncertain dependency usage blocks later cases sharing
the invocation ledger. The call-cap study uses synthetic usage and proves
logical dispatch control, not provider billing. Separate retained live-pilot
evidence establishes one count/usage agreement and a budget refusal. No dollar
spending guarantee is claimed.

## Human approval and publication

Passing candidates may replace the two local normal output files automatically.
The student reviews the comparison before external sharing. The workflow does
not automatically send messages or publish to external services. The two local
file replacements are individually atomic, not one atomic two-file transaction.

Quote membership, date-role, precision and missing-flag checks do not prove
semantic completeness. Admission relationships, qualifications and usefulness
still need source-context review. Student qualitative confirmation and editing
of the final paper remain separate; automated results do not grant approval.

## Verified evidence and limits

Task 016 passed 328 ordinary-WSL tests with zero errors or skips. Task 017 met
all ten declared controls, preserving 10,284 pre-existing entries and Git state.
Its real offline CLI controls used the in-memory SDK double, not new model
generations. See docs/exam/stress-study-2026-11-10.md and the retained raw runs.
Task 018 records acceptance of the newly packaged repository reproduction.
