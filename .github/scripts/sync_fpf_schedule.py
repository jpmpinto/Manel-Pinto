#!/usr/bin/env python3
"""Read-only-first FPF Group Vermelho schedule sync for Diário do Manel."""

from __future__ import annotations

import argparse
import html
import json
import re
import datetime
import sys
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://centroderesultados-as-prd.azurewebsites.net"
START_URL = f"{BASE}/Competition/Details?competitionId=22591&seasonId=106"
INDEX_PATH = Path("index.html")
SCHEDULE_PATH = Path("fpf-schedule.json")
TARGET_TEAM = "Dragon Force F.C. \"C\""
MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "Referer": "https://centroderesultados-as-prd.azurewebsites.net/",
}
MATCH_ROW = re.compile(
    r'<div\s+class="game"[^>]*>\s*'
    r'.*?<div\s+class="home-team[^"]*"[^>]*>(.*?)</div>'
    r'.*?<span\s+class="game-schedule"[^>]*>(.*?)</span>'
    r'.*?<div\s+class="away-team[^"]*"[^>]*>(.*?)</div>\s*</div>\s*'
    r'<div\s+class="game-list-stadium"[^>]*>\s*.*?<small[^>]*>(.*?)</small>\s*</div>',
    re.I | re.S,
)


def fetch(url: str) -> str:
    request = Request(url, headers=HEADERS)
    try:
        with urlopen(request, timeout=20) as response:
            status = getattr(response, "status", 200)
            body = response.read().decode("utf-8", "replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"FPF request failed for {url}: {exc}") from exc
    if status != 200:
        raise RuntimeError(f"FPF returned HTTP {status} for {url}")
    if len(body) < 1000:
        raise RuntimeError(f"FPF response was unexpectedly short ({len(body)} bytes): {url}")
    return body


def plain(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ").split())


def norm_team(value: str) -> str:
    value = unicodedata.normalize("NFKD", html.unescape(value))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def display_team(value: str) -> str:
    value = plain(value)
    return re.sub(r'"([^"]+)"', r"“\1”", value)


def find_div_contents(document: str, div_id: str) -> str:
    opening = re.search(r'<div\b[^>]*\bid="' + re.escape(div_id) + r'"[^>]*>', document, re.I)
    if not opening:
        raise RuntimeError(f"FPF fixture response did not contain div id={div_id!r}")
    start = opening.end()
    depth = 1
    for match in re.finditer(r"</?div\b[^>]*>", document[start:], re.I):
        tag = match.group(0)
        if tag.lower().startswith("</div"):
            depth -= 1
            if depth == 0:
                return document[start:start + match.start()]
        elif not tag.rstrip().endswith("/>"):
            depth += 1
    raise RuntimeError(f"Could not find the closing tag for div id={div_id!r}")


def parse_fixture_ids(page: str) -> list[tuple[int, str]]:
    marker = re.search(r"<span>\s*GRUPO VERMELHO\s*</span>", page, re.I)
    if not marker:
        raise RuntimeError("Could not find GRUPO VERMELHO in the 2026/27 FPF page")
    start = page.rfind('<div class="game-results', 0, marker.start())
    if start < 0:
        raise RuntimeError("Could not find the Group Vermelho container")
    end = page.find('<div class="game-results', marker.end())
    group_html = page[start:end if end >= 0 else len(page)]
    pairs = [
        (int(round_no), fixture_id)
        for fixture_id, round_no in re.findall(
            r'href="[^"]*GetClassificationAndMatchesByFixture\?fixtureId=(\d+)"[^>]*>\s*(\d+)\s*</a>',
            group_html,
            re.I,
        )
    ]
    pairs.sort()
    if len(pairs) < 9 or pairs != [(n, fid) for n, fid in pairs]:
        raise RuntimeError(f"Unexpected fixture links in Group Vermelho: {pairs!r}")
    round_numbers = [n for n, _ in pairs]
    if round_numbers != list(range(1, len(pairs) + 1)):
        raise RuntimeError(f"Round numbers are not consecutive: {round_numbers!r}")
    return pairs


def parse_date_time(schedule: str) -> tuple[str, str]:
    text = plain(schedule).lower()
    day_month = re.search(r"\b(\d{1,2})\s+(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\b", text)
    if not day_month:
        return "", ""
    day = int(day_month.group(1))
    month = MONTHS[day_month.group(2)]
    # The FPF season id 106 is the 2026/27 season.
    year = 2026 if month >= 8 else 2027
    kickoff_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    kickoff = f"{int(kickoff_match.group(1)):02d}:{kickoff_match.group(2)}" if kickoff_match else ""
    return f"{year:04d}-{month:02d}-{day:02d}", kickoff


def parse_matches(fragment: str) -> list[dict[str, str]]:
    section = find_div_contents(fragment, "matches")
    expected_rows = len(re.findall(r'<div\s+class="game"[^>]*>', section, re.I))
    rows = []
    for home_html, schedule_html, away_html, venue_html in MATCH_ROW.findall(section):
        home, away = display_team(home_html), display_team(away_html)
        date, kickoff = parse_date_time(schedule_html)
        rows.append({
            "home": home,
            "away": away,
            "date": date,
            "kickoff": kickoff,
            "venue": plain(venue_html),
        })
    if not rows or len(rows) != expected_rows:
        raise RuntimeError(
            f"Could not parse all FPF games in a round: parsed {len(rows)} of {expected_rows}"
        )
    return rows


def read_existing_seeds(index: str) -> list[list[object]]:
    match = re.search(r"var SEED=(\[[\s\S]*?\]);\s*function seed\(\)", index)
    if not match:
        raise RuntimeError("Could not locate the existing SEED array in index.html")
    try:
        seeds = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Existing SEED array is not valid JSON: {exc}") from exc
    if not isinstance(seeds, list) or not seeds:
        raise RuntimeError("Existing SEED array was empty")
    return seeds


def make_seed_rows(rounds: list[dict[str, object]], existing: list[list[object]]) -> list[list[object]]:
    if len(rounds) != len(existing):
        raise RuntimeError(
            f"Official FPF now has {len(rounds)} rounds but index.html has {len(existing)}. "
            "Refusing to renumber fixtures or risk mixing player stats."
        )
    output = []
    target = norm_team(TARGET_TEAM)
    total_played = 0
    for idx, entry in enumerate(rounds):
        round_no = idx + 1
        rows = entry["matches"]
        found = []
        for game in rows:
            home_match = norm_team(game["home"]) == target
            away_match = norm_team(game["away"]) == target
            if home_match or away_match:
                found.append((game, home_match))
        if len(found) > 1:
            raise RuntimeError(f"Jornada {round_no} contains multiple Dragon Force C games")
        if found:
            game, is_home = found[0]
            if not game["date"]:
                raise RuntimeError(f"Jornada {round_no} has a Dragon Force C fixture without a readable date")
            opponent = game["away"] if is_home else game["home"]
            output.append([
                game["date"], f"Jornada {round_no}", opponent, 1 if is_home else 0,
                game["venue"], game["kickoff"],
            ])
            total_played += 1
        else:
            # An empty round is only treated as a bye if other games in this FPF round parsed successfully.
            output.append([
                str(existing[idx][0]), f"Jornada {round_no}", "", 0, "", "",
            ])
    if not 8 <= total_played <= len(rounds):
        raise RuntimeError(f"Only {total_played} Dragon Force C fixtures were found across {len(rounds)} rounds")
    return output


def run(dry_run: bool) -> int:
    page = fetch(START_URL)
    if not re.search(r'<option[^>]+selected="selected"[^>]+value="106"[^>]*>\s*2026-2027', page, re.I):
        raise RuntimeError("The FPF page did not resolve to season 106 (2026-2027)")
    if not re.search(r"LIGA AFP\s*&quot;?CARLOS ALBERTO", page, re.I):
        raise RuntimeError("The FPF response is not the expected Carlos Alberto competition")
    fixture_links = parse_fixture_ids(page)
    print(f"FPF page OK: season 106, {len(fixture_links)} Group Vermelho rounds")
    rounds = []
    for round_no, fixture_id in fixture_links:
        url = f"{BASE}/Competition/GetClassificationAndMatchesByFixture?fixtureId={fixture_id}"
        round_html = fetch(url)
        matches = parse_matches(round_html)
        target = [
            m for m in matches
            if norm_team(m["home"]) == norm_team(TARGET_TEAM) or norm_team(m["away"]) == norm_team(TARGET_TEAM)
        ]
        if len(target) > 1:
            raise RuntimeError(f"Jornada {round_no} has multiple Dragon Force C fixtures")
        rounds.append({"round": round_no, "fixture_id": fixture_id, "matches": matches})
    index = INDEX_PATH.read_text(encoding="utf-8")
    old_seeds = read_existing_seeds(index)
    new_seeds = make_seed_rows(rounds, old_seeds)
    actual_count = sum(1 for row in new_seeds if row[2])
    print(f"Validated {actual_count} scheduled Dragon Force C matches and {len(new_seeds)-actual_count} bye rounds.")
    print(json.dumps(new_seeds, ensure_ascii=False, indent=2))
    official_schedule = {
        "source": "FPF Centro de Resultados",
        "source_url": START_URL,
        "season_id": 106,
        "season_name": "2026-2027",
        "competition_id": 29761,
        "group_name": "GRUPO VERMELHO",
        "team_name": "Dragon Force F.C. C",
        "matches": [
            {
                "fixture_key": f"fpf-r{idx + 1}",
                "round_label": row[1],
                "match_date": row[0] if row[2] else None,
                "kickoff": row[5] if row[2] and row[5] else None,
                "opponent": row[2] if row[2] else "Folga",
                "is_home": bool(row[3]),
                "venue": row[4] if row[2] else "",
                "match_status": "scheduled" if row[2] else "bye",
            }
            for idx, row in enumerate(new_seeds)
        ],
    }
    schedule_json = json.dumps(official_schedule, ensure_ascii=False, indent=2) + "\\n"
    print(f"Prepared public schedule metadata for {len(official_schedule['matches'])} rounds.")
    if dry_run:
        return 0
    replacement = "var SEED=" + json.dumps(new_seeds, ensure_ascii=False, indent=0) + ";"
    updated, count = re.subn(r"var SEED=\\[[\\s\\S]*?\\];", replacement, index, count=1)
    if count != 1:
        raise RuntimeError("Could not replace the SEED array safely")
    if updated != index:
        INDEX_PATH.write_text(updated, encoding="utf-8")
        print("Updated index.html from the official FPF schedule.")
    else:
        print("No index.html schedule changes detected.")
    previous_schedule = SCHEDULE_PATH.read_text(encoding="utf-8") if SCHEDULE_PATH.exists() else None
    if previous_schedule != schedule_json:
        SCHEDULE_PATH.write_text(schedule_json, encoding="utf-8")
        print("Updated fpf-schedule.json for read-only visitor views.")
    else:
        print("No public schedule JSON changes detected.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write the official fixture data into index.html")
    args = parser.parse_args()
    try:
        return run(dry_run=not args.apply)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
