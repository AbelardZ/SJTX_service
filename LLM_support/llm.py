from openai import OpenAI
import os
from datetime import datetime

class MarketAnalysisService:
    def __init__(self, model="deepseek-ai/DeepSeek-V2.5"):
        # 初始化客户端
        self.client = OpenAI(
            base_url='https://api.siliconflow.cn/v1',
            api_key='sk-vanmpefgzkgoydyshvdwvasbsiphmncpqycjqzxrvaswholc'
        )
        self.model = "deepseek-ai/DeepSeek-V3.2-Exp"  # 指定大模型类型
        self.messages = [] # 存储当前会话的上下文历史
        
        # 设置保存目录为当前文件所在目录下的 saved_reports
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.save_dir = os.path.join(base_dir, "saved_reports")
        
        # 确保保存目录存在
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)

        # 系统提示词
        self.system_prompt = "你是一个资深的金融市场分析师，擅长通过数据挖掘市场情绪和潜在机会。"
        
        # 结构化模板
        self.prompt_template = """
你是一个专业的助手。请根据我提供的信息，按照要求进行回答。

【背景/数据】：
{context}

【具体指令】：
{instruction}

请使用清晰的 Markdown 格式输出。
"""

    def start_analysis(self, context, instruction, date_str=None):
        """
        【第一步：一键分析】
        接收后端提供的 context 和 instruction，开启新的会话。
        返回一个生成器 (generator)，用于流式传输。
        """
        # 1. 重置历史，开启新会话
        self.messages = [{"role": "system", "content": self.system_prompt}]
        
        # 2. 组合 Prompt
        full_prompt = self.prompt_template.format(context=context, instruction=instruction)
        self.messages.append({"role": "user", "content": full_prompt})

        # 3. 调用 API 并流式返回
        full_response = ""
        print(f"[System] 开始分析任务: {instruction[:20]}...")
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                stream=True
            )

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield content # <--- 关键：这里将数据一点点“推”给调用者（前端）
            
            # 4. 分析完成后，将 AI 的回答加入历史，以便后续追问
            self.messages.append({"role": "assistant", "content": full_response})
            
            # 5. 自动保存报告
            self._save_to_markdown(instruction, context, full_response, date_str)
            
        except Exception as e:
            yield f"Error: {str(e)}"

    def follow_up_chat(self, user_question):
        """
        【第二步：追问】
        基于之前的分析结果进行问答。
        """
        # 1. 加入用户问题
        self.messages.append({"role": "user", "content": user_question})
        
        full_response = ""
        print(f"[System] 收到追问: {user_question}")
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                stream=True
            )

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield content

            # 2. 加入 AI 回答
            self.messages.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            yield f"Error: {str(e)}"

    def _save_to_markdown(self, title_hint, context, content, date_str=None):
        """辅助方法：保存文件"""
        if date_str:
            # 使用传入的日期（分析对象日期）
            file_date = date_str
        else:
            # 默认使用当前日期
            file_date = datetime.now().strftime("%Y_%m_%d")
            
        timestamp = datetime.now().strftime("%H%M%S")
        safe_title = "".join([c for c in title_hint[:10] if c.isalnum() or c in (' ', '_', '-')]).strip()
        
        # 文件名格式: AI_Analysis_YYYY_MM_DD_HHMMSS.md
        filename = f"{self.save_dir}/AI_Analysis_{file_date}_{timestamp}.md"
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# AI 市场分析报告 ({file_date})\n\n")
            f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"## 1. 背景数据\n{context}\n\n")
            f.write(f"## 2. 分析结论\n{content}\n")
        print(f"\n[System] 报告已归档: {filename}")


# ==========================================
# 模拟 后端 Controller 的调用过程
# ==========================================
if __name__ == "__main__":
    # 实例化服务
    service = MarketAnalysisService()

    # --- 场景 1: 前端点击“一键分析” ---
    # 这些数据通常来自您的数据库或爬虫
    mock_backend_context = """
    今日上证指数收盘 3050 点，下跌 1.2%。
    成交额 8000 亿，较昨日缩量 10%。
    北向资金净流出 45 亿。
    行业板块中，只有银行、煤炭翻红，TMT 板块跌幅居前。
    """
    mock_backend_instruction = "请分析今日市场情绪，并给出明日的操作建议。"

    print(">>> [前端] 用户点击了 '一键分析' 按钮")
    
    # 模拟流式推送到前端
    print(">>> [WebSocket] 开始推送流数据: \n")
    for chunk in service.start_analysis(mock_backend_context, mock_backend_instruction):
        print(chunk, end="", flush=True)
    print("\n\n>>> [前端] 分析结束，显示追问框")

    # --- 场景 2: 用户追问 ---
    while True:
        user_input = input("\n>>> [前端] 请输入追问 (输入 quit 退出): ")
        if user_input.lower() in ['quit', 'exit']:
            break
            
        print(">>> [WebSocket] 推送回答: \n")
        for chunk in service.follow_up_chat(user_input):
            print(chunk, end="", flush=True)
        print("\n")