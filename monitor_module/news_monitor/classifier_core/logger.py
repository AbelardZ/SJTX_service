# -*- coding: utf-8 -*-
"""简易日志模块（中文注释）

提供统一的 Logger 配置，避免在各处重复配置处理器与格式：
- 默认级别 INFO，输出到标准输出；
- 可通过传入 name 区分不同子模块日志；
- 若已存在处理器则不重复添加（避免多重打印）。
"""
from __future__ import annotations
import logging


def setup_logger(name: str = "news_classifier") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    fmt = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger
