import json
import os
import re
import time
import hashlib
from datetime import date
from typing import Dict, Generator, List, Optional, Set

import requests


QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
FILE_BASE_URL = "https://static.cninfo.com.cn/"
TOP_SEARCH_URL = "https://www.cninfo.com.cn/new/information/topSearch/query"

REPORT_CATEGORIES = {
    "年报": "category_ndbg_szsh",
    "半年报": "category_bndbg_szsh",
    "一季报": "category_yjdbg_szsh",
    "三季报": "category_sjdbg_szsh",
}


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
    category: str,
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
            "category": category,
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


def is_summary_report(title: str) -> bool:
    normalized = str(title or "").strip()
    return "摘要" in normalized


def file_sha256(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def remove_duplicate_pdf_by_hash(report_dir: str) -> int:
    hash_to_keep: Dict[str, str] = {}
    deleted = 0

    candidates: List[str] = []
    for root, _, files in os.walk(report_dir):
        for file_name in files:
            if not file_name.lower().endswith(".pdf"):
                continue
            candidates.append(os.path.join(root, file_name))

    candidates.sort()

    for path in candidates:
        try:
            digest = file_sha256(path)
        except OSError:
            continue

        keeper = hash_to_keep.get(digest)
        if not keeper:
            hash_to_keep[digest] = path
            continue

        try:
            os.remove(path)
            deleted += 1
        except OSError:
            pass

    return deleted


def download_file(session: requests.Session, timeout: int, url: str, target_path: str) -> None:
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with session.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(target_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)


def build_report_file_path(report_dir: str, item: Dict, report_type: str, announcement_id: str) -> str:
    stock_code = str(item.get("secCode", "")).strip()
    stock_name = str(item.get("secName", "")).strip()
    title = str(item.get("announcementTitle", "")).strip()
    publish_date = timestamp_to_ymd(item.get("announcementTime"))
    base_name = f"{publish_date}_{stock_code}_{stock_name}_{report_type}_{announcement_id}_{title}"
    return os.path.join(report_dir, safe_file_name(base_name) + ".pdf")


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


def fetch_remote_reports(
    session: requests.Session,
    timeout_value: int,
    stock_code: str,
    stock_param: str,
    sleep_seconds: float,
) -> List[Dict]:
    seen_ids: Set[str] = set()
    seen_adjunct_urls: Set[str] = set()
    remote_items: List[Dict] = []
    for report_type, category in REPORT_CATEGORIES.items():
        for item in iter_announcements(
            session=session,
            timeout=timeout_value,
            stock_code=stock_code,
            stock_param=stock_param,
            category=category,
            start_date="1990-01-01",
            end_date=date.today().strftime("%Y-%m-%d"),
            sleep_seconds=sleep_seconds,
        ):
            announcement_id = str(item.get("announcementId", "")).strip()
            title = str(item.get("announcementTitle", "")).strip()
            adjunct_url = str(item.get("adjunctUrl", "")).strip()
            if not announcement_id or announcement_id in seen_ids:
                continue
            if is_summary_report(title):
                continue
            if adjunct_url and adjunct_url in seen_adjunct_urls:
                continue
            seen_ids.add(announcement_id)
            if adjunct_url:
                seen_adjunct_urls.add(adjunct_url)
            row = dict(item)
            row["_report_type"] = report_type
            remote_items.append(row)
    return remote_items


def crawl_reports_since_listing(
    stock_code: str,
    stock_name: str,
    output_root: str = "data",
    timeout: int = 20,
    sleep_seconds: float = 0.35,
) -> Dict:
    session, timeout_value = create_session(timeout=timeout)
    folder_name = f"{stock_code}{sanitize_folder(stock_name)}"
    report_dir = os.path.join(output_root, folder_name, "report")
    os.makedirs(report_dir, exist_ok=True)

    meta_path = os.path.join(report_dir, "_meta.json")
    old_meta = read_json(meta_path)
    old_records = old_meta.get("records") if isinstance(old_meta.get("records"), list) else []
    known_map = {
        str(record.get("announcement_id")): str(record.get("file_path"))
        for record in old_records
        if isinstance(record, dict) and record.get("announcement_id")
    }

    deleted_summary_files = 0
    removed_invalid_dirs = 0
    deleted_duplicate_files = 0
    for record in old_records:
        if not isinstance(record, dict):
            continue
        title = str(record.get("title", "")).strip()
        file_path = str(record.get("file_path", "")).strip()
        if is_summary_report(title) and file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                deleted_summary_files += 1
            except OSError:
                pass

    for root, _, files in os.walk(report_dir):
        for file_name in files:
            if file_name == "_meta.json":
                continue
            file_path = os.path.join(root, file_name)
            if "摘要" in file_name:
                try:
                    os.remove(file_path)
                    deleted_summary_files += 1
                except OSError:
                    pass

    invalid_dir = os.path.join(report_dir, "announcement")
    if os.path.isdir(invalid_dir):
        try:
            for root, dirs, files in os.walk(invalid_dir, topdown=False):
                for file_name in files:
                    try:
                        os.remove(os.path.join(root, file_name))
                    except OSError:
                        pass
                for dir_name in dirs:
                    try:
                        os.rmdir(os.path.join(root, dir_name))
                    except OSError:
                        pass
            os.rmdir(invalid_dir)
            removed_invalid_dirs += 1
        except OSError:
            pass

    deleted_duplicate_files = remove_duplicate_pdf_by_hash(report_dir)

    stock_param = resolve_stock_param(session, timeout_value, stock_code, stock_name)
    remote_items = fetch_remote_reports(
        session=session,
        timeout_value=timeout_value,
        stock_code=stock_code,
        stock_param=stock_param,
        sleep_seconds=sleep_seconds,
    )

    downloaded = 0
    skipped_existing = 0
    records = []
    newest_remote_time = 0

    for item in remote_items:
        announcement_id = str(item.get("announcementId", "")).strip()
        report_type = str(item.get("_report_type", "")).strip()
        publish_time = int(item.get("announcementTime") or 0)
        newest_remote_time = max(newest_remote_time, publish_time)

        target_path = known_map.get(announcement_id)
        if not target_path:
            target_path = build_report_file_path(report_dir, item, report_type, announcement_id)

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
                "report_type": report_type,
                "title": item.get("announcementTitle"),
                "publish_time": publish_time,
                "adjunct_url": item.get("adjunctUrl"),
                "file_path": target_path,
                "exists": exists,
            }
        )

    local_existing_count = sum(1 for row in records if row.get("exists"))
    is_up_to_date = local_existing_count >= len(remote_items)

    write_json(
        meta_path,
        {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "scope": "上市以来财报（年报/半年报/季报）",
            "mode": "sync",
            "remote_total": len(remote_items),
            "local_existing": local_existing_count,
            "downloaded_files": downloaded,
            "skipped_existing": skipped_existing,
            "deleted_summary_files": deleted_summary_files,
            "deleted_duplicate_files": deleted_duplicate_files,
            "removed_invalid_dirs": removed_invalid_dirs,
            "is_up_to_date": is_up_to_date,
            "last_sync_date": date.today().strftime("%Y-%m-%d"),
            "latest_remote_publish_date": timestamp_to_ymd(newest_remote_time) if newest_remote_time else "unknown_date",
            "records": records,
        },
    )

    return {
        "downloaded": downloaded,
        "remote_total": len(remote_items),
        "local_existing": local_existing_count,
        "deleted_summary_files": deleted_summary_files,
        "deleted_duplicate_files": deleted_duplicate_files,
        "removed_invalid_dirs": removed_invalid_dirs,
        "up_to_date": is_up_to_date,
        "path": report_dir,
    }


