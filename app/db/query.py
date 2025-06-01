from db.init import engine
from db.models import ImageEntry
from sqlalchemy.orm import Session


def get_all_image_entries() -> list[ImageEntry]:
    with Session(engine) as session:
        return session.query(ImageEntry).order_by(ImageEntry.id).all()


def get_image_entry_by_id(image_id: int) -> ImageEntry | None:
    with Session(engine) as session:
        return session.query(ImageEntry).filter(ImageEntry.id == image_id).first()
