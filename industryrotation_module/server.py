from __future__ import annotations

import csv
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"


def available_dates() -> list[str]:
    if not DATA_DIR.exists():
        return []
    dates: set[str] = set()
    for path in DATA_DIR.glob("*.csv"):
        stem = path.stem
        if len(stem) >= 10:
            dates.add(stem[:10])
    return sorted(dates, reverse=True)


def read_csv_rows(trade_date: str, level: str) -> list[dict[str, str]]:
    file_path = DATA_DIR / f"{trade_date}-{level}.csv"
    if not file_path.exists():
        raise FileNotFoundError(f"数据文件不存在：{file_path.name}")
    with file_path.open("r", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/dates":
            self._json_response(available_dates())
            return
        if parsed.path == "/api/data":
            params = parse_qs(parsed.query)
            trade_date = (params.get("date") or [None])[0]
            level = (params.get("level") or ["sw1"])[0]
            if not trade_date or level not in ("sw1", "sw2"):
                self._json_response({"error": "缺少 date 或 level 参数"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                rows = read_csv_rows(trade_date, level)
                self._json_response(rows)
            except FileNotFoundError as exc:
                self._json_response({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        super().do_GET()

    def _json_response(self, data, status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def main():
    port = 8766
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"行业轮动分析 web 已启动: http://127.0.0.1:{port}")
    print(f"数据目录: {DATA_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
