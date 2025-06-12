import os
import subprocess
import sys
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

SCRIPT_NAME = "main.py"  # メインスクリプト（再実行対象）

# 監視対象（ファイル・フォルダ）
WATCH_TARGETS = ["main.py", "gui/", "db/", "utils/"]

# 無視対象
IGNORE_DIRS = ["__pycache__", ".vscode"]
IGNORE_EXTS = [".pyc", ".pyo", ".swp", ".tmp", ".DS_Store"]
IGNORE_FILES = [".code-workspace"]

# 再起動の間隔制限（秒）
RESTART_COOLDOWN = 3.0


class ReloadHandler(FileSystemEventHandler):
    def __init__(self):
        self.process = None
        self.last_restart_time = 0
        self.watch_targets = [os.path.abspath(t) for t in WATCH_TARGETS]
        self.start_app()

    def start_app(self):
        if self.process:
            print("⏹️ アプリを停止中...")
            self.process.terminate()
            self.process.wait()
        print("▶️ アプリ再起動中: python", SCRIPT_NAME)

        # 環境変数を設定（既存の環境を継承しつつ APP_ENV を追加）
        env = os.environ.copy()
        env["APP_ENV"] = "dev"

        # subprocess に環境変数を渡して dev 起動
        self.process = subprocess.Popen([sys.executable, SCRIPT_NAME], env=env)

    def on_modified(self, event):
        changed_path = os.path.abspath(event.src_path)

        # 再起動間隔が短すぎる場合は無視
        if time.time() - self.last_restart_time < RESTART_COOLDOWN:
            return

        # 拡張子・ファイル名・ディレクトリチェック
        if os.path.splitext(changed_path)[1] in IGNORE_EXTS:
            return
        if any(part in changed_path for part in IGNORE_DIRS):
            return
        if os.path.basename(changed_path) in IGNORE_FILES:
            return
        if not changed_path.endswith(".py"):
            return

        # 対象の監視パスに該当するかチェック
        for target in self.watch_targets:
            target_abs = os.path.abspath(target)
            if os.path.isdir(target_abs):
                if changed_path.startswith(target_abs + os.sep):
                    print(f"🔁 変更検知: {changed_path} → 再起動")
                    self.last_restart_time = time.time()
                    self.start_app()
                    break
            elif changed_path == target_abs:
                print(f"🔁 変更検知: {changed_path} → 再起動")
                self.last_restart_time = time.time()
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
