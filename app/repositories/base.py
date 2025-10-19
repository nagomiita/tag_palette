from contextlib import contextmanager
from typing import Generator

from db.engine import engine
from sqlalchemy.orm import Session


class BaseRepository:
    """リポジトリの基底クラス"""

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        session = Session(engine)
        try:
            yield session
        finally:
            session.close()
