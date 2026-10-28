#!/usr/bin/env python3
"""Collect filtered source sections for the approved automation courses."""

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "courses" / "course-sources.json"
OUTPUT = ROOT / "out" / "training" / "course-sources.json"
ROBOTS_URL = "https://www.fagskolen-innlandet.no/robots.txt"
COURSES = (
    ("automation-introduction", "https://www.fagskolen-innlandet.no/utdanninger/automasjon-for-elektrikere-introduksjon"),
    ("automation-pls", "https://www.fagskolen-innlandet.no/utdanninger/automasjon-for-elektrikere-pls"),
    ("automation-robot-regulation", "https://www.fagskolen-innlandet.no/utdanninger/automasjon-for-elektrikere-robot-og-regulering"),
)
USER_AGENT = "kiua2003-agentic-workflow/0.1 (https://github.com/Barzan-star/kiua2003-agentic-workflow)"
TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 2_000_000
REQUEST_INTERVAL_SECONDS = 1.0
EXCLUDED_TAGS = {"nav", "script", "style", "form", "footer", "button", "svg", "noscript"}
EXCLUDED_WORDS = re.compile(r"(?:^|[-_ ])(?:nav|menu|footer|contact|kontakt|staff|person|employee|credit|photo|image|newsletter|subscribe|form)(?:$|[-_ ])", re.I)
CONTACT_TERMS = re.compile(r"kontakt|contact|ansatte|staff|personer|people|sporsmal om soknad", re.I)
ALLOWED_SECTION_LABELS = {
    "course overview",
    "gjennomforinger du kan soke pa na",
    "nettbasert med samlinger",
    "kommende gjennomforinger",
    "hva laerer du",
    "gjennomforing",
    "hvilken nytteverdi vil du oppna",
    "nyttig a vite",
    "opptakskrav",
    "godkjente fagbrev",
    "samlingsdatoer",
    "fysiske samlinger",
    "teamssamlinger",
    "teams samlinger",
}
ALLOWED_URLS = {ROBOTS_URL, *(url for _, url in COURSES)}


class RestrictedRedirectHandler(HTTPRedirectHandler):
    """Allow redirects only when the destination is one of the approved URLs."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        destination = urljoin(request.full_url, new_url)
        parsed = urlparse(destination)
        if parsed.scheme != "https" or destination not in ALLOWED_URLS:
            raise RuntimeError(f"rejected redirect to unapproved URL: {destination}")
        return super().redirect_request(request, response, code, message, headers, new_url)


def _default_open(request, timeout):
    return build_opener(RestrictedRedirectHandler()).open(request, timeout=timeout)


def _clean(text):
    return re.sub(r"\s+", " ", text).strip()


def _normalise_label(text):
    """Normalise whitespace, case, accents, and punctuation in a heading."""
    value = _clean(text).casefold().translate(str.maketrans("æøå", "eoa"))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _is_contact_heading(text):
    label = _normalise_label(text)
    if CONTACT_TERMS.search(label):
        return True
    words = set(label.split())
    return "sporsmal" in words and bool(words.intersection({"soknad", "dokumentasjon", "regelverk", "opptak"}))


def _allowed_section(label):
    normalised = _normalise_label(label)
    return normalised in ALLOWED_SECTION_LABELS or normalised.startswith("studieavgift ")


class CourseHTMLParser(HTMLParser):
    """Retain visible text in main content, grouped under page headings."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.main_depth = None
        self.blocks = []
        self.current = []
        self.current_kind = "paragraph"
        self.current_level = 0
        self.contact_depth = None
        self.title = ""
        self.in_title = False
        self.heading_context_excluded = False

    def _flush(self):
        value = _clean(" ".join(self.current))
        if value:
            if self.current_kind == "heading":
                if self.contact_depth is not None and self.current_level <= self.contact_depth:
                    self.contact_depth = None
                if _is_contact_heading(value):
                    self.contact_depth = self.current_level
                self.heading_context_excluded = self.contact_depth is not None
                if not self.heading_context_excluded:
                    self.blocks.append(("heading", value))
            elif not self.heading_context_excluded and not re.search(r"(?:@|\b\+?\d[\d ()/-]{7,}\b|\bFoto\s*:)", value, re.I):
                self.blocks.append((self.current_kind, value))
        self.current = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        ident = attrs.get("id", "")
        excluded = tag in EXCLUDED_TAGS or bool(EXCLUDED_WORDS.search(classes)) or bool(EXCLUDED_WORDS.search(ident))
        self.stack.append((tag, excluded))
        if tag == "main" and not excluded:
            self.main_depth = len(self.stack)
        if tag == "title":
            self.in_title = True
        if self.main_depth is None or any(item[1] for item in self.stack):
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "tr"}:
            self._flush()
            self.current_kind = "heading" if tag.startswith("h") else "list_item" if tag == "li" else "paragraph"
            self.current_level = int(tag[1]) if tag.startswith("h") else 0

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if self.main_depth is not None and len(self.stack) >= self.main_depth and not any(item[1] for item in self.stack):
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "tr"}:
                self._flush()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if self.main_depth is not None and len(self.stack) < self.main_depth:
            self.main_depth = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.main_depth is not None and not any(item[1] for item in self.stack):
            self.current.append(data)


