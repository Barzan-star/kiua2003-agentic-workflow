---
name: task-plan
description: Produce a read-only implementation plan for an explicitly identified repository task file.
---

# Task plan

Use this skill only when explicitly invoked with a three-digit task identifier, for example `$task-plan 005`.

1. Require exactly one three-digit identifier. Find matching files with `tasks/NNN-*.md`; if the identifier is missing, malformed, or has zero or multiple matches, report that and stop without guessing.
2. Read the matched task file and only the project files needed to understand its goal and current implementation. Ordinary read-only file and Git inspection is allowed.
3. Report the task goal, current implementation state, proposed steps, affected files, and exact acceptance commands. Label every acceptance command **NOT RUN**.

Produce a plan only. Do not edit files, execute acceptance commands, make network calls, start model subprocesses, delegate, stage, commit, or push. Keep the plan concise and distinguish observed implementation state from assumptions.
