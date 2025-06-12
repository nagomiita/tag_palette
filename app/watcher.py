import hashlib
import os
import subprocess
import sys
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

SCRIPT_NAME = "main.py"
WATCH_TARGETS = ["main.py", "gui/", "db/", "utils/"]
IGNORE_DIRS = ["__pycache__", ".vscode"]
IGNORE_EXTS = [".pyc", ".pyo", ".swp", ".tmp", ".DS_Store"]
IGNORE_FILES = [".code-workspace"]
RESTART_COOLDOWN = 3.0


class ReloadHandler(FileSystemEventHandler):
    def __init__(self):
        self.process = None
        self.last_restart_time = 0
        self.watch_targets = [os.path.abspath(t) for t in WATCH_TARGETS]
        self.file_hash_cache = {}  # ファイルごとの前回内容
        self.start_app()

    def start_app(self):
        if self.process:
            print("⏹️ アプリを停止中...")
            self.process.terminate()
            self.process.wait()
        print("▶️ アプリ再起動中: python", SCRIPT_NAME)
        env = os.environ.copy()
        env["APP_ENV"] = "dev"
        self.process = subprocess.Popen([sys.executable, SCRIPT_NAME], env=env)

    def on_modified(self, event):
        if event.is_directory:
            return

        changed_path = os.path.abspath(event.src_path)

        if time.time() - self.last_restart_time < RESTART_COOLDOWN:
            return
        if os.path.splitext(changed_path)[1] not in [".py"]:
            return
        if any(part in changed_path for part in IGNORE_DIRS):
            return
        if os.path.basename(changed_path) in IGNORE_FILES:
            return

        for target in self.watch_targets:
            target_abs = os.path.abspath(target)
            if os.path.isdir(target_abs):
                if changed_path.startswith(target_abs + os.sep):
                    if not self._has_file_changed(changed_path):
                        return
                    print(f"🔁 変更検知: {changed_path} → 再起動")
                    self.last_restart_time = time.time()
                    self.start_app()
                    break
            elif changed_path == target_abs:
                if not self._has_file_changed(changed_path):
                    return
                print(f"🔁 変更検知: {changed_path} → 再起動")
                self.last_restart_time = time.time()
                self.start_app()
                break

    def _has_file_changed(self, path: str) -> bool:
        """内容とmtime（更新時刻）の両方を使って変更判定"""
        try:
            stat = os.stat(path)
            mtime = stat.st_mtime  # 最終更新時刻（float秒）
            with open(path, "rb") as f:
                content = f.read()
                hash_now = hashlib.md5(content).hexdigest()
        except Exception:
            return False

        prev = self.file_hash_cache.get(path)
        if prev and prev["hash"] == hash_now and prev["mtime"] == mtime:
            return False  # 中身も更新時刻も変わっていない

        # 更新履歴を保存
        self.file_hash_cache[path] = {"hash": hash_now, "mtime": mtime}
        return True


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
