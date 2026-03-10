import json
import os
import re
import shutil
import sqlite3
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np


def is_valid_pdf_file(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            header = file.read(5)
        return header.startswith(b"%PDF")
    except OSError:
        return False


def discover_files(stock_root: Path) -> List[Path]:
    targets = []
    for sub in ["report", "announcement"]:
        folder = stock_root / sub
        if not folder.exists():
            continue
        for p in folder.rglob("*"):
            if p.is_file() and p.suffix.lower() in [".pdf", ".txt", ".md"]:
                targets.append(p)
    return targets


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def read_pdf_pages_text(path: Path) -> List[str]:
    try:
        from pypdf import PdfReader
    except Exception as ex:
        raise RuntimeError("缺少 pypdf，请先安装：pip install pypdf") from ex

    reader = PdfReader(str(path))
    page_texts: List[str] = []
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            page_texts.append((page.extract_text() or "").strip())
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            print(f"[页面跳过] {path.name} p{page_index}: {ex}")
            page_texts.append("")
    return page_texts


def should_trigger_ocr(page_texts: List[str], min_chars_per_page: int, min_avg_chars: int) -> bool:
    if not page_texts:
        return True
    lengths = [len(t.strip()) for t in page_texts]
    low_pages = sum(1 for v in lengths if v < min_chars_per_page)
    avg_chars = sum(lengths) / max(len(lengths), 1)
    return low_pages >= max(1, int(0.6 * len(lengths))) or avg_chars < min_avg_chars


def ocr_pdf_with_rapidocr(path: Path) -> str:
    try:
        import fitz
    except Exception as ex:
        raise RuntimeError("缺少 PyMuPDF，请先安装：pip install pymupdf") from ex
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as ex:
        raise RuntimeError("缺少 rapidocr-onnxruntime，请先安装：pip install rapidocr-onnxruntime") from ex

    engine = RapidOCR()
    doc = fitz.open(str(path))
    page_texts: List[str] = []

    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        img_bytes = pix.tobytes("png")
        result, _ = engine(img_bytes)
        if result:
            text = "\n".join([line[1] for line in result if len(line) > 1])
            page_texts.append(text)
        else:
            page_texts.append("")

    doc.close()
    return "\n".join(page_texts)


def clean_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int = 700, overlap: int = 120) -> List[str]:
    if len(text) <= chunk_size:
        return [text]

    segments: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        piece = text[start:end].strip()
        if piece:
            segments.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return segments


def iter_documents(
    stock_root: Path,
    ocr_mode: str = "auto",
    ocr_min_chars_per_page: int = 30,
    ocr_min_avg_chars: int = 80,
) -> Iterable[Dict]:
    files = discover_files(stock_root)
    total_files = len(files)
    print(f"[RAG] 待处理文件数: {total_files}")

    for idx, file in enumerate(files, start=1):
        if idx == 1 or idx == total_files or idx % 20 == 0:
            print(f"[RAG] 处理进度: {idx}/{total_files} | {file.name}")

        try:
            if file.suffix.lower() == ".pdf":
                if not is_valid_pdf_file(file):
                    print(f"[文件跳过] 非有效PDF: {file.name}")
                    continue

                page_texts = read_pdf_pages_text(file)
                text = "\n".join(page_texts)

                do_ocr = False
                if ocr_mode == "on":
                    do_ocr = True
                elif ocr_mode == "auto":
                    do_ocr = should_trigger_ocr(
                        page_texts,
                        min_chars_per_page=ocr_min_chars_per_page,
                        min_avg_chars=ocr_min_avg_chars,
                    )

                if do_ocr:
                    try:
                        ocr_text = ocr_pdf_with_rapidocr(file)
                        if len(ocr_text.strip()) > len(text.strip()):
                            text = ocr_text
                    except Exception as ex:
                        print(f"[OCR跳过] {file.name}: {ex}")
            else:
                text = read_text_file(file)
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            print(f"[文件跳过] 解析失败 {file.name}: {ex}")
            continue

        text = clean_text(text)
        if not text:
            continue

        doc_type = "report" if "report" in str(file).lower() else "announcement"
        yield {
            "doc_id": file.stem,
            "source_path": str(file),
            "doc_type": doc_type,
            "text": text,
        }


