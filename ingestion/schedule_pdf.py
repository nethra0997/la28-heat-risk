"""Parse the LA28 'Competition Schedule by Session' PDF into one row per session.

The PDF is a grid: venue | sport | one column per day (July 10-30, 2028).
Merged venue/sport cells put their label in the vertical middle of the block, so
naive text/table extraction assigns sessions to the wrong venue. Instead we use
the drawn geometry:

* horizontal borders starting at the venue column (x~19) separate venue blocks
* horizontal borders starting at the sport column (x~61) separate sport blocks
* vertical borders define the day columns
* a cell's fill colour marks gold (yellow) / bronze (peach) medal sessions

Usage:  uv run python -m ingestion.schedule_pdf
"""

from __future__ import annotations

import re
from itertools import pairwise
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pdfplumber
import requests

from ingestion.common import BRONZE, write_bronze

PDF_URL = (
    "https://la28.org/content/dam/latwentyeight/competition-schedule-imagery/"
    "uploaded-june-9th-oly-3-1/LA28OlympicGamesCompetitionScheduleBySessionV3.1.pdf"
)
SCHEDULE_VERSION = "3.1"
FIRST_DAY = date(2028, 7, 10)  # "Day -4" column

VENUE_X, SPORT_X, GRID_X = 61.0, 117.0, 117.0
TIME_RE = re.compile(r"^(\d{2}):(\d{2})(?:\s*-\s*(\d{2}):(\d{2}))?$")
GOLD, BRONZE_FILL = (1.0, 1.0, 0.0), (0.969, 0.78, 0.675)


@dataclass
class Session:
    page: int
    zone: str | None
    venue_label: str
    sport: str
    session_date: date
    day_number: int
    start_time: str | None
    end_time: str | None
    ends_next_day: bool
    status: str  # scheduled | tbd | contingency
    medal: str | None  # gold | bronze | None
    time_basis: str  # LA (all LA28 times are Pacific) or LOCAL (OKC local time)


def download(path: Path = BRONZE / "schedule" / f"schedule_v{SCHEDULE_VERSION}.pdf") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        r = requests.get(PDF_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


def _close(a, b, tol=0.02) -> bool:
    if not isinstance(a, (tuple, list)) or len(a) != 3:
        return False
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _lines(words: list[dict], tol: float = 1.0) -> list[list[dict]]:
    """Group words into visual lines by their `top` coordinate."""
    out: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if out and abs(out[-1][0]["top"] - w["top"]) <= tol:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in out]


def _text(words: list[dict]) -> str:
    return " ".join(" ".join(w["text"] for w in line) for line in _lines(words)).strip()


