# image_pathからimage_nameを抽出してDBを更新するスクリプト
import logging
import os

from engine import engine
from models import ImageEntry
from sqlalchemy import select, update
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def extract_image_name(image_path: str) -> str:
    """Extract the image name from the image path."""
    return os.path.splitext(os.path.basename(image_path))[0]


def update_image_names():
    """Update image_name for all ImageEntry records."""
    with Session(engine) as session:
        stmt = select(ImageEntry)
        results = session.execute(stmt).scalars().all()
        for image in results:
            if not image.image_name:
                image_name = extract_image_name(image.image_path)
                logger.info(
                    f"Updating image ID {image.id}: setting image_name to '{image_name}'"
                )
                session.execute(
                    update(ImageEntry)
                    .where(ImageEntry.id == image.id)
                    .values(image_name=image_name)
                )
        session.commit()
    logger.info("Image name update completed.")


if __name__ == "__main__":
    update_image_names()
    logger.info("Image name update completed.")
