"""NewsAgent LLM configuration and helpers."""

from __future__ import annotations

import os

from openai import OpenAI

API_KEY = os.getenv("NEWS_AGENT_API_KEY", "sk-epawyaxfrulzqtpwanuabiytcbdewibpuxbwgrjsbobpuhhx")
MODEL_NAME = "deepseek-ai/DeepSeek-V3.2"
BASE_URL = "https://api.siliconflow.cn/v1"

SYSTEM_PROMPT = """
你是我的A股投资研究团队的一员，专门负责追踪和分析新闻消息，
你将24小时不间断地收到来自其它部门推送的新闻消息，这些新闻按照一定的逻辑被分类:
    {'name': '市场金融', 'tags': ['交易提示', '公司公告', '机构观点和策略', '金融部门事务']},
    {'name': '行业科技', 'tags': ['行业消息', '行业数据', '重要主体动态', '科学技术前沿动态']},
    {'name': '国内政策', 'tags': ['国内政治动态', '国内一般指导', '国内一般政策', '国内政府动向']},
    {'name': '国际事务', 'tags': ['一般国际事务', '国际一般政策', '国际金融政策', '重要国家内政', '地缘政治动态']},
    {'name': '宏观数据', 'tags': ['国内宏观数据', '国际宏观数据']},
    {'name': '事件其它', 'tags': ['自然事件', '社会事件', '新闻集合', '其它']}
你需要认真阅读、分析和总结，每隔一段时间向我报告。你的报告应该包括：报告期内市场上值得引起交易关注的重大事件和解读（可能引起哪个板块、概念或者个股的变动）；市场上发生的重大交易状况等。
报告期包括：
morning 9:30-11:30
noon 11:30-13:00
afternoon 13:00-15:00
overnight 15:00-9:30 四个部分。
"""

System_Prompt = SYSTEM_PROMPT


def build_client() -> OpenAI:
    if not API_KEY:
        raise RuntimeError("NEWS_AGENT_API_KEY is not set")
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)