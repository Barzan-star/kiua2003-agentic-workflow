#!/usr/bin/env python3
"""Render validated course records as deterministic JSON and Norwegian Markdown."""

import argparse
import json
from pathlib import Path


def render(records):
    """Return comparison Markdown without making further factual inferences."""
    lines = [
        "# Sammenligning av automasjonskurs",
        "",
        "Datoer, avgifter og status nedenfor er gjengitt fra den kontrollerte kildeoversikten.",
        "",
        "| Kurs | Søknadsfrist | Eksakt oppstart | Planlagt periode | Studieavgift (NOK) | Søknadsstatus |",
        "|---|---|---|---|---:|---|",
    ]
    for course in records["courses"]:
        fee = course["study_fee_nok"]["amount"]
        fee_text = "Ikke oppgitt" if fee is None else str(fee)
        if course["materials_qualification"]["value"]:
            fee_text += "; " + course["materials_qualification"]["value"]
        planned = course["planned_period"]["value"] or "Ikke oppgitt"
        status_names = {
            "not_stated": "Ikke oppgitt i kilden",
            "no_current_openings": "Ingen åpne gjennomføringer nå",
            "open_for_application": "Åpen for søknad (oppgitt i kilden)",
            "uncertain": "Usikkert",
        }
        deadline = course["application_deadline"]["date"] or "Ikke oppgitt"
        start = course["start_date"]["date"] or "Ikke oppgitt"
        lines.append(
            f"| [{course['title']}]({course['source_url']}) | {deadline} | {start} | {planned} | {fee_text} | {status_names[course['application_status']['value']]} |"
        )
    lines.extend(["", "## Opptakskrav", ""])
    for course in records["courses"]:
        lines.append(f"### [{course['title']}]({course['source_url']})")
        lines.append("")
        if course["prerequisites"]:
            lines.extend(f"- {item['text']}" for item in course["prerequisites"])
        else:
            lines.append("Ikke oppgitt i kilden.")
        lines.append("")
        lines.append(f"Kildeinnhentet: `{course['retrieved_at']}`. [Åpne kilden]({course['source_url']}).")
        uncertain = course["missing_or_uncertain_fields"]
        if uncertain:
            lines.append("Uavklart eller mangler: " + ", ".join(uncertain) + ".")
        lines.append("")
    lines.extend([
        "## Tolkning og begrensninger",
        "",
        "Sitat- og feltsjekken bekrefter at verdiene finnes i riktig kurskilde, og kontrollerer dato- og avgiftsformat mekanisk. Den beviser ikke at alle opptakskrav eller forbehold er tolket fullstendig. Manglende eller usikre kildeopplysninger er derfor vist som slike, uten å fylle dem inn.",
        "",
    ])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)
    data = json.loads(args.input.read_text(encoding="utf-8"))
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render(data), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
