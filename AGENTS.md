# Project instructions

Group 2 individual course project

Run these check commands from the repository root:

```sh
python3 harness/probe.py --offline && python3 eval/check_probe.py
python3 -m unittest discover -s tests
git diff --check
```

- Ask before editing anything in `eval/`.
- Never use personal data.

MET API and fixture details: use the met-api skill in .agents/skills/met-api/SKILL.md.
