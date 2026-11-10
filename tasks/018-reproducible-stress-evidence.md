# Task 018: Repository reproduction and verified exam evidence

## Purpose and changes

Make the accepted input/dependency study repeatable from a source-only checkout
without Downloads helpers, ignored historical runs, Git history, new dependencies
or model requests. Preserve the accepted problem, production behavior, frozen
corpus/reference and earlier runs.

Add an offline stress runner/internal driver, three retained candidate fixtures,
a historical checker control and protocol/provenance. The same ten Task 017
controls remain. New tests cover complete reproduction without Git/history,
refusal of altered replay data before dispatch, and an output symlink escaping
the checkout. Existing normal publication must survive.

Add safety, evaluation and stress-study documents and README/SPEC links. Record
semantic limits, the controller's departure from the original Codex-process
extraction, and pending student review. Existing production and evaluation
requests do not read these new stress fixtures.

## Acceptance

The preceding ordinary-WSL checkpoint passed 328 tests. Three new tests make
this task's full acceptance count 331 with zero failures/errors/skips. Corpus,
component replay, standalone stress reproduction, isolated required probe/check
and runner previews must also pass. The review runtime can run 317 tests;
twelve pinned OpenAI SDK and two MCP integration tests require ordinary WSL.

The guarded integration helper backs up its target files, applies only this
scope, verifies pre-existing files/index/tags and restores its matching changes
on failure. Evidence is retained for review and successful work stays
uncommitted. No actual model trial or live collection is part of this task.

## Ordinary-WSL acceptance (2026-11-10)

All three source-only reproduction and write-boundary controls passed.
The full suite passed 331 tests with zero failures, errors or
skips. Corpus/component replay, the standalone ten-control stress study,
isolated probe/checker, runner syntax/previews and whitespace checks passed.

The existing source, historical runs, index and tags were preserved.
Evidence: `out/exam/task-018/integration-20261110T173501Z-dc62052b/`. No installation, live collection,
model request, staging, commit, push or tag change was performed.