def _load_embedding_model(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None

    try:
        return SentenceTransformer(model_name)
    except Exception as ex:
        print(f"[RAG] 远程模型不可用，切换离线哈希向量器: {ex}")
        return None


def _encode_with_hashing(texts: List[str], dim: int = 384) -> np.ndarray:
    vectors = np.zeros((len(texts), dim), dtype=np.float32)
    for row_idx, text in enumerate(texts):
        content = str(text or "")
        if not content:
            continue
        content = re.sub(r"\s+", "", content)
        tokens = []
        if len(content) < 2:
            tokens = [content]
        else:
            tokens = [content[i : i + 2] for i in range(len(content) - 1)]
        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % dim
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vectors[row_idx, index] += sign

    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def _encode_texts(model, texts: List[str]) -> np.ndarray:
    if model is None:
        return _encode_with_hashing(texts)
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vectors, dtype=np.float32)


def get_rag_paths(stock_root: Path) -> Dict[str, Path]:
    rag_root = stock_root / "rag"
    return {
        "rag_root": rag_root,
        "chunks_db": rag_root / "chunks.db",
        "chunks_meta": rag_root / "chunks_meta.json",
        "embeddings": rag_root / "embeddings.npy",
        "meta": rag_root / "meta.json",
        "build_state": rag_root / "build_state.json",
        "embedding_parts": rag_root / "embedding_parts",
    }


def _write_json(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _init_chunks_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_type ON chunks(doc_type)")
    conn.commit()
    return conn


def _build_chunks_db(
    stock_root: Path,
    paths: Dict[str, Path],
    chunk_size: int,
    overlap: int,
    ocr_mode: str,
    ocr_min_chars_per_page: int,
    ocr_min_avg_chars: int,
) -> Tuple[int, int]:
    if paths["chunks_db"].exists() and paths["chunks_meta"].exists():
        meta = _read_json(paths["chunks_meta"])
        chunk_count = int(meta.get("chunk_count", 0))
        doc_count = int(meta.get("doc_count", 0))
        if chunk_count > 0:
            print(f"[RAG] 复用已有 chunks.db: docs={doc_count}, chunks={chunk_count}")
            return doc_count, chunk_count

    if paths["chunks_db"].exists():
        paths["chunks_db"].unlink(missing_ok=True)

    conn = _init_chunks_db(paths["chunks_db"])
    doc_count = 0
    chunk_count = 0

    try:
        for doc in iter_documents(
            stock_root=stock_root,
            ocr_mode=ocr_mode,
            ocr_min_chars_per_page=ocr_min_chars_per_page,
            ocr_min_avg_chars=ocr_min_avg_chars,
        ):
            doc_count += 1
            pieces = chunk_text(doc["text"], chunk_size=chunk_size, overlap=overlap)
            rows = [
                (doc["doc_id"], doc["source_path"], doc["doc_type"], i, piece)
                for i, piece in enumerate(pieces)
                if piece
            ]
            if rows:
                conn.executemany(
                    "INSERT INTO chunks (doc_id, source_path, doc_type, chunk_index, text) VALUES (?, ?, ?, ?, ?)",
                    rows,
                )
                chunk_count += len(rows)

            if doc_count % 20 == 0:
                conn.commit()
    finally:
        conn.commit()
        conn.close()

    _write_json(
        paths["chunks_meta"],
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "chunk_size": chunk_size,
            "overlap": overlap,
            "ocr_mode": ocr_mode,
            "ocr_min_chars_per_page": ocr_min_chars_per_page,
            "ocr_min_avg_chars": ocr_min_avg_chars,
            "doc_count": doc_count,
            "chunk_count": chunk_count,
            "storage": "sqlite",
            "chunks_db": str(paths["chunks_db"]),
        },
    )
    print(f"[RAG] 切片已落盘到SQLite: docs={doc_count}, chunks={chunk_count}")
    return doc_count, chunk_count