def extract_course(html, course_id, url, retrieved_at):
    parser = CourseHTMLParser()
    parser.feed(html)
    parser.close()
    parser._flush()
    blocks = parser.blocks
    title = next((value for kind, value in blocks if kind == "heading"), "")
    if not title or not title.lower().startswith("automasjon for elektrikere"):
        raise ValueError(f"unexpected course page at {url}: expected course title in main content")
    expected_title = {
        "automation-introduction": "introduksjon",
        "automation-pls": "pls",
        "automation-robot-regulation": "robot og regulering",
    }.get(course_id)
    if expected_title is None or expected_title not in title.casefold():
        raise ValueError(f"unexpected course page at {url}: title does not match {course_id}")
    sections = []
    label = "Course overview"
    content = []

    def keep_section(section_label, section_content):
        if _allowed_section(section_label) and section_content:
            sections.append({"label": section_label, "text": "\n".join(section_content)})

    for kind, value in blocks:
        if kind == "heading":
            if value == title:
                continue
            keep_section(label, content)
            content = []
            label = value
        else:
            content.append(value)
    keep_section(label, content)
    if not sections or not any(section["text"].strip() for section in sections):
        raise ValueError(f"unusable course extraction at {url}: no course sections found")
    if len(" ".join(s["text"] for s in sections)) < 30:
        raise ValueError(f"unusable course extraction at {url}: insufficient relevant source text")
    return {
        "course_id": course_id,
        "source_url": url,
        "retrieved_at": retrieved_at,
        "title": title,
        "source_sections": sections,
        "source_text_is_untrusted_data": True,
    }


def _read_response(url, *, previous_request=None, opener=_default_open):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"})
    if previous_request is not None:
        delay = REQUEST_INTERVAL_SECONDS - (time.monotonic() - previous_request)
        if delay > 0:
            time.sleep(delay)
    try:
        response = opener(request, timeout=TIMEOUT_SECONDS)
    except (HTTPError, URLError, OSError) as error:
        raise RuntimeError(f"request failed for {url}: {error}") from error
    with response:
        final_url = response.geturl() if hasattr(response, "geturl") else url
        if final_url != url:
            raise RuntimeError(f"unexpected final URL for {url}: {final_url}")
        status = response.getcode()
        if status != 200:
            raise RuntimeError(f"request failed for {url}: unexpected HTTP status {status}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise RuntimeError(f"response exceeded {MAX_RESPONSE_BYTES} bytes: {url}")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError(f"response was not UTF-8: {url}") from error


def collect(opener=_default_open, clock=lambda: datetime.now(timezone.utc)):
    robots_text = _read_response(ROBOTS_URL, opener=opener)
    robot = RobotFileParser(ROBOTS_URL)
    robot.parse(robots_text.splitlines())
    collected = []
    last_request = time.monotonic()
    for course_id, url in COURSES:
        if not robot.can_fetch(USER_AGENT, url):
            raise RuntimeError(f"robots.txt disallows collection: {url}")
        html = _read_response(url, previous_request=last_request, opener=opener)
        last_request = time.monotonic()
        collected.append(extract_course(html, course_id, url, clock().isoformat()))
    return {"schema_version": 1, "courses": collected}


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _create_fixture_once(data):
    """Keep the first successful sanitised capture as the offline snapshot."""
    if FIXTURE.exists():
        return
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FIXTURE.open("x", encoding="utf-8") as fixture:
            fixture.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError:
        pass


def _valid_bundle(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return False
    courses = data.get("courses")
    if not isinstance(courses, list) or len(courses) != len(COURSES):
        return False
    for item, (course_id, url) in zip(courses, COURSES):
        if not isinstance(item, dict) or item.get("course_id") != course_id or item.get("source_url") != url:
            return False
        if not isinstance(item.get("retrieved_at"), str) or not item.get("title"):
            return False
        sections = item.get("source_sections")
        if not isinstance(sections, list) or not sections or not all(
            isinstance(section, dict) and isinstance(section.get("label"), str)
            and isinstance(section.get("text"), str)
            and _allowed_section(section["label"])
            and not _is_contact_heading(section["label"])
            for section in sections
        ):
            return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="read the saved course-only fixture")
    args = parser.parse_args(argv)
    try:
        if args.offline:
            data = json.loads(FIXTURE.read_text(encoding="utf-8"))
            if not _valid_bundle(data):
                raise ValueError("offline course fixture is missing or malformed")
        else:
            data = collect()
            if not _valid_bundle(data):
                raise ValueError("collection produced an invalid course source bundle")
            _create_fixture_once(data)
        # Only report metadata and counts. Source text may contain hostile or
        # misleading text and is never emitted to stdout as instructions.
        _atomic_write(OUTPUT, data)
        print(f"Saved {len(data['courses'])} course sources to {OUTPUT}")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"Course source collection failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
