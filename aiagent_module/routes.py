import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Generator, List
from datetime import datetime

from flask import Blueprint, Response, jsonify, render_template, request, send_from_directory

aiagent_bp = Blueprint("aiagent", __name__, url_prefix="/aiagent", template_folder='templates')

_MODULE_DIR = Path(__file__).resolve().parent
BASE_DIR = _MODULE_DIR.parent
LLM_BASE = BASE_DIR / "LLMAgent"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from aiagent_module.LLMAgent.stock_deep_research import StockDeepResearchAgent

SESSIONS: Dict[str, Dict[str, Any]] = {}


def _get_agent() -> StockDeepResearchAgent:
    return StockDeepResearchAgent(
        model=(os.getenv("ARK_MODEL", "doubao-seed-2-0-lite-260215").strip()),
        api_key=(os.getenv("ARK_API_KEY", "").strip()),
        data_root=LLM_BASE / "data",
        prompt_dir=LLM_BASE / "prompt",
        report_dir=LLM_BASE / "reports",
        top_k=6,
        dry_run=False,
    )


def _chunk_text(text: str, chunk_size: int = 120) -> Generator[str, None, None]:
    clean = text or ""
    for i in range(0, len(clean), chunk_size):
        yield clean[i : i + chunk_size]


def _streaming_response(generate: Generator[str, None, None]) -> Response:
    response = Response(generate, mimetype="text/plain; charset=utf-8")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response


@aiagent_bp.route("/stock/history", methods=["GET"])
def list_history():
    reports_dir = LLM_BASE / "reports"
    if not reports_dir.exists():
        return jsonify({"ok": True, "reports": []})

    files = []
    for f in reports_dir.iterdir():
        if f.is_file() and f.name.endswith(".md"):
            parts = f.stem.split('_')

            display_name = f.name
            code = ""
            time_str = ""

            try:
                if len(parts) >= 4 and parts[0] == "Stock" and parts[1] == "Deep":
                    code = parts[3]
                    name = parts[4]
                    if len(parts) >= 6:
                        t_str = parts[5]
                        if len(parts) > 6:
                            t_str += " " + parts[6]

                        dt = datetime.strptime(t_str, "%Y%m%d %H%M%S") if len(parts) > 6 else datetime.strptime(t_str, "%Y%m%d")
                        time_str = dt.strftime("%Y-%m-%d %H:%M")

                    display_name = name
            except Exception:
                pass

            if not time_str:
                mtime = f.stat().st_mtime
                time_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

            files.append({
                "filename": f.name,
                "name": display_name,
                "code": code,
                "time": time_str,
                "ts": f.stat().st_mtime
            })

    files.sort(key=lambda x: x['ts'], reverse=True)
    return jsonify({"ok": True, "reports": files})


@aiagent_bp.route("/stock/report/<filename>", methods=["GET"])
def get_report(filename):
    reports_dir = LLM_BASE / "reports"
    return send_from_directory(str(reports_dir), filename)


@aiagent_bp.route("/stock", methods=["GET"])
def stock_research_page():
    return render_template("ai_stock.html")


@aiagent_bp.post("/stock/preprocess")
def stock_preprocess_api():
    body = request.get_json(silent=True) or {}
    stock_name = str(body.get("stock_name", "")).strip()
    stock_code = str(body.get("stock_code", "")).strip()
    days = int(body.get("days", 365))

    if not stock_name:
        return jsonify({"ok": False, "error": "请输入股票名称"}), 400

    agent = _get_agent()
    logs: List[str] = []

    def log(msg: str) -> None:
        logs.append(msg)

    try:
        log("开始解析股票标识...")
        resolved_code, resolved_name = agent.resolve_stock_identity(stock_name=stock_name, stock_code=stock_code)
        log(f"股票解析完成：{resolved_name}({resolved_code})")

        use_rag = bool(body.get("use_rag", True))
        log(f"RAG增强检索：{'已启用' if use_rag else '已禁用'}")

        if use_rag:
            log("检查本地向量库/执行抓取...")
            pipeline = agent.ensure_pipeline(resolved_code, resolved_name, days=days)
            if pipeline.get("reason") == "rag_exists":
                log("检测到现有向量库，跳过抓取与向量化")
            else:
                log("已完成抓取与向量化")
        else:
            pipeline = {"skipped": True, "reason": "rag_disabled"}
            log("Skipping RAG pipeline as requested")

        report_path = agent.write_report(
            stock_code=resolved_code,
            stock_name=resolved_name,
            sections=[],
            report_path=None,
            chat_records=None,
        )

        session_id = uuid.uuid4().hex
        SESSIONS[session_id] = {
            "stock_code": resolved_code,
            "stock_name": resolved_name,
            "pipeline": pipeline,
            "use_rag": use_rag,
            "sections": {},
            "chat_records": [],
            "chat_history": [],
            "report_path": report_path,
        }

        return jsonify(
            {
                "ok": True,
                "session_id": session_id,
                "stock_code": resolved_code,
                "stock_name": resolved_name,
                "pipeline": pipeline,
                "logs": logs,
                "report_path": report_path,
            }
        )
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex), "logs": logs}), 500


