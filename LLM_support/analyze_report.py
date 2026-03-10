import os
import sys
import glob

# Add current directory to path to import llm
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm import MarketAnalysisService

def get_latest_report_content(report_dir):
    # Find all .md files in the report directory
    files = glob.glob(os.path.join(report_dir, "Report_*.md"))
    if not files:
        return None, None
    
    # Sort by filename (which contains date YYYY_MM_DD) descending
    latest_file = sorted(files, reverse=True)[0]
    
    with open(latest_file, 'r', encoding='utf-8') as f:
        return latest_file, f.read()

def get_instruction_content(instruction_path):
    if not os.path.exists(instruction_path):
        return "请对上述数据进行分析。"
    with open(instruction_path, 'r', encoding='utf-8') as f:
        return f.read()

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    report_dir = os.path.join(base_dir, 'reports')
    instruction_path = os.path.join(base_dir, 'prompt_instruction.md')
    
    # 1. Get Data Report (Context)
    report_path, report_content = get_latest_report_content(report_dir)
    if not report_content:
        print("Error: No reports found in", report_dir)
        return

    print(f"Using report: {os.path.basename(report_path)}")

    # 2. Get Pre-instruction (Instruction)
    instruction_content = get_instruction_content(instruction_path)
    print("Using instruction from prompt_instruction.md")

    # 3. Initialize LLM Service
    service = MarketAnalysisService()
    
    # 4. Start Analysis
    print("\n--- Starting LLM Analysis ---\n")
    
    # The start_analysis method returns a generator
    response_generator = service.start_analysis(context=report_content, instruction=instruction_content)
    
    full_response = ""
    for chunk in response_generator:
        # Assuming chunk is a string or has content. 
        # Let's check llm.py implementation details if possible, but usually it yields strings or objects.
        # Based on standard OpenAI streaming, it might be chunks.
        # Let's print it directly.
        print(chunk, end="", flush=True)
        full_response += chunk
    
    print("\n\n--- Analysis Complete ---")
    
    # Optional: Save the analysis
    analysis_file = report_path.replace("Report_", "Analysis_")
    with open(analysis_file, 'w', encoding='utf-8') as f:
        f.write(full_response)
    print(f"Analysis saved to: {analysis_file}")

if __name__ == "__main__":
    main()
