# Task 007: Repository-local task planning skill

## Goal
Create the repository-local `task-plan` skill for W43. When explicitly invoked
with a three-digit task identifier, it finds and reads the matching task file
and prepares a concise, read-only implementation plan.

## Requirements
- Accept only an explicit three-digit identifier and locate its matching
  `tasks/NNN-*.md` file. Report missing, malformed, absent, or ambiguous
  identifiers without guessing.
- Read the task and only project files needed to understand it.
- Report the task goal, current implementation state, proposed steps, affected
  files, and exact acceptance commands. Mark acceptance commands `NOT RUN`.
- Plan only: no edits, acceptance command execution, network calls, model
  subprocesses, delegation, staging, commits, or pushes. Ordinary read-only
  file and Git inspection is allowed.
- Set `allow_implicit_invocation: false` in the skill UI metadata.
- Document explicit `$task-plan 005` invocation in `README.md`.

## Acceptance
- The skill validates with the skill-creator `quick_validate.py` tool.
- A fresh-context invocation for task 005 produces a plan and leaves the
  worktree unchanged.
- `git diff --check` succeeds.
