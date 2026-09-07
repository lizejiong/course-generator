import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import models  # noqa: F401
from app.db.base import Base

TEST_DATABASE_URL = (
    "postgresql+psycopg://course_generator:course_generator@localhost:5433/course_generator"
)
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)


@pytest.fixture()
def db_session():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=TEST_DATABASE_URL,
        courses_root=tmp_path / "courses",
        releases_root=tmp_path / "releases",
    )
