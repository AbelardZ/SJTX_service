"""
示例入口（仅演示）
===================
用途：
- 演示文本清洗 + 规则分类的最小流程。
- 不包含抓取与入库，仅打印分类结果，便于快速自测与调试。

如何运行：
    python -m src.app
或在 VS Code 中直接运行当前文件。
"""
from monitor_module.news_monitor.classifier_core.text_cleaning import clean_text
from monitor_module.news_monitor.classifier_core.classifier import Classifier
from monitor_module.news_monitor.classifier_core.logger import setup_logger

def main():
    # Set up logging
    logger = setup_logger()

    # 演示样例：可以替换为你从 news_monitor 读取的实时文本
    samples = [
        {"title": "【公司X签订5亿元订单】", "content": "公司X公告称与某大型客户签订5亿元长期供货订单。"},
        {"title": "【国务院发布新能源补贴政策】", "content": "国务院发布最新新能源产业补贴指导意见，强调技术创新。"},
        {"title": "【北向资金大幅流入】", "content": "今日北向资金净流入超40亿元，科技板块走强。"},
    ]

    clf = Classifier()
    for it in samples:
        title, content = it["title"], clean_text(it["content"])
        labels, scores, primary = clf.classify_multi(title, content)
    # 打印分类结果：主标签、多标签、各标签命中计数
    logger.info(f"标题: {title} | 主标签: {primary} | 多标签: {labels} | 分数: {scores}")

if __name__ == "__main__":
    main()