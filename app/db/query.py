from db.init import engine
from db.models import ImageEntry
from sqlalchemy.orm import Session


def get_all_image_entries() -> list[ImageEntry]:
    with Session(engine) as session:
        return session.query(ImageEntry).order_by(ImageEntry.id).all()


def get_image_entry_by_id(image_id: int) -> ImageEntry | None:
    with Session(engine) as session:
        return session.query(ImageEntry).filter(ImageEntry.id == image_id).first()


def toggle_favorite_flag(image_id: int) -> bool | None:
    with Session(engine) as session:
        entry = session.query(ImageEntry).filter(ImageEntry.id == image_id).first()
        if entry:
            entry.is_favorite = not entry.is_favorite
            session.commit()
            return entry.is_favorite
    return None


def get_favorite_flag(image_id: int) -> bool:
    with Session(engine) as session:
        entry = session.query(ImageEntry).filter(ImageEntry.id == image_id).first()
        return entry.is_favorite if entry else False
