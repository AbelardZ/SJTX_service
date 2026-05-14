import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

try:
    from .cninfo_announcements_crawler import crawl_announcements_last_year
    from .cninfo_reports_crawler import crawl_reports_since_listing
    from .local_rag import build_rag, query_rag
except ImportError:
    from aiagent_module.LLMAgent.cninfo_announcements_crawler import crawl_announcements_last_year
    from aiagent_module.LLMAgent.cninfo_reports_crawler import crawl_reports_since_listing
    from aiagent_module.LLMAgent.local_rag import build_rag, query_rag


def setup_logger(log_root: str = "logs") -> logging.Logger:
    Path(log_root).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_root) / f"pipeline_{datetime.now().strftime('%Y%m%d')}.log"

    logger = logging.getLogger("stock_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info("日志初始化完成: %s", log_file)
    return logger


def get_stock_folder(stock_code: str, stock_name: str) -> str:
    return f"{stock_code}{stock_name}"


def run_crawl(args, logger: logging.Logger) -> dict:
    logger.info("开始执行数据同步: stock=%s %s", args.stock_code, args.stock_name)

    report_result = crawl_reports_since_listing(
        stock_code=args.stock_code,
        stock_name=args.stock_name,
        output_root=args.data_root,
    )
    logger.info("财报同步完成: %s", report_result)

    ann_result = crawl_announcements_last_year(
        stock_code=args.stock_code,
        stock_name=args.stock_name,
        days=args.days,
        output_root=args.data_root,
    )
    logger.info("公告同步完成: %s", ann_result)

    result = {"reports": report_result, "announcements": ann_result}
    logger.info("数据同步结束")
    return result


def run_rag_build(args, logger: logging.Logger) -> dict:
    stock_folder = args.stock_folder or get_stock_folder(args.stock_code, args.stock_name)
    logger.info("开始构建RAG索引: folder=%s", stock_folder)
    result = build_rag(
        data_root=args.data_root,
        stock_folder=stock_folder,
        model_name=args.model,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        ocr_mode=args.ocr,
        ocr_min_chars_per_page=args.ocr_min_chars_page,
        ocr_min_avg_chars=args.ocr_min_avg_chars,
    )
    logger.info("RAG索引构建完成: chunk_count=%s, doc_count=%s", result.get("chunk_count"), result.get("doc_count"))
    return result


def run_rag_query(args, logger: logging.Logger) -> list:
    stock_folder = args.stock_folder or get_stock_folder(args.stock_code, args.stock_name)
    logger.info("开始RAG检索: folder=%s, top_k=%s", stock_folder, args.top_k)
    result = query_rag(
        data_root=args.data_root,
        stock_folder=stock_folder,
        query=args.q,
        top_k=args.top_k,
        model_name=args.model,
    )
    logger.info("RAG检索完成: hit_count=%s", len(result))
    return result


def run_pipeline(args, logger: logging.Logger) -> dict:
    logger.info("开始执行一键全流程（抓取 + 向量化）")
    crawl_result = run_crawl(args, logger)
    rag_result = run_rag_build(args, logger)
    output = {"crawl": crawl_result, "rag_build": rag_result}
    logger.info("一键全流程执行完成")
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一接口：巨潮同步 + 本地RAG")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--stock-code", required=True, help="六位股票代码，例如 600536")
    common.add_argument("--stock-name", required=True, help="股票简称，例如 中国软件")
    common.add_argument("--data-root", default="data", help="数据根目录，默认 data")

    crawl = sub.add_parser("crawl", parents=[common], help="同步财报与公告")
    crawl.add_argument("--days", type=int, default=365, help="公告窗口天数，默认 365")

    rag_build = sub.add_parser("rag-build", parents=[common], help="构建RAG索引")
    rag_build.add_argument("--stock-folder", default="", help="可选，默认由代码+名称自动拼接")
    rag_build.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    rag_build.add_argument("--chunk-size", type=int, default=700)
    rag_build.add_argument("--overlap", type=int, default=120)
    rag_build.add_argument("--ocr", default="auto", choices=["auto", "on", "off"])
    rag_build.add_argument("--ocr-min-chars-page", type=int, default=30)
    rag_build.add_argument("--ocr-min-avg-chars", type=int, default=80)

    rag_query = sub.add_parser("rag-query", parents=[common], help="查询RAG索引")
    rag_query.add_argument("--stock-folder", default="", help="可选，默认由代码+名称自动拼接")
    rag_query.add_argument("--q", required=True, help="检索问题")
    rag_query.add_argument("--top-k", type=int, default=5)
    rag_query.add_argument("--model", default="BAAI/bge-small-zh-v1.5")

    pipeline = sub.add_parser("pipeline", parents=[common], help="一键执行 crawl + rag-build")
    pipeline.add_argument("--days", type=int, default=365)
    pipeline.add_argument("--stock-folder", default="", help="可选，默认由代码+名称自动拼接")
    pipeline.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    pipeline.add_argument("--chunk-size", type=int, default=700)
    pipeline.add_argument("--overlap", type=int, default=120)
    pipeline.add_argument("--ocr", default="auto", choices=["auto", "on", "off"])
    pipeline.add_argument("--ocr-min-chars-page", type=int, default=30)
    pipeline.add_argument("--ocr-min-avg-chars", type=int, default=80)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logger = setup_logger()

    if args.cmd == "crawl":
        result = run_crawl(args, logger)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.cmd == "rag-build":
        result = run_rag_build(args, logger)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.cmd == "rag-query":
        result = run_rag_query(args, logger)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    result = run_pipeline(args, logger)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
