# -*- coding: utf-8 -*-
import torch
import json
import os
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from typing import List, Dict, Tuple, Union

class BertClassifier:
    """
    基于 BERT 的新闻分类器
    模型路径: 默认位于项目根目录下的 bert_model_output
    """
    
    def __init__(self, model_path: str = None):
        # 默认路径
        if model_path is None:
            # 动态计算路径：.../src/classifiers/ml -> .../root
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
            self.model_path = os.path.join(project_root, "bert_model_output")
        else:
            self.model_path = model_path
            
        print(f"Loading BERT model from {self.model_path}...")
        
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_path)
            self.model.eval() # 设置为评估模式
            
            # 加载 label_map (虽然模型config里有id2label，但读取json可以确保一致性)
            label_map_path = os.path.join(self.model_path, "label_map.json")
            if os.path.exists(label_map_path):
                with open(label_map_path, "r", encoding="utf-8") as f:
                    self.label_map = json.load(f)
                    # 反转映射: id -> label
                    self.id2label = {v: k for k, v in self.label_map.items()}
            else:
                # Fallback to model config
                self.id2label = self.model.config.id2label
                
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.model.to(self.device)
            print(f"Model loaded successfully on {self.device}")
            
        except Exception as e:
            print(f"Error loading model: {e}")
            raise e

    def predict(self, text: str) -> Tuple[str, float]:
        """
        单条文本预测
        返回: (标签, 置信度)
        """
        if not text:
            return "其他", 0.0

        inputs = self.tokenizer(
            text, 
            return_tensors="pt", 
            truncation=True, 
            padding=True, 
            max_length=512
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            probabilities = torch.nn.functional.softmax(outputs.logits, dim=1)
            
        confidence, predicted_class_id = torch.max(probabilities, dim=1)
        
        predicted_class_id = predicted_class_id.item()
        confidence = confidence.item()
        
        label = self.id2label.get(predicted_class_id, str(predicted_class_id))
        # id2label 有时候 key 是 str
        if isinstance(self.id2label, dict) and predicted_class_id not in self.id2label:
             label = self.id2label.get(str(predicted_class_id), "未知")
             
        return label, confidence

    def predict_batch(self, texts: List[str]) -> List[Tuple[str, float]]:
        """批量预测"""
        results = []
        for text in texts:
            results.append(self.predict(text))
        return results
