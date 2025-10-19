import os
import time

import psutil

# from config import DB_PATH

MAX_RETRIES = 3
RETRY_DELAY_SEC = 1.0


# ファイルを使用しているプロセスを特定して終了
def kill_process_using_file(filepath: str):
    for proc in psutil.process_iter(["pid", "name", "open_files"]):
        try:
            for f in proc.info.get("open_files") or []:
                if f.path == os.path.abspath(filepath):
                    print(f"🔪 プロセス {proc.pid} ({proc.name()}) を終了します")
                    proc.terminate()
                    proc.wait(timeout=3)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue


# 強制削除試行
for attempt in range(1, MAX_RETRIES + 1):
    try:
        os.remove("images_dev.db")
        print(f"✅ 削除完了: {'images_dev.db'}")
        break
    except PermissionError as e:
        print(f"🛑 削除失敗（{attempt}/{MAX_RETRIES}）: {e}")
        kill_process_using_file("images_dev.db")
        time.sleep(RETRY_DELAY_SEC)
else:
    print("🚨 複数回試行しましたが削除できませんでした。")
