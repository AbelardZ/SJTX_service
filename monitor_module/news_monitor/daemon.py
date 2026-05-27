import os
import signal
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
MAIN_SCRIPT = BASE_DIR / "monitor_module" / "news_monitor" / "main.py"
LOCK_FILE = Path("/tmp/sjtx_news_monitor_child.pid")
MAX_RSS_MB = int(os.environ.get("NEWS_MONITOR_MAX_RSS_MB", "1600"))
CHECK_INTERVAL = max(5, int(os.environ.get("NEWS_MONITOR_CHECK_INTERVAL", "15")))
RESTART_DELAY = max(1, int(os.environ.get("NEWS_MONITOR_RESTART_DELAY", "10")))
MIN_UPTIME_SECONDS = int(os.environ.get("NEWS_MONITOR_MIN_UPTIME_SECONDS", "120"))
MAX_UPTIME_SECONDS = int(os.environ.get("NEWS_MONITOR_MAX_UPTIME_SECONDS", "21600"))

_shutdown_requested = False


def _handle_signal(signum, frame):
    global _shutdown_requested
    _shutdown_requested = True


def _sleep_with_shutdown(seconds):
    deadline = time.time() + seconds
    while not _shutdown_requested and time.time() < deadline:
        time.sleep(min(1, max(0.1, deadline - time.time())))


def _read_rss_mb(pid):
    status_path = Path(f"/proc/{pid}/status")
    with status_path.open("r", encoding="utf-8", errors="ignore") as fp:
        for line in fp:
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) / 1024.0
    return 0.0


def _kill_stale_main_processes():
    """杀掉所有残留的 main.py 子进程，防止双进程同时跑。"""
    killed = 0
    for proc_path in Path("/proc").iterdir():
        if not proc_path.name.isdigit():
            continue
        try:
            cmdline = (proc_path / "cmdline").read_text(errors="ignore")
            if "monitor_module/news_monitor/main.py" in cmdline:
                pid = int(proc_path.name)
                if pid == os.getpid():
                    continue
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed += 1
                    print(f"[NEWS_MONITOR_SUPERVISOR] killed stale main.py pid={pid}")
                except OSError:
                    pass
        except (FileNotFoundError, PermissionError, ValueError):
            continue
    if killed:
        print(f"[NEWS_MONITOR_SUPERVISOR] cleaned up {killed} stale main.py process(es)")


def _start_child():
    _kill_stale_main_processes()
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    proc = subprocess.Popen(
        [sys.executable, str(MAIN_SCRIPT)],
        cwd=str(BASE_DIR),
        env=env,
    )
    try:
        LOCK_FILE.write_text(str(proc.pid))
    except Exception:
        pass
    return proc


def _stop_child(proc):
    if proc is None:
        return
    if proc.poll() is not None:
        return

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    # 确保没有残留
    _kill_stale_main_processes()
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def supervise():
    print(
        f"[NEWS_MONITOR_SUPERVISOR] starting with RSS cap {MAX_RSS_MB} MB, "
        f"check interval {CHECK_INTERVAL}s, max uptime {MAX_UPTIME_SECONDS}s"
    )
    child = None
    child_start_time = 0.0

    while not _shutdown_requested:
        if child is None or child.poll() is not None:
            if child is not None:
                print(f"[NEWS_MONITOR_SUPERVISOR] child exited with code {child.returncode}")
                if _shutdown_requested:
                    break
                _sleep_with_shutdown(RESTART_DELAY)

            if _shutdown_requested:
                break

            print(f"[NEWS_MONITOR_SUPERVISOR] launching {MAIN_SCRIPT}")
            child = _start_child()
            child_start_time = time.time()
            print(f"[NEWS_MONITOR_SUPERVISOR] child pid={child.pid}")

        try:
            rss_mb = _read_rss_mb(child.pid)
            uptime = time.time() - child_start_time
            if uptime >= MAX_UPTIME_SECONDS:
                print(
                    f"[NEWS_MONITOR_SUPERVISOR] uptime {uptime:.0f}s reached recycle limit; restarting child"
                )
                _stop_child(child)
                child = None
                _sleep_with_shutdown(RESTART_DELAY)
                continue

            if rss_mb >= MAX_RSS_MB and uptime >= MIN_UPTIME_SECONDS:
                print(
                    f"[NEWS_MONITOR_SUPERVISOR] rss {rss_mb:.1f} MB exceeded cap; restarting child"
                )
                _stop_child(child)
                child = None
                _sleep_with_shutdown(RESTART_DELAY)
                continue
        except FileNotFoundError:
            child = None
            continue
        except Exception as exc:
            print(f"[NEWS_MONITOR_SUPERVISOR] memory check failed: {exc}")

        _sleep_with_shutdown(CHECK_INTERVAL)

    if child is not None:
        _stop_child(child)


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    supervise()


if __name__ == "__main__":
    main()