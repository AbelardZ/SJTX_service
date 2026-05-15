# -*- coding: utf-8 -*-
"""
核心分类模块（BERT 模型版）
================================
功能目标：
1. 使用预训练的 BERT 模型进行新闻分类。
2. 保持与旧版规则分类器的基本接口兼容性。

模型路径：项目根目录/bert_model_output
"""
from __future__ import annotations
from typing import Dict, List, Tuple, Any
import logging
from monitor_module.news_monitor.classifier_core.classifiers.ml.bert_classifier import BertClassifier

logger = logging.getLogger(__name__)

class Classifier:
    """新闻分类器（BERT 模型版）"""

    def __init__(self):
        # 初始化 BERT 模型
        # 注意：此处假定 BertClassifier 内部已处理好多例/单例加载问题
        self.model = BertClassifier()
        # 兼容属性
        self.labels = list(self.model.id2label.values())

    def classify_multi(self, title: str, content: str) -> Tuple[List[str], Dict[str, float], str]:
        """
        兼容接口：BERT 模型预测。
        
        返回：
            labels: List[str]  命中标签列表 (目前仅 Top-1)
            scores: Dict[str, float]  置信度
            primary: str  主标签
        """
        full_text = f"{title or ''} {content or ''}".strip()
        if not full_text:
            return ["其他"], {"其他": 0.0}, "其他"

        try:
            label, confidence = self.model.predict(full_text)
            
            # 构造兼容旧接口的返回值
            labels = [label]
            scores = {label: float(confidence)}
            primary = label
            return labels, scores, primary
        except Exception as e:
            logger.error(f"Classification error: {e}")
            return ["error"], {"error": 0.0}, "error"

    def classify(self, title: str, content: str) -> str:
        """返回主标签（单标签）。"""
        _, _, primary = self.classify_multi(title, content)
        return primary

# 单例模式
_default_clf: Classifier | None = None

def _get_default() -> Classifier:
    global _default_clf
    if _default_clf is None:
        try:
            _default_clf = Classifier()
        except Exception as e:
            logger.error(f"Failed to initialize BERT Classifier: {e}")
            raise e
    return _default_clf

def classify_multi(title: str, content: str) -> Tuple[List[str], Dict[str, Any], str]:
    return _get_default().classify_multi(title, content)

def classify_single(title: str, content: str) -> str:
    return _get_default().classify(title, content)
