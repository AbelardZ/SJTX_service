"""NewsAgent LLM configuration and helpers."""

from __future__ import annotations

import os

from openai import OpenAI

from monitor_module.news_monitor.newsagent.topics import BASE_SYSTEM_PROMPT, build_system_prompt, build_user_prompt

API_KEY = os.getenv("NEWS_AGENT_API_KEY", "sk-mdfigyqgucbkkhgptiwhzwqfstrqjjtqifikogtvjzvyavlm")
MODEL_NAME = "deepseek-ai/DeepSeek-V3.2"
BASE_URL = "https://api.siliconflow.cn/v1"

SYSTEM_PROMPT = BASE_SYSTEM_PROMPT
System_Prompt = SYSTEM_PROMPT


def build_cluster_system_prompt(cluster_name: str) -> str:
    return build_system_prompt(cluster_name)


def build_cluster_user_prompt(cluster_name: str, period_name: str, date, content: str) -> str:
    return build_user_prompt(cluster_name, period_name, date, content)


def build_client() -> OpenAI:
    if not API_KEY:
        raise RuntimeError("NEWS_AGENT_API_KEY is not set")
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)
