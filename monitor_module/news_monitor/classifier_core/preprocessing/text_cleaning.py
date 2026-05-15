from typing import List
import re

def clean_text(text: str) -> str:
    """
    清洗输入文本，去除多余的空格、换行符和特殊字符。
    """
    # 去除HTML标签
    clean = re.compile('<.*?>')
    text = re.sub(clean, '', text)
    
    # 去除特殊字符
    text = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5\s]', '', text)
    
    # 去除多余的空格
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def split_sentences(text: str) -> List[str]:
    """
    将文本按句子分割。
    """
    # 使用句号、问号和感叹号作为分隔符
    sentences = re.split(r'(?<=[。！？])\s*', text)
    return [sentence for sentence in sentences if sentence]

def preprocess_text(text: str) -> List[str]:
    """
    预处理文本，返回清洗后的句子列表。
    """
    cleaned_text = clean_text(text)
    sentences = split_sentences(cleaned_text)
    return sentences