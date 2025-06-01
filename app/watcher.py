import os
import subprocess
import sys
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

SCRIPT_NAME = "main.py"  # メインスクリプト（再実行対象）

# 監視したいファイルやディレクトリのリスト
WATCH_TARGETS = [
    "main.py",
    "ui.py",
    "logic.py",
    # "components/",  # ディレクトリも指定可能（再帰なし）
]


class ReloadHandler(FileSystemEventHandler):
    def __init__(self):
        self.process = None
        self.start_app()

    def start_app(self):
        if self.process:
            print("⏹️ アプリを停止中...")
            self.process.terminate()
            self.process.wait()
        print("▶️ アプリ再起動中: python", SCRIPT_NAME)
        self.process = subprocess.Popen([sys.executable, SCRIPT_NAME])

    def on_modified(self, event):
        changed_path = os.path.relpath(event.src_path)
        if any(changed_path.startswith(t) for t in WATCH_TARGETS):
            print(f"🔁 変更検知: {changed_path} → 再起動")
            self.start_app()


if __name__ == "__main__":
    event_handler = ReloadHandler()
    observer = Observer()
    observer.schedule(event_handler, ".", recursive=True)
    observer.start()
    print("👀 ファイルを監視中（Ctrl+C で終了）")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 停止")
        observer.stop()
    observer.join()
