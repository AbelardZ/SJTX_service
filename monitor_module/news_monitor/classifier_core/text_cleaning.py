# -*- coding: utf-8 -*-
"""
文本清洗模块（精简版）
----------------------
提供最基础的文本预处理：
- 去除全角空格/不间断空格、HTML 标签
- 统一空白字符，做 strip 收尾

可扩展：
- 停用词表、分词、拼写纠错、数字标准化、专有名词映射等
"""
from __future__ import annotations
import re

_HTML_TAG = re.compile(r"<.*?>")


def clean_text(text: str) -> str:
    """基础清洗：统一空白、移除 HTML 标签与多余符号。

    说明：尽量保持“无损”原则，不改变文本语义，仅作格式化。
    """
    if not text:
        return ""
    t = text.strip()
    t = t.replace("\u3000", " ").replace("\xa0", " ")
    # 去 HTML 标签
    t = _HTML_TAG.sub("", t)
    # 统一空白
    t = re.sub(r"[\t\r\f]+", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()
