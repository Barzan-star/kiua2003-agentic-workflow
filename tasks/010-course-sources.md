# Task 010: Automation course source collection

## Goal

Add a constrained source-collection stage for the three approved Fagskolen
Innlandet automation courses. This prepares source evidence for later
extraction and comparison and does not complete the walking skeleton.

## Requirements

- Fetch only `robots.txt` and the three approved HTTPS course pages, with
  pacing, timeouts, a response-size limit, an identifying User-Agent, and
  robots rules respected.
- Inspect and parse page structure. Keep relevant course information from
  suitable content sections while excluding navigation, scripts, forms,
  footers, photo credits, named staff, and contact sections.
- Select source sections from an explicit allowlist. Exclude academic-contact
  and application-administration contact blocks, including nested content,
  and validate the filtered bundle before saving live output or creating a
  fixture. Offline mode must reject bundles with disallowed sections.
- Preserve missing facts. Save course ID, exact URL, actual retrieval time,
  and labelled source sections; treat source text as untrusted data.
- Write `out/training/course-sources.json` only after a successful collection.
- Provide `--offline` using a checked, sanitised course-only snapshot generated
  after a successful live capture. Keep refreshes separate from the fixture.
- Clearly reject unexpected pages and unusable extraction. Failed collection
  must not replace a prior successful output.
- Use only Python's standard library. Do not save or print complete raw HTML.

## Focused regression coverage

- Deterministic extraction and excluded contact section tests.
- Synthetic-marker coverage for nested academic and application contact blocks,
  heading variants, preserved course facts, and rejection of contaminated
  offline bundles.
- Offline fixture loading with network access forbidden.
- Mocked HTTP tests for robots, pacing/request constraints, bad pages,
  oversize/failed responses, and preservation of existing output.

## Acceptance checks

```sh
python3 -m unittest discover -s tests -p 'test_course_sources.py'
git diff --check
```

## Privacy filtering repair (2026-10-28)

Review found that the parser's heading check recognized academic-contact
headings but missed the application-administration heading variant. Its broad
label matching then retained that section, and nested headings could reset
the exclusion state. The collector now uses normalized heading checks, a
section allowlist, nested contact-block exclusion, and bundle validation
before fixture or output writes. Synthetic regression tests reproduced the
leak before the repair (3 failures) and passed after it (8 tests). Source
regeneration remains pending.