def _count_chunks(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("SELECT COUNT(1) FROM chunks").fetchone()[0])
    finally:
        conn.close()


def _fetch_chunk_text_batch(db_path: Path, start: int, limit: int) -> List[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "SELECT text FROM chunks ORDER BY id LIMIT ? OFFSET ?",
            (limit, start),
        )
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def _fetch_chunks_by_ids(db_path: Path, chunk_ids: List[int]) -> Dict[int, Dict]:
    if not chunk_ids:
        return {}
    placeholders = ",".join(["?"] * len(chunk_ids))
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            f"SELECT id, doc_id, source_path, doc_type, chunk_index, text FROM chunks WHERE id IN ({placeholders})",
            chunk_ids,
        )
        result = {}
        for row in cursor.fetchall():
            result[int(row[0])] = {
                "id": int(row[0]),
                "doc_id": row[1],
                "source_path": row[2],
                "doc_type": row[3],
                "chunk_index": int(row[4]),
                "text": row[5],
            }
        return result
    finally:
        conn.close()


def _reset_embedding_runtime(paths: Dict[str, Path]) -> None:
    if paths["embedding_parts"].exists():
        shutil.rmtree(paths["embedding_parts"], ignore_errors=True)
    paths["embedding_parts"].mkdir(parents=True, exist_ok=True)
    if paths["build_state"].exists():
        paths["build_state"].unlink(missing_ok=True)


def _build_embeddings_resumable(
    db_path: Path,
    total_chunks: int,
    model_name: str,
    paths: Dict[str, Path],
    batch_size: int = 32,
) -> np.ndarray:
    state = _read_json(paths["build_state"])
    resume_valid = (
        state.get("model_name") == model_name
        and int(state.get("total_chunks", -1)) == total_chunks
        and paths["embedding_parts"].exists()
    )

    if not resume_valid:
        _reset_embedding_runtime(paths)
        state = {"model_name": model_name, "total_chunks": total_chunks, "next_index": 0}
        _write_json(paths["build_state"], state)

    next_index = int(state.get("next_index", 0))
    model = _load_embedding_model(model_name)

    while next_index < total_chunks:
        end = min(next_index + batch_size, total_chunks)
        part_file = paths["embedding_parts"] / f"part_{next_index}_{end}.npy"
        if not part_file.exists():
            texts = _fetch_chunk_text_batch(db_path, next_index, end - next_index)
            vectors = _encode_texts(model, texts)
            np.save(part_file, np.asarray(vectors, dtype=np.float32))

        next_index = end
        state["next_index"] = next_index
        _write_json(paths["build_state"], state)

        if next_index % (batch_size * 5) == 0 or next_index == total_chunks:
            print(f"[RAG] 向量化进度: {next_index}/{total_chunks}")

    part_files = sorted(
        paths["embedding_parts"].glob("part_*.npy"),
        key=lambda p: int(p.stem.split("_")[1]),
    )
    if not part_files:
        raise RuntimeError("未生成任何向量分片文件")

    first = np.load(part_files[0])
    vector_dim = int(first.shape[1])

    merged = np.lib.format.open_memmap(
        str(paths["embeddings"]),
        mode="w+",
        dtype=np.float32,
        shape=(total_chunks, vector_dim),
    )
    for file in part_files:
        stem_parts = file.stem.split("_")
        start = int(stem_parts[1])
        end = int(stem_parts[2])
        merged[start:end] = np.load(file)
    merged.flush()
    del merged

    paths["build_state"].unlink(missing_ok=True)
    shutil.rmtree(paths["embedding_parts"], ignore_errors=True)
    return np.load(paths["embeddings"], mmap_mode="r")