@aiagent_bp.post("/stock/section/<int:section_index>/stream")
def stock_section_stream_api(section_index: int):
    body = request.get_json(silent=True) or {}
    session_id = str(body.get("session_id", "")).strip()
    state = SESSIONS.get(session_id)
    if not state:
        return jsonify({"ok": False, "error": "会话不存在，请先执行预处理"}), 404

    if section_index not in {2, 3, 4, 5, 6}:
        return jsonify({"ok": False, "error": "模块编号仅支持 2-6"}), 400

    mapped_section = section_index - 1

    def generate() -> Generator[str, None, None]:
        agent = _get_agent()
        stock_code = state["stock_code"]
        stock_name = state["stock_name"]
        use_rag = state.get("use_rag", True)

        try:
            yield (f"[模块{section_index}] 开始执行...\n" + (" " * 2048) + "\n")
            yield f"[系统] 已建立流式连接，RAG已{'启用' if use_rag else '禁用'}...\n"
            pending_result: Dict[str, Any] = {}
            assistant_buffer: List[str] = []
            reasoning_buffer: List[str] = []
            last_flush_length = 0
            for event in agent.stream_section(stock_code=stock_code, stock_name=stock_name, section_index=mapped_section, use_rag=use_rag):
                event_type = event.get("type")
                if event_type == "meta":
                    pending_result = {
                        "index": int(event.get("index", mapped_section)),
                        "prompt_file": str(event.get("prompt_file", "")),
                        "rag_hits": int(event.get("rag_hits", 0)),
                        "rag_sources": list(event.get("rag_sources", [])),
                        "assistant": "",
                        "reasoning": "",
                        "response_id": "",
                    }
                    yield f"[模块{section_index}] RAG命中：{event.get('rag_hits', 0)}\n"
                    yield "[正文开始]\n"
                    continue
                if event_type == "assistant_delta":
                    delta_text = str(event.get("delta", ""))
                    assistant_buffer.append(delta_text)
                    yield delta_text

                    current_len = sum(len(x) for x in assistant_buffer)
                    if pending_result and (current_len - last_flush_length >= 800):
                        pending_result["assistant"] = "".join(assistant_buffer)
                        pending_result["reasoning"] = "".join(reasoning_buffer)
                        state["sections"][str(section_index)] = dict(pending_result)
                        updated_report = agent.write_report(
                            stock_code=stock_code,
                            stock_name=stock_name,
                            sections=list(state["sections"].values()),
                            report_path=Path(state["report_path"]),
                            chat_records=state["chat_records"],
                        )
                        state["report_path"] = updated_report
                        last_flush_length = current_len
                    continue
                if event_type == "progress":
                    stage = str(event.get("stage", "processing"))
                    if stage == "reasoning":
                        yield "\n[系统] 深度思考进行中...\n"
                    elif stage == "retry":
                        attempt = int(event.get("attempt", 0))
                        wait_seconds = int(event.get("wait", 0))
                        error_code = str(event.get("error_code", "")).strip()
                        if error_code:
                            yield (
                                f"\n[系统] 请求限流/波动（code={error_code}），"
                                f"准备第{attempt + 1}次尝试，等待{wait_seconds}s...\n"
                            )
                        else:
                            yield f"\n[系统] 请求限流/波动，准备第{attempt + 1}次尝试，等待{wait_seconds}s...\n"
                    else:
                        yield "\n[系统] 正在处理检索/工具调用...\n"
                    continue
                if event_type == "done":
                    pending_result = {
                        "index": int(event.get("index", mapped_section)),
                        "prompt_file": str(event.get("prompt_file", "")),
                        "rag_hits": int(event.get("rag_hits", 0)),
                        "rag_sources": list(event.get("rag_sources", [])),
                        "assistant": str(event.get("assistant", "")),
                        "reasoning": str(event.get("reasoning", "")),
                        "response_id": str(event.get("response_id", "")),
                    }
                    reasoning_buffer = [pending_result["reasoning"]]

            if pending_result:
                state["sections"][str(section_index)] = pending_result
                updated_report = agent.write_report(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    sections=list(state["sections"].values()),
                    report_path=Path(state["report_path"]),
                    chat_records=state["chat_records"],
                )
                state["report_path"] = updated_report
                yield "\n[正文结束]\n"
                yield f"[模块{section_index}] 已写入报告：{updated_report}\n"
        except Exception as ex:
            yield f"\n[错误] {str(ex)}\n"

    return _streaming_response(generate())


@aiagent_bp.post("/stock/chat/stream")
def stock_chat_stream_api():
    body = request.get_json(silent=True) or {}
    session_id = str(body.get("session_id", "")).strip()
    message = str(body.get("message", "")).strip()
    state = SESSIONS.get(session_id)
    if not state:
        return jsonify({"ok": False, "error": "会话不存在，请先执行预处理"}), 404
    if not message:
        return jsonify({"ok": False, "error": "请输入问题"}), 400

    def generate() -> Generator[str, None, None]:
        agent = _get_agent()
        stock_code = state["stock_code"]
        stock_name = state["stock_name"]

        try:
            yield ("[对话] AI正在思考...\n" + (" " * 2048) + "\n")
            chat = agent.call_chat(
                stock_code=stock_code,
                stock_name=stock_name,
                user_message=message,
                history=state.get("chat_history", []),
            )

            assistant = chat.get("assistant", "")
            reasoning = chat.get("reasoning", "")

            state.setdefault("chat_history", []).append({"role": "user", "content": message})
            state.setdefault("chat_history", []).append({"role": "assistant", "content": assistant})
            state.setdefault("chat_records", []).append(
                {"user": message, "assistant": assistant, "reasoning": reasoning}
            )

            updated_report = agent.write_report(
                stock_code=stock_code,
                stock_name=stock_name,
                sections=list(state["sections"].values()),
                report_path=Path(state["report_path"]),
                chat_records=state["chat_records"],
            )
            state["report_path"] = updated_report

            for chunk in _chunk_text(assistant):
                yield chunk
            yield f"\n[对话] 已写入报告：{updated_report}\n"
        except Exception as ex:
            yield f"\n[错误] {str(ex)}\n"

    return _streaming_response(generate())
