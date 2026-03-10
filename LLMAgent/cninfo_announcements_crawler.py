import json
import os
import re
import time
from datetime import date, timedelta
from typing import Dict, Generator, List, Optional

import requests


QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
FILE_BASE_URL = "https://static.cninfo.com.cn/"
TOP_SEARCH_URL = "https://www.cninfo.com.cn/new/information/topSearch/query"


def create_session(timeout: int = 20) -> tuple[requests.Session, int]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.cninfo.com.cn",
            "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
        }
    )
    return session, timeout


def infer_column(stock_code: str) -> str:
    return "sse" if stock_code.strip().startswith("6") else "szse"


def post_json(session: requests.Session, timeout: int, payload: Dict) -> Dict:
    response = session.post(QUERY_URL, data=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("巨潮返回结果格式异常")
    return data


def resolve_stock_param(session: requests.Session, timeout: int, stock_code: str, stock_name: str) -> str:
    candidates = [stock_code, stock_name]
    for keyword in candidates:
        if not keyword:
            continue
        response = session.post(
            TOP_SEARCH_URL,
            data={"keyWord": keyword, "maxNum": 20, "plate": ""},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list) or not data:
            continue

        exact = None
        for item in data:
            if str(item.get("code", "")).strip() == stock_code.strip():
                exact = item
                break
        chosen = exact or data[0]
        org_id = str(chosen.get("orgId", "")).strip()
        code = str(chosen.get("code", stock_code)).strip()
        if org_id:
            return f"{code},{org_id}"
    return f"{stock_code},{stock_name}"


def iter_announcements(
    session: requests.Session,
    timeout: int,
    stock_code: str,
    stock_param: str,
    start_date: str,
    end_date: str,
    page_size: int = 30,
    sleep_seconds: float = 0.35,
) -> Generator[Dict, None, None]:
    page_num = 1
    while True:
        payload = {
            "pageNum": page_num,
            "pageSize": page_size,
            "column": infer_column(stock_code),
            "tabName": "fulltext",
            "plate": "",
            "stock": stock_param,
            "searchkey": "",
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": f"{start_date}~{end_date}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        data = post_json(session, timeout, payload)
        ann_list = data.get("announcements") or []
        if not ann_list:
            break
        for item in ann_list:
            yield item
        page_num += 1
        time.sleep(sleep_seconds)


def build_file_url(item: Dict) -> Optional[str]:
    adjunct_url = item.get("adjunctUrl")
    if not adjunct_url:
        return None
    if str(adjunct_url).startswith("http://") or str(adjunct_url).startswith("https://"):
        return str(adjunct_url)
    return FILE_BASE_URL + str(adjunct_url).lstrip("/")


def timestamp_to_ymd(value) -> str:
    if value is None:
        return "unknown_date"
    try:
        ts = int(value) / 1000
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except Exception:
        return "unknown_date"


def safe_file_name(value: str) -> str:
    clean = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", value)
    clean = re.sub(r"\s+", " ", clean).strip(" .")
    return clean[:180] if len(clean) > 180 else clean


def sanitize_folder(value: str) -> str:
    clean = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", value)
    return clean.strip(" .")


def download_file(session: requests.Session, timeout: int, url: str, target_path: str) -> None:
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with session.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(target_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)


def build_announcement_file_path(ann_dir: str, item: Dict, announcement_id: str) -> str:
    stock_code = str(item.get("secCode", "")).strip()
    stock_name = str(item.get("secName", "")).strip()
    title = str(item.get("announcementTitle", "")).strip()
    publish_date = timestamp_to_ymd(item.get("announcementTime"))
    base_name = f"{publish_date}_{stock_code}_{stock_name}_{announcement_id}_{title}"

    ext = ".pdf"
    adjunct_url = str(item.get("adjunctUrl", ""))
    maybe_ext = os.path.splitext(adjunct_url)[1].lower()
    if maybe_ext:
        ext = maybe_ext

    return os.path.join(ann_dir, safe_file_name(base_name) + ext)


def write_json(path: str, payload: Dict) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def read_json(path: str) -> Dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def crawl_announcements_last_year(
    stock_code: str,
    stock_name: str,
    days: int = 365,
    output_root: str = "data",
    timeout: int = 20,
    sleep_seconds: float = 0.35,
) -> Dict:
    session, timeout_value = create_session(timeout=timeout)

    folder_name = f"{stock_code}{sanitize_folder(stock_name)}"
    ann_dir = os.path.join(output_root, folder_name, "announcement")
    os.makedirs(ann_dir, exist_ok=True)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    start_ms = int(time.mktime(start_date.timetuple()) * 1000)

    meta_path = os.path.join(ann_dir, "_meta.json")
    old_meta = read_json(meta_path)
    old_records = old_meta.get("records") if isinstance(old_meta.get("records"), list) else []
    known_map = {
        str(record.get("announcement_id")): str(record.get("file_path"))
        for record in old_records
        if isinstance(record, dict) and record.get("announcement_id")
    }

    stock_param = resolve_stock_param(session, timeout_value, stock_code, stock_name)
    remote_items = list(
        iter_announcements(
            session=session,
            timeout=timeout_value,
            stock_code=stock_code,
            stock_param=stock_param,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            sleep_seconds=sleep_seconds,
        )
    )

    downloaded = 0
    skipped_existing = 0
    current_ids = set()
    records: List[Dict] = []

    for item in remote_items:
        announcement_id = str(item.get("announcementId", "")).strip()
        if not announcement_id:
            continue

        publish_time = int(item.get("announcementTime") or 0)
        if publish_time < start_ms:
            continue

        current_ids.add(announcement_id)
        target_path = known_map.get(announcement_id)
        if not target_path:
            target_path = build_announcement_file_path(ann_dir, item, announcement_id)

        file_url = build_file_url(item)
        exists = bool(target_path and os.path.exists(target_path))
        if (not exists) and file_url:
            download_file(session, timeout_value, file_url, target_path)
            downloaded += 1
            exists = True
        elif exists:
            skipped_existing += 1

        records.append(
            {
                "announcement_id": announcement_id,
                "title": item.get("announcementTitle"),
                "sec_code": item.get("secCode"),
                "sec_name": item.get("secName"),
                "publish_time": publish_time,
                "adjunct_url": item.get("adjunctUrl"),
                "file_path": target_path,
                "exists": exists,
            }
        )

    deleted_outdated = 0
    for record in old_records:
        if not isinstance(record, dict):
            continue
        announcement_id = str(record.get("announcement_id", "")).strip()
        old_path = str(record.get("file_path", "")).strip()
        if not announcement_id or announcement_id in current_ids:
            continue
        if old_path and os.path.exists(old_path):
            try:
                os.remove(old_path)
                deleted_outdated += 1
            except OSError:
                pass

    local_existing_count = sum(1 for row in records if row.get("exists"))
    is_up_to_date = local_existing_count >= len(records)

    write_json(
        meta_path,
        {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "scope": f"最近{days}天公告",
            "mode": "sync",
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "remote_total": len(records),
            "local_existing": local_existing_count,
            "downloaded_files": downloaded,
            "skipped_existing": skipped_existing,
            "deleted_outdated": deleted_outdated,
            "is_up_to_date": is_up_to_date,
            "last_sync_date": date.today().strftime("%Y-%m-%d"),
            "records": records,
        },
    )

    return {
        "downloaded": downloaded,
        "total": len(records),
        "deleted_outdated": deleted_outdated,
        "up_to_date": is_up_to_date,
        "path": ann_dir,
    }


