import argparse
import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Generator, List, Optional, Tuple

import requests

try:
    from .cninfo_crawler import run_pipeline, run_rag_query, setup_logger
except ImportError:
    from aiagent_module.LLMAgent.cninfo_crawler import run_pipeline, run_rag_query, setup_logger


ARK_RESPONSES_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
CNINFO_TOP_SEARCH_URL = "https://www.cninfo.com.cn/new/information/topSearch/query"
DEFAULT_ARK_API_KEY = "887e6232-8ea0-4d68-89ad-6dc1826ec0c3"

_ARK_RATE_LOCK = threading.Lock()
_ARK_LAST_CALL_TS = 0.0
_ARK_MIN_INTERVAL_SECONDS = 12.0
_ARK_MAX_STREAM_ATTEMPTS = 6

if not os.getenv("ARK_API_KEY", "").strip():
    os.environ["ARK_API_KEY"] = DEFAULT_ARK_API_KEY


class StockDeepResearchAgent:
    def __init__(
        self,
        model: str,
        api_key: str,
        data_root: Path,
        prompt_dir: Path,
        report_dir: Path,
        top_k: int = 6,
        timeout: int = 180,
        dry_run: bool = False,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.data_root = data_root
        self.prompt_dir = prompt_dir
        self.report_dir = report_dir
        self.fallback_report_dir = Path("/tmp/sjtx_reports")
        self.top_k = top_k
        self.timeout = timeout
        self.dry_run = dry_run
        try:
            self.logger = setup_logger(str(Path(__file__).resolve().parent / "logs"))
        except Exception:
            self.logger = logging.getLogger("stock_deep_research")
            self.logger.setLevel(logging.INFO)
            self.logger.handlers.clear()
            stream = logging.StreamHandler()
            stream.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            self.logger.addHandler(stream)

        self.modules = {
            1: "01_总体商业基本面分析.md",
            2: "02_大级别自上而下分析.md",
            3: "03_小级别自上而下分析.md",
            4: "04_资金面分析.md",
            5: "05_基于不同交易策略的投资建议.md",
        }

    def _read_prompt(self, filename: str) -> str:
        path = self.prompt_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Prompt 文件不存在: {path}")
        return path.read_text(encoding="utf-8")

    def _extract_code_from_input(self, stock_name_or_full: str) -> Tuple[Optional[str], str]:
        text = stock_name_or_full.strip()
        match = re.search(r"(\d{6})", text)
        code = match.group(1) if match else None
        normalized = re.sub(r"[（(]\d{6}[）)]", "", text).strip()
        return code, normalized

    def _resolve_from_local_folder(self, stock_name: str) -> Optional[Tuple[str, str]]:
        if not self.data_root.exists():
            return None

        exact_hits: List[Tuple[str, str]] = []
        for folder in self.data_root.iterdir():
            if not folder.is_dir():
                continue
            m = re.match(r"^(\d{6})(.+)$", folder.name)
            if not m:
                continue
            code, name = m.group(1), m.group(2)
            if name == stock_name:
                exact_hits.append((code, name))

        if len(exact_hits) == 1:
            return exact_hits[0]
        return None

    def _resolve_from_cninfo(self, query: str) -> Optional[Tuple[str, str]]:
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

        response = session.post(
            CNINFO_TOP_SEARCH_URL,
            data={"keyWord": query, "maxNum": 20, "plate": ""},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list) or not data:
            return None

        first = data[0]
        code = str(first.get("code", "")).strip()
        name = str(first.get("zwjc", "")).strip() or str(first.get("orgName", "")).strip() or query
        if not code:
            return None
        return code, name

    def resolve_stock_identity(self, stock_name: str, stock_code: str = "") -> Tuple[str, str]:
        provided_code = stock_code.strip()
        parsed_code, parsed_name = self._extract_code_from_input(stock_name)

        if provided_code:
            return provided_code, parsed_name
        if parsed_code:
            return parsed_code, parsed_name

        local_hit = self._resolve_from_local_folder(parsed_name)
        if local_hit:
            return local_hit

        remote_hit = self._resolve_from_cninfo(parsed_name)
        if remote_hit:
            return remote_hit

        raise ValueError(
            f"无法仅通过股票名称解析代码: {parsed_name}。请补充 --stock-code 参数，例如 600536。"
        )

    def _stock_folder(self, stock_code: str, stock_name: str) -> str:
        return f"{stock_code}{stock_name}"

    def _rag_exists(self, stock_folder: str) -> bool:
        rag_root = self.data_root / stock_folder / "rag"
        required = [
            rag_root / "chunks.db",
            rag_root / "chunks_meta.json",
            rag_root / "meta.json",
        ]
        return all(p.exists() for p in required)

    def ensure_pipeline(self, stock_code: str, stock_name: str, days: int) -> Dict[str, Any]:
        stock_folder = self._stock_folder(stock_code, stock_name)
        if self._rag_exists(stock_folder):
            self.logger.info("检测到现有向量库，跳过抓取与向量化: %s", stock_folder)
            return {"skipped": True, "reason": "rag_exists", "stock_folder": stock_folder}

        if self.dry_run:
            self.logger.info("dry-run 模式：跳过抓取与向量化")
            return {"skipped": True, "reason": "dry_run", "stock_folder": stock_folder}

        args = SimpleNamespace(
            stock_code=stock_code,
            stock_name=stock_name,
            data_root=str(self.data_root),
            days=days,
            stock_folder=stock_folder,
            model="BAAI/bge-small-zh-v1.5",
            chunk_size=700,
            overlap=120,
            ocr="auto",
            ocr_min_chars_page=30,
            ocr_min_avg_chars=80,
        )
        result = run_pipeline(args, self.logger)
        result["stock_folder"] = stock_folder
        return result

    def query_rag(self, stock_code: str, stock_name: str, question: str) -> List[Dict[str, Any]]:
        if self.dry_run:
            return [
                {
                    "source": "dry_run/mock_source",
                    "text": f"模拟RAG命中：{stock_name}({stock_code}) 对于问题“{question}”的上下文摘要。",
                    "score": 0.99,
                }
            ]

        args = SimpleNamespace(
            stock_code=stock_code,
            stock_name=stock_name,
            stock_folder="",
            data_root=str(self.data_root),
            q=question,
            top_k=self.top_k,
            model="BAAI/bge-small-zh-v1.5",
        )
        return run_rag_query(args, self.logger)

    def _parse_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        assistant_texts: List[str] = []
        reasoning_texts: List[str] = []

        if isinstance(data.get("output_text"), str) and data.get("output_text").strip():
            assistant_texts.append(data["output_text"].strip())

        for item in data.get("output", []) or []:
            item_type = item.get("type")
            if item_type == "reasoning":
                for part in item.get("summary", []) or []:
                    if part.get("type") == "summary_text":
                        summary_text = (part.get("text") or "").strip()
                        if summary_text:
                            reasoning_texts.append(summary_text)
                continue

            if item_type != "message":
                continue

            for part in item.get("content", []) or []:
                ptype = part.get("type", "")
                if ptype in {"output_text", "text"}:
                    text = (part.get("text") or "").strip()
                    if text:
                        assistant_texts.append(text)

        assistant = "\n".join(assistant_texts).strip()
        reasoning = "\n".join(reasoning_texts).strip()

        if not assistant:
            raise RuntimeError(f"Doubao 未返回正文输出: {json.dumps(data, ensure_ascii=False)[:1200]}")

        return {
            "assistant": assistant,
            "reasoning": reasoning,
            "response_id": data.get("id", ""),
        }

    def _extract_api_error(self, response: requests.Response) -> str:
        status_code = response.status_code
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("x-tt-logid")
            or response.headers.get("X-Tt-Logid")
            or ""
        )

        error_code = ""
        error_message = ""
        body_preview = ""
        try:
            payload = response.json()
            error_obj = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error_obj, dict):
                error_code = str(error_obj.get("code", "") or "")
                error_message = str(error_obj.get("message", "") or "")
            if not error_message:
                error_message = str(payload.get("message", "") or "") if isinstance(payload, dict) else ""
            body_preview = json.dumps(payload, ensure_ascii=False)[:500]
        except Exception:
            body_preview = (response.text or "")[:500]

        parts = [f"HTTP {status_code}"]
        if error_code:
            parts.append(f"code={error_code}")
        if request_id:
            parts.append(f"request_id={request_id}")
        if error_message:
            parts.append(f"message={error_message}")
        elif body_preview:
            parts.append(f"body={body_preview}")
        return " | ".join(parts)

    def _call_doubao(self, system_prompt: str, user_prompt: str) -> Dict[str, str]:
        if self.dry_run:
            return {
                "assistant": "【dry-run】该段为模拟输出，用于验证端到端流程。",
                "reasoning": "【dry-run】推理过程占位内容。",
                "response_id": "dry-run",
            }

        if not self.api_key:
            raise ValueError("环境变量 ARK_API_KEY 未设置，无法调用 Doubao Pro 2.0")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: Dict[str, Any] = {
            "model": self.model,
            "input": [
                {"type": "message", "role": "system", "content": system_prompt},
                {"type": "message", "role": "user", "content": user_prompt},
            ],
            "tools": [
                {
                    "type": "web_search",
                    "limit": 6,
                    "max_keyword": 2,
                }
            ],
            "tool_choice": "auto",
            "stream": False,
            "max_output_tokens": 5000,
            "thinking": {"type": "enabled"},
            "reasoning": {"effort": "high"},
            "temperature": 0.7,
            "top_p": 0.95,
        }
        response = requests.post(ARK_RESPONSES_URL, headers=headers, json=payload, timeout=self.timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"Doubao 调用失败: {self._extract_api_error(response)}")
        data = response.json()
        return self._parse_response(data)

    def call_chat(self, stock_code: str, stock_name: str, user_message: str, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, str]:
        if self.dry_run:
            return {
                "assistant": f"【dry-run】收到提问：{user_message}",
                "reasoning": "【dry-run】对话推理占位",
                "response_id": "dry-run-chat",
            }

        if not self.api_key:
            raise ValueError("环境变量 ARK_API_KEY 未设置，无法调用 Doubao Pro 2.0")

        role_prompt = self._read_prompt("00_角色设定.md")
        rules_prompt = self._read_prompt("06_补充强调与技术分析规范.md")
        system_prompt = (
            f"{role_prompt}\n\n{rules_prompt}\n\n"
            f"你正在继续回答 {stock_name}({stock_code}) 的个股深度投研问题。"
            "请输出可执行结论，必要时使用联网搜索补充最新事件。"
        )

        input_messages: List[Dict[str, Any]] = [{"type": "message", "role": "system", "content": system_prompt}]
        for item in (history or [])[-12:]:
            role = item.get("role", "user")
            content = (item.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                input_messages.append({"type": "message", "role": role, "content": content})
        input_messages.append({"type": "message", "role": "user", "content": user_message})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "input": input_messages,
            "tools": [{"type": "web_search", "limit": 6, "max_keyword": 2}],
            "tool_choice": "auto",
            "stream": False,
            "max_output_tokens": 4000,
            "thinking": {"type": "enabled"},
            "reasoning": {"effort": "high"},
            "temperature": 0.7,
            "top_p": 0.95,
        }

        response = requests.post(ARK_RESPONSES_URL, headers=headers, json=payload, timeout=self.timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"Doubao 对话失败: {self._extract_api_error(response)}")
        return self._parse_response(response.json())

    def generate_section(self, stock_code: str, stock_name: str, section_index: int, use_rag: bool = True) -> Dict[str, Any]:
        if section_index not in self.modules:
            raise ValueError(f"不支持的模块编号: {section_index}")

        prompt_file = self.modules[section_index]
        section_prompt = self._read_prompt(prompt_file)
        question = f"{stock_name}({stock_code}) 第{section_index}部分深度分析"
        
        rag_chunks = []
        if use_rag:
            rag_chunks = self.query_rag(stock_code, stock_name, question)
            
        system_prompt, user_prompt = self._build_prompts(
            stock_code=stock_code,
            stock_name=stock_name,
            section_prompt=section_prompt,
            rag_chunks=rag_chunks,
        )
        llm = self._call_doubao(system_prompt, user_prompt)

        return {
            "index": section_index,
            "prompt_file": prompt_file,
            "rag_hits": len(rag_chunks),
            "rag_sources": [chunk.get("source", "未知来源") for chunk in rag_chunks],
            "assistant": llm["assistant"],
            "reasoning": llm.get("reasoning", ""),
            "response_id": llm.get("response_id", ""),
        }

    def stream_section(self, stock_code: str, stock_name: str, section_index: int, use_rag: bool = True) -> Generator[Dict[str, Any], None, None]:
        if section_index not in self.modules:
            raise ValueError(f"不支持的模块编号: {section_index}")

        prompt_file = self.modules[section_index]
        section_prompt = self._read_prompt(prompt_file)
        question = f"{stock_name}({stock_code}) 第{section_index}部分深度分析"
        
        rag_chunks = []
        if use_rag:
            rag_chunks = self.query_rag(stock_code, stock_name, question)
            
        rag_sources = [chunk.get("source", "未知来源") for chunk in rag_chunks]
        system_prompt, user_prompt = self._build_prompts(
            stock_code=stock_code,
            stock_name=stock_name,
            section_prompt=section_prompt,
            rag_chunks=rag_chunks,
        )

        yield {
            "type": "meta",
            "index": section_index,
            "prompt_file": prompt_file,
            "rag_hits": len(rag_chunks),
            "rag_sources": rag_sources,
        }

        if self.dry_run:
            text = "【dry-run】该段为模拟输出，用于验证端到端流程。"
            for ch in text:
                yield {"type": "assistant_delta", "delta": ch}
            yield {
                "type": "done",
                "index": section_index,
                "prompt_file": prompt_file,
                "rag_hits": len(rag_chunks),
                "rag_sources": rag_sources,
                "assistant": text,
                "reasoning": "【dry-run】推理过程占位内容。",
                "response_id": "dry-run",
            }
            return

        if not self.api_key:
            raise ValueError("环境变量 ARK_API_KEY 未设置，无法调用 Doubao Pro 2.0")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "input": [
                {"type": "message", "role": "system", "content": system_prompt},
                {"type": "message", "role": "user", "content": user_prompt},
            ],
            "tools": [{"type": "web_search", "limit": 5, "max_keyword": 2}],
            "tool_choice": "auto",
            "stream": True,
            "max_output_tokens": 5000,
            "thinking": {"type": "enabled"},
            "reasoning": {"effort": "high"},
            "temperature": 0.7,
            "top_p": 0.95,
        }

        response = None
        max_attempts = _ARK_MAX_STREAM_ATTEMPTS
        for attempt in range(1, max_attempts + 1):
            try:
                global _ARK_LAST_CALL_TS
                with _ARK_RATE_LOCK:
                    now = time.time()
                    throttle_wait = _ARK_MIN_INTERVAL_SECONDS - (now - _ARK_LAST_CALL_TS)
                    if throttle_wait > 0:
                        yield {
                            "type": "progress",
                            "stage": "throttle",
                            "attempt": attempt,
                            "wait": round(throttle_wait, 1),
                        }
                        time.sleep(throttle_wait)
                    _ARK_LAST_CALL_TS = time.time()

                response = requests.post(
                    ARK_RESPONSES_URL,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                    stream=True,
                )

                if response.status_code == 429 and attempt < max_attempts:
                    retry_after = response.headers.get("Retry-After", "")
                    error_code = ""
                    error_message = ""
                    try:
                        error_obj = (response.json() or {}).get("error", {})
                        if isinstance(error_obj, dict):
                            error_code = str(error_obj.get("code", "") or "")
                            error_message = str(error_obj.get("message", "") or "")
                    except Exception:
                        pass
                    wait_seconds = 0.0
                    try:
                        wait_seconds = float(retry_after) if retry_after else 0.0
                    except Exception:
                        wait_seconds = 0.0
                    exp_backoff = min(120.0, 6.0 * (2 ** (attempt - 1)))
                    jitter = random.uniform(0.8, 4.0)
                    wait_seconds = max(wait_seconds, exp_backoff + jitter)
                    response.close()
                    yield {
                        "type": "progress",
                        "stage": "retry",
                        "reason": "rate_limit",
                        "error_code": error_code,
                        "error_message": error_message,
                        "attempt": attempt,
                        "wait": round(wait_seconds, 1),
                    }
                    time.sleep(wait_seconds)
                    continue

                if response.status_code >= 400:
                    raise RuntimeError(f"Doubao 流式调用失败: {self._extract_api_error(response)}")
                break
            except requests.RequestException:
                if attempt >= max_attempts:
                    raise
                exp_backoff = min(60.0, 3.0 * (2 ** (attempt - 1)))
                jitter = random.uniform(0.3, 2.0)
                wait_seconds = exp_backoff + jitter
                yield {
                    "type": "progress",
                    "stage": "retry",
                    "reason": "network_or_http",
                    "attempt": attempt,
                    "wait": round(wait_seconds, 1),
                }
                time.sleep(wait_seconds)

        if response is None:
            raise RuntimeError("Doubao 请求未成功发起")

        assistant_parts: List[str] = []
        reasoning_parts: List[str] = []
        response_id = ""
        reasoning_event_count = 0

        for raw in response.iter_lines(decode_unicode=False):
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore")
            if not line.startswith("data: "):
                continue

            data_text = line[6:].strip()
            if data_text == "[DONE]":
                break

            try:
                event = json.loads(data_text)
            except Exception:
                continue

            event_type = str(event.get("type", ""))
            if event_type == "response.created":
                response_id = str((event.get("response") or {}).get("id", ""))
                continue

            if event_type == "response.output_text.delta":
                delta = str(event.get("delta", ""))
                if delta:
                    assistant_parts.append(delta)
                    yield {"type": "assistant_delta", "delta": delta}
                continue

            if event_type in {"response.in_progress", "response.output_item.added", "response.output_item.done"}:
                yield {"type": "progress", "stage": "processing"}
                continue

            if event_type == "response.output_text.done" and not assistant_parts:
                done_text = str(event.get("text", ""))
                if done_text:
                    assistant_parts.append(done_text)
                continue

            if event_type == "response.reasoning_summary_text.delta":
                rs_delta = str(event.get("delta", ""))
                if rs_delta:
                    reasoning_parts.append(rs_delta)
                    reasoning_event_count += 1
                    if reasoning_event_count % 40 == 0:
                        yield {"type": "progress", "stage": "reasoning", "count": reasoning_event_count}
                continue

            if event_type == "response.reasoning_summary_text.done" and not reasoning_parts:
                rs_text = str(event.get("text", ""))
                if rs_text:
                    reasoning_parts.append(rs_text)
                continue

            if event_type in {"response.failed", "error"}:
                raise RuntimeError(f"Doubao 流式调用失败: {json.dumps(event, ensure_ascii=False)[:800]}")

        assistant = "".join(assistant_parts).strip()
        if not assistant:
            raise RuntimeError("Doubao 流式未返回正文输出")

        yield {
            "type": "done",
            "index": section_index,
            "prompt_file": prompt_file,
            "rag_hits": len(rag_chunks),
            "rag_sources": rag_sources,
            "assistant": assistant,
            "reasoning": "".join(reasoning_parts).strip(),
            "response_id": response_id,
        }

    def write_report(
        self,
        stock_code: str,
        stock_name: str,
        sections: List[Dict[str, Any]],
        report_path: Optional[Path] = None,
        chat_records: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        if report_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                self.report_dir.mkdir(parents=True, exist_ok=True)
                report_path = self.report_dir / f"Stock_Deep_Research_{stock_code}_{stock_name}_{timestamp}.md"
            except Exception:
                self.fallback_report_dir.mkdir(parents=True, exist_ok=True)
                report_path = self.fallback_report_dir / f"Stock_Deep_Research_{stock_code}_{stock_name}_{timestamp}.md"

        lines: List[str] = []
        lines.append(f"# {stock_name}({stock_code}) 个股深度投研报告")
        lines.append("")
        lines.append(f"- 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- 模型: {self.model}")
        lines.append(f"- 分析方式: 五模块分段独立生成 + RAG检索 + 联网搜索")
        lines.append("")
        lines.append("---")
        lines.append("")

        for section in sorted(sections, key=lambda x: x.get("index", 999)):
            title = str(section.get("prompt_file", "")).replace(".md", "").split("_", 1)[-1]
            lines.append(f"## 第{section.get('index')}部分：{title}")
            lines.append("")
            lines.append(f"- RAG命中数: {section.get('rag_hits', 0)}")
            rag_sources = section.get("rag_sources") or []
            if rag_sources:
                lines.append(f"- RAG来源: {', '.join(rag_sources[:8])}")
            lines.append("")
            lines.append("### 正文输出")
            lines.append("")
            lines.append((section.get("assistant") or "").strip())
            lines.append("")
            lines.append("### 深度思考")
            lines.append("")
            lines.append((section.get("reasoning") or "（无显式思考链返回）").strip())
            lines.append("")
            lines.append("---")
            lines.append("")

        if chat_records:
            lines.append("## 第7部分：继续问答记录")
            lines.append("")
            for idx, item in enumerate(chat_records, start=1):
                lines.append(f"### 对话 {idx}")
                lines.append("")
                lines.append(f"- 用户: {item.get('user', '')}")
                lines.append("")
                lines.append("#### 正文输出")
                lines.append("")
                lines.append((item.get("assistant") or "").strip())
                lines.append("")
                lines.append("#### 深度思考")
                lines.append("")
                lines.append((item.get("reasoning") or "（无显式思考链返回）").strip())
                lines.append("")

        try:
            report_path.write_text("\n".join(lines), encoding="utf-8")
            return str(report_path)
        except PermissionError:
            self.fallback_report_dir.mkdir(parents=True, exist_ok=True)
            fallback_path = self.fallback_report_dir / report_path.name
            fallback_path.write_text("\n".join(lines), encoding="utf-8")
            return str(fallback_path)

    def _build_prompts(self, stock_code: str, stock_name: str, section_prompt: str, rag_chunks: List[Dict[str, Any]]) -> Tuple[str, str]:
        role_prompt = self._read_prompt("00_角色设定.md")
        rules_prompt = self._read_prompt("06_补充强调与技术分析规范.md")

        rag_text = "\n\n".join(
            [
                f"[命中{i+1}] 来源: {chunk.get('source', '未知来源')}\n内容: {chunk.get('text', '')}"
                for i, chunk in enumerate(rag_chunks)
            ]
        )
        if not rag_text:
            rag_text = "未命中有效RAG资料。"

        system_prompt = (
            f"{role_prompt}\n\n{rules_prompt}\n\n"
            f"你正在撰写 {stock_name}({stock_code}) 的个股深度投研报告。"
            "必须综合使用：\n"
            "1) 已提供的RAG资料；\n"
            "2) 联网搜索得到的最新信息。\n"
            "输出需结构化、可执行，并明确不确定性。"
        )

        user_prompt = (
            f"请严格完成以下分析模块任务：\n\n{section_prompt}\n\n"
            f"【RAG参考资料】\n{rag_text}\n\n"
            "要求：\n"
            "- 优先引用RAG命中资料；\n"
            "- 同时使用联网搜索补充最近事件、政策与市场动态；\n"
            "- 给出结论、风险、触发条件、时间窗口与执行建议；\n"
            "- 禁止只给泛化观点。"
        )
        return system_prompt, user_prompt

    def generate_report(self, stock_name: str, stock_code: str = "", days: int = 365) -> Dict[str, Any]:
        resolved_code, resolved_name = self.resolve_stock_identity(stock_name=stock_name, stock_code=stock_code)
        self.logger.info("股票解析成功: %s %s", resolved_code, resolved_name)

        pipeline_result = self.ensure_pipeline(resolved_code, resolved_name, days=days)

        section_outputs: List[Dict[str, Any]] = []
        for idx, prompt_file in self.modules.items():
            section_prompt = self._read_prompt(prompt_file)
            question = f"{resolved_name}({resolved_code}) 第{idx}部分深度分析"
            rag_chunks = self.query_rag(resolved_code, resolved_name, question)
            system_prompt, user_prompt = self._build_prompts(
                stock_code=resolved_code,
                stock_name=resolved_name,
                section_prompt=section_prompt,
                rag_chunks=rag_chunks,
            )
            llm = self._call_doubao(system_prompt, user_prompt)

            section_outputs.append(
                {
                    "index": idx,
                    "prompt_file": prompt_file,
                    "rag_hits": len(rag_chunks),
                    "assistant": llm["assistant"],
                    "reasoning": llm.get("reasoning", ""),
                    "rag_sources": [chunk.get("source", "未知来源") for chunk in rag_chunks],
                }
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.report_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.report_dir / f"Stock_Deep_Research_{resolved_code}_{resolved_name}_{timestamp}.md"

        self.write_report(
            stock_code=resolved_code,
            stock_name=resolved_name,
            sections=section_outputs,
            report_path=report_path,
            chat_records=None,
        )

        return {
            "ok": True,
            "stock_code": resolved_code,
            "stock_name": resolved_name,
            "pipeline": pipeline_result,
            "report_path": str(report_path),
            "sections": [
                {
                    "index": x["index"],
                    "prompt_file": x["prompt_file"],
                    "rag_hits": x["rag_hits"],
                }
                for x in section_outputs
            ],
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="个股深度投研统一脚本（RAG + 联网搜索 + 五模块分段）")
    parser.add_argument("--stock-name", required=True, help="股票名称，支持 中国软件 或 中国软件(600536)")
    parser.add_argument("--stock-code", default="", help="可选，六位代码。若不传将尝试自动解析")
    parser.add_argument("--days", type=int, default=365, help="公告抓取窗口，默认365天")
    parser.add_argument("--top-k", type=int, default=6, help="每模块RAG召回数")
    parser.add_argument("--dry-run", action="store_true", help="可行性测试模式，不触发外部网络调用")
    parser.add_argument("--json", action="store_true", help="以JSON输出结果")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    llm_model = os.getenv("ARK_MODEL", "doubao-seed-2-0-lite-260215").strip()
    llm_api_key = os.getenv("ARK_API_KEY", "").strip()

    base_dir = Path(__file__).resolve().parent
    agent = StockDeepResearchAgent(
        model=llm_model,
        api_key=llm_api_key,
        data_root=base_dir / "data",
        prompt_dir=base_dir / "prompt",
        report_dir=base_dir / "reports",
        top_k=args.top_k,
        dry_run=args.dry_run,
    )

    try:
        result = agent.generate_report(stock_name=args.stock_name, stock_code=args.stock_code, days=args.days)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as ex:
        payload = {"ok": False, "error": str(ex)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
