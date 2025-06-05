from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from db.engine import engine
from db.models import ImageEntry
from sqlalchemy.orm import Session
from utils.image import image_manager

# ---------------------------- Session Management ----------------------------


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


# ---------------------------- Query: Fetch Entries ----------------------------


def get_all_image_entries() -> list[ImageEntry]:
    with get_session() as session:
        return session.query(ImageEntry).order_by(ImageEntry.id).all()


def get_favorite_image_entries() -> list[ImageEntry]:
    with get_session() as session:
        return (
            session.query(ImageEntry)
            .filter_by(is_favorite=True)
            .order_by(ImageEntry.id)
            .all()
        )


def get_image_entry_by_id(image_id: int) -> ImageEntry | None:
    with get_session() as session:
        return session.query(ImageEntry).filter_by(id=image_id).first()


# ---------------------------- Query: Favorite Flags ----------------------------


def get_favorite_flag(image_id: int) -> bool:
    with get_session() as session:
        entry = session.query(ImageEntry).filter_by(id=image_id).first()
        return entry.is_favorite if entry else False


def toggle_favorite_flag(image_id: int) -> bool | None:
    with get_session() as session:
        entry = session.query(ImageEntry).filter_by(id=image_id).first()
        if entry:
            entry.is_favorite = not entry.is_favorite
            try:
                session.commit()
                return entry.is_favorite
            except Exception:
                session.rollback()
    return None


# ---------------------------- Query: Image Registration ----------------------------


def get_registered_image_paths() -> set[str]:
    with get_session() as session:
        return {r.image_path for r in session.query(ImageEntry.image_path).all()}


def add_image_entry(image_path: Path, thumbnail_path: Path) -> None:
    with get_session() as session:
        session.add(
            ImageEntry(image_path=str(image_path), thumbnail_path=str(thumbnail_path))
        )
        session.commit()


def add_image_entries(entries: list[tuple[Path, Path]]) -> None:
    with get_session() as session:
        image_objects = [
            ImageEntry(
                image_path=str(orig),
                thumbnail_path=str(thumb),
                created_at=image_manager.extract_captured_at(orig),
            )
            for orig, thumb in entries
        ]
        session.add_all(image_objects)
        session.commit()


def delete_image_entry(image_id: int) -> bool:
    with get_session() as session:
        entry = session.query(ImageEntry).filter_by(id=image_id).first()
        if entry:
            image_manager.delete_image_files(entry.image_path, entry.thumbnail_path)
            session.delete(entry)
            session.commit()
            return True
    return False


# ---------------------------- Query: Tag ----------------------------
def get_tags_for_image(image_id: int) -> list[str]:
    with get_session() as session:
        image = session.query(ImageEntry).filter_by(id=image_id).first()
        if not image:
            return []
        return ["test"]  # [t.tag.tag for t in image.image_tags]
