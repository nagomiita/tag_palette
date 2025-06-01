# db/engine.py
from config import DB_PATH
from sqlalchemy import create_engine

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
