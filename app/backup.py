import shutil
from pathlib import Path

from db.models import ImageEntry
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# 設定
DB_PATH = Path("images.db")  # 元DB
BACKUP_DIR = Path("Z:/backup")  # バックアップ先
BACKUP_DB_PATH = BACKUP_DIR / DB_PATH.name
BACKUP_IMAGE_DIR = BACKUP_DIR / "images"  # 画像バックアップフォルダ


def ensure_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def copy_file_if_needed(src: Path, dst: Path):
    if not src.exists():
        print(f"⚠️ スキップ（存在しない）: {src}")
        return
    if dst.exists() and src.stat().st_mtime <= dst.stat().st_mtime:
        print(f"✅ スキップ（変更なし）: {dst}")
        return
    ensure_directory(dst.parent)
    shutil.copy2(src, dst)
    print(f"📁 コピー完了: {src} → {dst}")


def backup_database():
    ensure_directory(BACKUP_DIR)
    shutil.copy2(DB_PATH, BACKUP_DB_PATH)
    print(f"✅ DBコピー完了: {DB_PATH} → {BACKUP_DB_PATH}")


def backup_images():
    engine = create_engine(f"sqlite:///{DB_PATH}")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        entries = session.execute(select(ImageEntry)).scalars().all()
        for entry in entries:
            src_path = Path(entry.image_path)
            rel_path = (
                src_path.relative_to(src_path.anchor)
                if src_path.is_absolute()
                else src_path
            )
            dst_path = BACKUP_IMAGE_DIR / rel_path
            copy_file_if_needed(src_path, dst_path)
    finally:
        session.close()


def run_backup():
    print("🔄 バックアップ開始")
    backup_database()
    backup_images()
    print("🎉 バックアップ完了")


if __name__ == "__main__":
    run_backup()
