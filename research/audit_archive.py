"""Read and inventory every member of the user-supplied archive, without modifying it.

Full paper/dictionary extracts stay in ignored data/. Only source metadata and
quality checks are suitable for publication. No season-end stats enter predictors.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "data" / "audit_deps"))


class HashedStream(io.RawIOBase):
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
    def readable(self):
        return True
    def readinto(self, buffer):
        b = self.stream.read(len(buffer))
        self.digest.update(b)
        buffer[:len(b)] = b
        return len(b)


def read_table(archive, entry, cache):
    source = HashedStream(archive.open(entry))
    stream = io.TextIOWrapper(io.BufferedReader(source), encoding="utf-8-sig", errors="replace", newline="")
    reader = csv.reader(stream)
    header = next(reader)
    missing = Counter()
    lengths = Counter()
    selected = {i: Counter() for i, c in enumerate(header) if c.lower() in {
        "season", "season_type", "league", "game_date", "game_id", "athlete_position_abbreviation", "athlete_position_name"
    }}
    game_ids = set()
    game_column = next((i for i, c in enumerate(header) if c.lower() == "game_id"), None)
    rows = 0
    errors = []
    try:
        for row in reader:
            rows += 1
            lengths[len(row)] += 1
            if len(row) != len(header):
                if len(errors) < 8:
                    errors.append({"record": rows, "fields": len(row), "expected_fields": len(header)})
                continue
            missing.update(i for i, x in enumerate(row) if x.strip().lower() in {"", "na", "nan", "null", "none"})
            for i, counts in selected.items():
                value = row[i]
                if header[i].lower() == "game_date":
                    value = value[:4]
                if header[i].lower() != "game_id":
                    counts[value] += 1
            if game_column is not None:
                game_ids.add(row[game_column])
    except csv.Error as exc:
        errors.append({"csv_error": str(exc), "line_number": reader.line_num})
        # Consume all remaining bytes so the source hash still covers the file.
        for _ in iter(lambda: stream.read(1024 * 1024), ""):
            pass
    result = {
        "rows_read": rows, "columns": header, "column_count": len(header),
        "duplicate_column_names": [k for k, n in Counter(header).items() if n > 1],
        "record_field_counts": dict(lengths),
        "malformed_records": sum(n for size, n in lengths.items() if size != len(header)),
        "parse_errors": errors,
        "missing_by_column": {header[i]: n for i, n in missing.items()},
        "selected_values": {header[i]: dict(c.most_common(30)) for i, c in selected.items() if c},
        "distinct_game_ids": len(game_ids) if game_column is not None else None,
        "sha256": source.digest.hexdigest(),
    }
    stream.close()
    return result


def read_workbook(raw):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(raw)) as book:
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            shared = ["".join(si.itertext()) for si in root.findall("m:si", ns)]
        sheets = []
        for path in book.namelist():
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", path):
                root = ET.fromstring(book.read(path))
                cells = []
                for c in root.findall(".//m:sheetData/m:row/m:c", ns):
                    v = c.find("m:v", ns)
                    inline = c.find("m:is", ns)
                    value = v.text if v is not None else "".join(inline.itertext()) if inline is not None else ""
                    if c.get("t") == "s" and value:
                        value = shared[int(value)]
                    if value:
                        cells.append({"cell": c.get("r"), "value": value})
                sheets.append({"sheet_xml": path, "nonempty_cells": len(cells), "cells": cells})
        names = ET.fromstring(book.read("xl/workbook.xml")).findall("m:sheets/m:sheet", ns)
        for s, name in zip(sheets, names):
            s["name"] = name.get("name")
        return sheets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    args = ap.parse_args()
    source = args.source.resolve(strict=True)
    cache = HERE / "data" / "archive_review"
    cache.mkdir(parents=True, exist_ok=True)
    results = HERE / "results"
    results.mkdir(exist_ok=True)
    started = time.time()
    sha = hashlib.sha256()
    with source.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            sha.update(block)
    record = {"source_filename": source.name, "source_bytes": source.stat().st_size,
              "source_sha256": sha.hexdigest(), "reviewed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "members": [], "policy": "Archive unchanged. Paper text, dictionaries and raw tables remain local. Salary and full-season stats are excluded from pre-shot predictors."}
    with zipfile.ZipFile(source) as archive:
        for entry in archive.infolist():
            item = {"path": entry.filename, "bytes": entry.file_size, "compressed_bytes": entry.compress_size, "is_directory": entry.is_dir()}
            if entry.is_dir():
                item["status"] = "directory"
                record["members"].append(item)
                continue
            print("AUDIT", entry.filename, flush=True)
            try:
                suffix = Path(entry.filename).suffix.lower()
                if suffix == ".csv":
                    item.update(read_table(archive, entry, cache))
                    item["status"] = "read_all_records" if not item["parse_errors"] else "review_required"
                else:
                    raw = archive.read(entry)
                    item["sha256"] = hashlib.sha256(raw).hexdigest()
                    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(entry.filename).stem)[:130]
                    if suffix == ".pdf":
                        from pypdf import PdfReader
                        doc = PdfReader(io.BytesIO(raw))
                        pages = [p.extract_text() or "" for p in doc.pages]
                        text = "\n\n".join(f"PAGE {i+1}\n{p}" for i, p in enumerate(pages))
                        (cache / (slug + ".txt")).write_text(text, encoding="utf-8")
                        item.update(pages=len(pages), text_characters=len(text), pages_without_text=[i+1 for i,p in enumerate(pages) if not p.strip()], extraction_file=slug+".txt")
                    elif suffix == ".docx":
                        with zipfile.ZipFile(io.BytesIO(raw)) as doc:
                            root = ET.fromstring(doc.read("word/document.xml"))
                            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                            paragraphs = ["".join(t.text or "" for t in p.iter(ns+"t")) for p in root.iter(ns+"p")]
                            text = "\n".join(paragraphs)
                            (cache / (slug + ".txt")).write_text(text, encoding="utf-8")
                            item.update(paragraphs=len(paragraphs), text_characters=len(text), extraction_file=slug+".txt")
                    elif suffix == ".xlsx":
                        sheets = read_workbook(raw)
                        (cache / "data_dictionary.json").write_text(json.dumps(sheets, ensure_ascii=False, indent=2), encoding="utf-8")
                        item["sheets"] = [{k:v for k,v in s.items() if k != "cells"} for s in sheets]
                    elif suffix == ".txt":
                        text = raw.decode("utf-8-sig", errors="replace")
                        item.update(lines=len(text.splitlines()), text_characters=len(text), header=text.splitlines()[0] if text.splitlines() else "")
                        # Basketball Reference exports may be HTML despite their .txt extension.
                        item["contains_html_table"] = "<table" in text.lower()
                        item["usage"] = "Season-end description only; unavailable before every shot in that season."
                        (cache / (slug + ".txt")).write_text(text, encoding="utf-8")
                    item["status"] = "read_all_bytes"
            except Exception as exc:
                item["status"] = "review_required"
                item["error"] = f"{type(exc).__name__}: {exc}"
            record["members"].append(item)
            (results / "archive_audit.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    record["files_reviewed"] = sum(not x["is_directory"] for x in record["members"])
    record["seconds"] = time.time() - started
    record["all_members_accounted_for"] = len(record["members"]) == len(archive.infolist())
    (results / "archive_audit.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    with (results / "archive_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["path", "bytes", "sha256", "status", "rows_read", "malformed_records", "pages", "text_characters"]
        writer = csv.DictWriter(f, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(x for x in record["members"] if not x["is_directory"])
    print("ARCHIVE_AUDIT_COMPLETE", record["files_reviewed"], "files", round(record["seconds"], 1), "seconds", flush=True)


if __name__ == "__main__":
    main()
