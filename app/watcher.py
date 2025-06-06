import os
import subprocess
import sys
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

SCRIPT_NAME = "main.py"  # メインスクリプト（再実行対象）

# 監視したいファイルやディレクトリのリスト
WATCH_TARGETS = ["main.py", "gui/", "db/", "config.py", "utils/"]

# 無視するパスや拡張子
IGNORE_DIRS = ["__pycache__"]
IGNORE_EXTS = [".pyc", ".pyo"]


class ReloadHandler(FileSystemEventHandler):
    def __init__(self):
        self.process = None
        self.watch_targets = [os.path.abspath(t) for t in WATCH_TARGETS]
        self.start_app()

    def start_app(self):
        if self.process:
            print("⏹️ アプリを停止中...")
            self.process.terminate()
            self.process.wait()
        print("▶️ アプリ再起動中: python", SCRIPT_NAME)
        self.process = subprocess.Popen([sys.executable, SCRIPT_NAME])

    def on_modified(self, event):
        changed_path = os.path.abspath(event.src_path)

        # ⛔ 無視対象かどうかをチェック
        if any(ignored in changed_path for ignored in IGNORE_DIRS):
            return
        if os.path.splitext(changed_path)[1] in IGNORE_EXTS:
            return
        if not changed_path.endswith(".py"):
            return
        for target in self.watch_targets:
            if os.path.isdir(target):
                if changed_path.startswith(target + os.sep):
                    print(f"🔁 変更検知: {changed_path} → 再起動")
                    self.start_app()
                    break
            elif changed_path == target:
                print(f"🔁 変更検知: {changed_path} → 再起動")
                self.start_app()
                break


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