def parse_page(page, page_no: int) -> list[Session]:
    rects = page.rects
    header = next(w for w in page.extract_words() if w["text"] == "Sport/Event")
    table_top = header["bottom"] + 10  # skip the two header rows

    # Day columns from vertical borders right of the sport column.
    xs = sorted({round(r["x0"]) for r in rects if r["width"] < 1 and r["height"] > 3})
    col_edges = [x for x in xs if x >= GRID_X - 1]
    col_edges = [x for i, x in enumerate(col_edges) if i == 0 or x - col_edges[i - 1] > 5]

    def day_col(xc: float) -> int | None:
        for i in range(len(col_edges) - 1):
            if col_edges[i] <= xc < col_edges[i + 1]:
                return i
        return None

    hlines = [r for r in rects if r["height"] < 1 and r["width"] > 300 and r["top"] > table_top - 12]
    venue_edges = sorted({round(r["top"], 1) for r in hlines if r["x0"] < 25})
    sport_edges = sorted(set(venue_edges) | {round(r["top"], 1) for r in hlines if 55 < r["x0"] < 70})

    fills = [r for r in rects if r["width"] > 20 and r["height"] > 3 and r["x0"] >= GRID_X - 1]

    def medal_at(w) -> str | None:
        xc, yc = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
        for r in fills:
            if r["x0"] <= xc <= r["x1"] and r["top"] <= yc <= r["bottom"]:
                c = r.get("non_stroking_color")
                if _close(c, GOLD):
                    return "gold"
                if _close(c, BRONZE_FILL):
                    return "bronze"
        return None

    words = [w for w in page.extract_words(y_tolerance=1) if w["top"] > table_top]
    sessions: list[Session] = []
    zone: str | None = "Ceremonies"

    for top, bottom in pairwise(venue_edges):
        block = [w for w in words if top < (w["top"] + w["bottom"]) / 2 < bottom]
        if not block:
            continue
        venue_words = [w for w in block if w["x1"] <= VENUE_X + 1]
        grid_words = [w for w in block if w["x0"] >= GRID_X]
        venue_text = _text(venue_words)
        # Some zone headers share a block with the first venue ("X Zone Venue").
        if " Zone " in venue_text:
            zone, venue_text = (p.strip() for p in venue_text.split(" Zone ", 1))
            zone += " Zone"

        # Zone header rows ("DTLA Zone") have no session cells.
        if not grid_words and (venue_text.endswith("Zone") or "Tournaments" in venue_text):
            zone = venue_text
            continue
        if not grid_words:
            continue

        sub_edges = [e for e in sport_edges if top <= e <= bottom]
        for s_top, s_bottom in pairwise(sub_edges):
            sub = [w for w in block if s_top < (w["top"] + w["bottom"]) / 2 < s_bottom]
            sport = _text([w for w in sub if VENUE_X - 1 <= w["x0"] and w["x1"] <= SPORT_X + 1])
            cells = [w for w in sub if w["x0"] >= GRID_X]
            if not cells:
                continue
            sessions += _cells_to_sessions(cells, day_col, medal_at, page_no, zone, venue_text, sport)
    return sessions


def _cells_to_sessions(cells, day_col, medal_at, page_no, zone, venue, sport) -> list[Session]:
    out: list[Session] = []
    by_col: dict[int, list[dict]] = {}
    for w in cells:
        c = day_col((w["x0"] + w["x1"]) / 2)
        if c is not None:
            by_col.setdefault(c, []).append(w)

    for col, ws in by_col.items():
        lines = _lines(ws)
        texts = [" ".join(w["text"] for w in ln) for ln in lines]
        # OKC venues print each session twice: local time, then "LA Time".
        # Keep only the rows labelled "LA Time"; rotated duplicates fail TIME_RE.
        has_tz_labels = any(t in ("LA Time", "OKC Time") for t in texts)
        for i, (ln, t) in enumerate(zip(lines, texts)):
            basis = "LA"
            if has_tz_labels:
                nxt = texts[i + 1] if i + 1 < len(texts) else ""
                if nxt != "LA Time":
                    continue
            d = FIRST_DAY + timedelta(days=col)
            base = dict(page=page_no, zone=zone, venue_label=venue, sport=sport,
                        session_date=d, day_number=col - 4, time_basis=basis)
            if t in ("TBD", "T T B B D D") or t.startswith("TBD"):
                for _ in range(max(1, t.count("TBD"))):
                    out.append(Session(**base, start_time=None, end_time=None, ends_next_day=False,
                                       status="tbd", medal=medal_at(ln[0])))
                continue
            if t == "Contingency":
                out.append(Session(**base, start_time=None, end_time=None, ends_next_day=False,
                                   status="contingency", medal=None))
                continue
            m = TIME_RE.match(t)
            if not m:
                continue
            h1, m1, h2, m2 = m.groups()
            start = f"{h1}:{m1}"
            end = f"{h2}:{m2}" if h2 else None
            out.append(Session(**base, start_time=start, end_time=end,
                               ends_next_day=bool(end and end < start),
                               status="scheduled", medal=medal_at(ln[0])))
    return out


def parse(pdf_path: Path) -> pd.DataFrame:
    rows: list[Session] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            rows += parse_page(page, i + 1)
    df = pd.DataFrame([asdict(r) for r in rows])
    df["venue_label"] = df["venue_label"].str.replace(r"\s+", " ", regex=True)
    df["schedule_version"] = SCHEDULE_VERSION
    return df


def main() -> None:
    df = parse(download())
    write_bronze(df, "schedule_sessions")
    print(f"parsed {len(df)} sessions across {df.venue_label.nunique()} venues")


if __name__ == "__main__":
    main()
