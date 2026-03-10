import os
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from cninfo_crawler import run_crawl, run_pipeline, run_rag_build, run_rag_query, setup_logger


APP_NAME = "stock-rag-api"
APP_VERSION = "0.1.0"

logger = setup_logger()
app = FastAPI(title=APP_NAME, version=APP_VERSION)


def verify_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    server_api_key = os.getenv("API_KEY", "").strip()
    if not server_api_key:
        return
    if not x_api_key or x_api_key.strip() != server_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


class BaseStockRequest(BaseModel):
    stock_code: str = Field(..., description="六位股票代码，例如 600536")
    stock_name: str = Field(..., description="股票简称，例如 中国软件")
    data_root: str = Field(default="data", description="数据根目录")


class CrawlRequest(BaseStockRequest):
    days: int = Field(default=365, ge=1, le=3650)


class RagBuildRequest(BaseStockRequest):
    stock_folder: str = Field(default="")
    model: str = Field(default="BAAI/bge-small-zh-v1.5")
    chunk_size: int = Field(default=700, ge=100, le=5000)
    overlap: int = Field(default=120, ge=0, le=2000)
    ocr: str = Field(default="auto", pattern="^(auto|on|off)$")
    ocr_min_chars_page: int = Field(default=30, ge=1, le=5000)
    ocr_min_avg_chars: int = Field(default=80, ge=1, le=5000)


class RagQueryRequest(BaseStockRequest):
    stock_folder: str = Field(default="")
    q: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=30)
    model: str = Field(default="BAAI/bge-small-zh-v1.5")


class PipelineRequest(BaseStockRequest):
    days: int = Field(default=365, ge=1, le=3650)
    stock_folder: str = Field(default="")
    model: str = Field(default="BAAI/bge-small-zh-v1.5")
    chunk_size: int = Field(default=700, ge=100, le=5000)
    overlap: int = Field(default=120, ge=0, le=2000)
    ocr: str = Field(default="auto", pattern="^(auto|on|off)$")
    ocr_min_chars_page: int = Field(default=30, ge=1, le=5000)
    ocr_min_avg_chars: int = Field(default=80, ge=1, le=5000)


def _ns(payload: Dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(**payload)


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"status": "ok", "service": APP_NAME, "version": APP_VERSION}


@app.post("/crawl", dependencies=[Depends(verify_api_key)])
def crawl_api(body: CrawlRequest) -> Dict[str, Any]:
    try:
        result = run_crawl(_ns(body.model_dump()), logger)
        return {"ok": True, "result": result}
    except Exception as ex:
        logger.exception("/crawl failed")
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/rag/build", dependencies=[Depends(verify_api_key)])
def rag_build_api(body: RagBuildRequest) -> Dict[str, Any]:
    try:
        result = run_rag_build(_ns(body.model_dump()), logger)
        return {"ok": True, "result": result}
    except Exception as ex:
        logger.exception("/rag/build failed")
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/rag/query", dependencies=[Depends(verify_api_key)])
def rag_query_api(body: RagQueryRequest) -> Dict[str, Any]:
    try:
        result: List[Dict[str, Any]] = run_rag_query(_ns(body.model_dump()), logger)
        return {"ok": True, "result": result}
    except Exception as ex:
        logger.exception("/rag/query failed")
        raise HTTPException(status_code=500, detail=str(ex))


@app.post("/pipeline", dependencies=[Depends(verify_api_key)])
def pipeline_api(body: PipelineRequest) -> Dict[str, Any]:
    try:
        result = run_pipeline(_ns(body.model_dump()), logger)
        return {"ok": True, "result": result}
    except Exception as ex:
        logger.exception("/pipeline failed")
        raise HTTPException(status_code=500, detail=str(ex))
