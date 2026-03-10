import time
import subprocess
import os
import sys

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))

def run_fetchers():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting Daily Chart Fetchers...")
    script_path = os.path.join(current_dir, 'run_all_fetchers.py')
    try:
        # Run run_all_fetchers.py using the same python interpreter
        result = subprocess.run([sys.executable, script_path], cwd=current_dir)
        if result.returncode == 0:
            print("Fetchers completed successfully.")
        else:
            print(f"Fetchers failed with code {result.returncode}")
    except Exception as e:
        print(f"Error running fetchers: {e}")

def main():
    print("Scheduler started. Waiting for 15:30...")
    last_run_date = None
    
    while True:
        now = time.localtime()
        current_date = time.strftime('%Y-%m-%d', now)
        
        # Check if it's 15:30 and haven't run today
        if now.tm_hour == 15 and now.tm_min == 30 and last_run_date != current_date:
             run_fetchers()
             last_run_date = current_date
             time.sleep(60) # Wait a bit
        
        time.sleep(10)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--now':
        run_fetchers()
    else:
        main()
