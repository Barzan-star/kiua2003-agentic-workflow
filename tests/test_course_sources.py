import json
from email.message import Message
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import course_sources as source


HTML = """<!doctype html><html><head><title>Automasjon for elektrikere – Introduksjon</title></head>
<body><nav><h1>Site menu</h1><p>Navigation leak</p></nav><main>
<h1>Automasjon for elektrikere – Introduksjon</h1>
<p>Modul for elektrikere med automasjonskompetanse.</p>
<form><h2>Hold meg oppdatert</h2><p>Newsletter email</p></form>
<div class="application"><h2>Gjennomføringer du kan søke på nå</h2>
<h3>Nettbasert med samlinger</h3><p>Søknadsfrist</p><p>3. januar 2027</p>
<p>Oppstartsdato 9. februar 2027</p><p>Lokasjon Raufoss</p><p>Studieavgift kr. 0</p></div>
<section><h2>Gjennomføring</h2><p>Kombinasjon av fysiske og nettbaserte samlinger.</p></section>
<section><h2>Kommende gjennomføringer</h2><p>Planlagt oppstart høsten 2027; eksakt dato publiseres senere.</p></section>
<section><h2>Nyttig å vite</h2><h3>Opptakskrav</h3><p>Fagbrev som elektriker eller relevant praksis.</p><p>Bøker og annet studiemateriell kan medføre ekstra kostnader.</p></section>
<section><h2>Kontaktpersoner faglig innhold</h2><p>ACADEMIC_CONTACT_MARKER</p><h3>Gjennomføring</h3><p>NESTED_ACADEMIC_CONTACT_MARKER</p></section>
<section><h2>Spørsmål om søknad, dokumentasjon og regelverk</h2><p>ADMIN_CONTACT_MARKER</p><h3>Nyttig å vite</h3><p>NESTED_ADMIN_CONTACT_MARKER</p></section>
</main><footer><p>Footer leak</p></footer></body></html>"""


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status
        self.headers = Message()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def read(self, limit=-1):
        return self.body[:limit]


class CourseSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.output = root / "out" / "course-sources.json"
        self.fixture = root / "fixtures" / "course-sources.json"
        self.output_patch = patch.object(source, "OUTPUT", self.output)
        self.fixture_patch = patch.object(source, "FIXTURE", self.fixture)
        self.output_patch.start()
        self.fixture_patch.start()
        self.addCleanup(self.output_patch.stop)
        self.addCleanup(self.fixture_patch.stop)

    def test_extracts_labelled_course_sections_and_excludes_contact_form_navigation_and_footer(self):
        result = source.extract_course(HTML, "automation-introduction", source.COURSES[0][1], "2026-10-28T12:00:00+00:00")
        self.assertEqual(result["title"], "Automasjon for elektrikere – Introduksjon")
        text = "\n".join(section["text"] for section in result["source_sections"])
        self.assertIn("Søknadsfrist", text)
        self.assertIn("9. februar 2027", text)
        self.assertIn("Opptakskrav", [section["label"] for section in result["source_sections"]])
        self.assertIn("Fagbrev som elektriker eller relevant praksis.", text)
        self.assertIn("Planlagt oppstart høsten 2027; eksakt dato publiseres senere.", text)
        self.assertIn("Bøker og annet studiemateriell kan medføre ekstra kostnader.", text)
        self.assertNotIn("ACADEMIC_CONTACT_MARKER", text)
        self.assertNotIn("NESTED_ACADEMIC_CONTACT_MARKER", text)
        self.assertNotIn("ADMIN_CONTACT_MARKER", text)
        self.assertNotIn("NESTED_ADMIN_CONTACT_MARKER", text)
        self.assertNotIn("Newsletter", text)
        self.assertNotIn("Navigation leak", text)
        self.assertNotIn("Footer leak", text)
        self.assertTrue(result["source_text_is_untrusted_data"])

    def test_application_administration_contact_heading_variants_are_excluded(self):
        html = HTML.replace(
            "Spørsmål om søknad, dokumentasjon og regelverk",
            "  Spørsmål   om SØKNAD / DOKUMENTASJON og regelverk  ",
        )
        result = source.extract_course(html, "automation-introduction", source.COURSES[0][1], "2026-10-28T12:00:00+00:00")
        text = "\n".join(section["text"] for section in result["source_sections"])
        self.assertNotIn("ADMIN_CONTACT_MARKER", text)
        self.assertNotIn("NESTED_ADMIN_CONTACT_MARKER", text)

    def test_collection_fetches_only_robots_and_approved_urls_with_identifying_agent(self):
        urls = []

        def fake_open(request, timeout):
            urls.append(request.full_url)
            self.assertEqual(timeout, source.TIMEOUT_SECONDS)
            self.assertEqual(request.get_header("User-agent"), source.USER_AGENT)
            if request.full_url == source.ROBOTS_URL:
                return FakeResponse("User-agent: *\nAllow: /\n")
            course_id = next(course_id for course_id, url in source.COURSES if url == request.full_url)
            title = {
                "automation-introduction": "Automasjon for elektrikere – Introduksjon",
                "automation-pls": "Automasjon for elektrikere – PLS",
                "automation-robot-regulation": "Automasjon for elektrikere - Robot og regulering",
            }[course_id]
            return FakeResponse(HTML.replace("Automasjon for elektrikere – Introduksjon", title))

        with patch.object(source.time, "sleep") as pause:
            result = source.collect(opener=fake_open, clock=lambda: __import__("datetime").datetime(2026, 10, 28, tzinfo=__import__("datetime").timezone.utc))
        self.assertEqual(urls, [source.ROBOTS_URL] + [url for _, url in source.COURSES])
        self.assertGreaterEqual(pause.call_count, 3)
        self.assertEqual(len(result["courses"]), 3)
        self.assertEqual(result["courses"][0]["retrieved_at"], "2026-10-28T00:00:00+00:00")

    def test_offline_operation_never_uses_network(self):
        self.fixture.parent.mkdir(parents=True)
        expected = {"schema_version": 1, "courses": []}
        for course_id, url in source.COURSES:
            expected["courses"].append({
                "course_id": course_id,
                "source_url": url,
                "retrieved_at": "2026-10-28T00:00:00+00:00",
                "title": "Automasjon for elektrikere – Introduksjon",
                "source_sections": [{"label": "Course overview", "text": "Fixture data"}],
            })
        self.fixture.write_text(json.dumps(expected), encoding="utf-8")
        with patch.object(source, "_default_open", side_effect=AssertionError("network used")):
            self.assertEqual(source.main(["--offline"]), 0)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), expected)

    def test_offline_operation_rejects_fixture_with_contact_section(self):
        self.fixture.parent.mkdir(parents=True)
        expected = {"schema_version": 1, "courses": []}
        for course_id, url in source.COURSES:
            expected["courses"].append({
                "course_id": course_id,
                "source_url": url,
                "retrieved_at": "2026-10-28T00:00:00+00:00",
                "title": "Automasjon for elektrikere – Introduksjon",
                "source_sections": [
                    {"label": "Course overview", "text": "Fixture data"},
                    {"label": "Spørsmål om søknad, dokumentasjon og regelverk", "text": "ADMIN_CONTACT_MARKER"},
                ],
            })
        self.fixture.write_text(json.dumps(expected), encoding="utf-8")
        with patch.object(source, "_default_open", side_effect=AssertionError("network used")):
            self.assertEqual(source.main(["--offline"]), 2)

    def test_robot_disallow_and_unexpected_course_page_fail_clearly(self):
        def denied(request, timeout):
            if request.full_url == source.ROBOTS_URL:
                return FakeResponse("User-agent: *\nDisallow: /utdanninger/\n")
            self.fail("course request was made despite robots.txt")

        with self.assertRaisesRegex(RuntimeError, "robots.txt disallows"):
            source.collect(opener=denied)

        def bad_page(request, timeout):
            return FakeResponse("User-agent: *\nAllow: /\n" if request.full_url == source.ROBOTS_URL else "<main><h1>Other page</h1></main>")

        with self.assertRaisesRegex(ValueError, "unexpected course page"):
            source.collect(opener=bad_page)

    def test_failed_collection_does_not_replace_existing_output(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_text("previous successful output\n", encoding="utf-8")
        original = self.output.read_bytes()
        with patch.object(source, "collect", side_effect=RuntimeError("network down")):
            self.assertEqual(source.main([]), 2)
        self.assertEqual(self.output.read_bytes(), original)

    def test_response_size_limit_is_enforced(self):
        with patch.object(source, "MAX_RESPONSE_BYTES", 5):
            with self.assertRaisesRegex(RuntimeError, "exceeded 5 bytes"):
                source._read_response(source.ROBOTS_URL, opener=lambda *_a, **_k: FakeResponse(b"123456"))


if __name__ == "__main__":
    unittest.main()
