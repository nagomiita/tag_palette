from config import DB_PATH, IMAGE_DIR, SUPPORTED_FORMATS, THUMB_DIR, THUMBNAIL_SIZE
from db.models import Base, ImageEntry
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
THUMB_DIR.mkdir(exist_ok=True)


def initialize_database():
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        registered = {r.image_path for r in session.query(ImageEntry.image_path).all()}
        for img_path in IMAGE_DIR.glob("*"):
            if (
                img_path.suffix.lower() not in SUPPORTED_FORMATS
                or str(img_path) in registered
            ):
                continue
            thumb_path = THUMB_DIR / f"{img_path.stem}_thumb.png"
            img = Image.open(img_path)
            img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            img.save(thumb_path)
            session.add(
                ImageEntry(image_path=str(img_path), thumbnail_path=str(thumb_path))
            )
        session.commit()