def build_rag(
    data_root: str,
    stock_folder: str,
    model_name: str = "BAAI/bge-small-zh-v1.5",
    chunk_size: int = 700,
    overlap: int = 120,
    ocr_mode: str = "auto",
    ocr_min_chars_per_page: int = 30,
    ocr_min_avg_chars: int = 80,
) -> Dict:
    stock_root = Path(data_root) / stock_folder
    if not stock_root.exists():
        raise FileNotFoundError(f"股票目录不存在: {stock_root}")

    print(f"[RAG] 开始构建: {stock_root}")
    paths = get_rag_paths(stock_root)
    paths["rag_root"].mkdir(parents=True, exist_ok=True)

    old_jsonl = paths["rag_root"] / "chunks.jsonl"
    if old_jsonl.exists():
        old_jsonl.unlink(missing_ok=True)

    doc_count, chunk_count = _build_chunks_db(
        stock_root=stock_root,
        paths=paths,
        chunk_size=chunk_size,
        overlap=overlap,
        ocr_mode=ocr_mode,
        ocr_min_chars_per_page=ocr_min_chars_per_page,
        ocr_min_avg_chars=ocr_min_avg_chars,
    )
    if chunk_count <= 0:
        raise ValueError("未发现可向量化内容，请检查 report/announcement 下是否有 PDF/TXT/MD")

    total_chunks = _count_chunks(paths["chunks_db"])
    print(f"[RAG] 文档数: {doc_count} | 切片数: {total_chunks} | 开始向量化")
    vectors = _build_embeddings_resumable(
        db_path=paths["chunks_db"],
        total_chunks=total_chunks,
        model_name=model_name,
        paths=paths,
        batch_size=32,
    )

    meta = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "stock_folder": stock_folder,
        "model_name": model_name,
        "chunk_size": chunk_size,
        "overlap": overlap,
        "ocr_mode": ocr_mode,
        "ocr_min_chars_per_page": ocr_min_chars_per_page,
        "ocr_min_avg_chars": ocr_min_avg_chars,
        "doc_count": doc_count,
        "chunk_count": int(total_chunks),
        "vector_dim": int(vectors.shape[1]),
        "storage": "sqlite+numpy",
        "files": {
            "chunks_db": str(paths["chunks_db"]),
            "chunks_meta": str(paths["chunks_meta"]),
            "embeddings": str(paths["embeddings"]),
        },
    }
    _write_json(paths["meta"], meta)
    print("[RAG] 构建完成")
    return meta


def cosine_search(query_vec: np.ndarray, doc_vecs: np.ndarray, top_k: int) -> Tuple[np.ndarray, np.ndarray]:
    scores = doc_vecs @ query_vec
    k = min(top_k, len(scores))
    idx = np.argpartition(-scores, k - 1)[:k]
    idx = idx[np.argsort(-scores[idx])]
    return idx, scores[idx]


def query_rag(
    data_root: str,
    stock_folder: str,
    query: str,
    top_k: int = 5,
    model_name: str = "BAAI/bge-small-zh-v1.5",
) -> List[Dict]:
    stock_root = Path(data_root) / stock_folder
    paths = get_rag_paths(stock_root)
    if not paths["chunks_db"].exists() or not paths["embeddings"].exists():
        raise FileNotFoundError("RAG索引不存在，请先运行 build")

    vectors = np.load(paths["embeddings"], mmap_mode="r")
    model = _load_embedding_model(model_name)
    query_vec = _encode_texts(model, [query])[0]

    idx, scores = cosine_search(query_vec, vectors, top_k=top_k)
    chunk_ids = [int(i) + 1 for i in idx.tolist()]
    rows_map = _fetch_chunks_by_ids(paths["chunks_db"], chunk_ids)

    hits = []
    for rank, (i, score) in enumerate(zip(idx.tolist(), scores.tolist()), start=1):
        chunk_id = int(i) + 1
        row = rows_map.get(chunk_id)
        if not row:
            continue
        hits.append(
            {
                "rank": rank,
                "score": float(score),
                "doc_type": row["doc_type"],
                "source_path": row["source_path"],
                "chunk_id": f"{row['doc_id']}#{row['chunk_index']}",
                "text": row["text"],
            }
        )
    return hits
