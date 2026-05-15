from __future__ import annotations

import csv
import json
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def available_dates() -> list[str]:
    if not DATA_DIR.exists():
        return []
    dates = []
    for path in DATA_DIR.glob("*.csv"):
        if DATE_RE.match(path.stem):
            dates.append(path.stem)
    return sorted(dates, reverse=True)


def read_csv_rows(trade_date: str) -> tuple[list[str], list[dict[str, str]]]:
    if not DATE_RE.match(trade_date):
        raise ValueError("invalid date")

    path = DATA_DIR / f"{trade_date}.csv"
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = reader.fieldnames or []
        rows = []
        for row in reader:
            rows.append({column: (row.get(column) or "").strip() for column in columns})
    return columns, rows


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/dates":
            self.write_json({"dates": available_dates()})
            return

        if parsed.path == "/api/data":
            params = parse_qs(parsed.query)
            trade_date = (params.get("date") or [""])[0]
            try:
                columns, rows = read_csv_rows(trade_date)
            except ValueError:
                self.write_json({"error": "日期格式不正确"}, HTTPStatus.BAD_REQUEST)
                return
            except FileNotFoundError:
                self.write_json({"error": "未找到该日期的 CSV"}, HTTPStatus.NOT_FOUND)
                return

            self.write_json({"date": trade_date, "columns": columns, "rows": rows})
            return

        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def write_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("ZT analysis web is running: http://127.0.0.1:8765")
    print(f"CSV data directory: {DATA_DIR}")
    server.serve_forever()


if __name__ == "__main__":
    main()
