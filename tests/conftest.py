import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Re-bind the database engine and SessionLocal to a shared in-memory database using StaticPool
import app.database

app.database.DATABASE_URL = "sqlite:///:memory:"
shared_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
app.database.engine = shared_engine
app.database.SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=shared_engine
)

from app.database import Base, SessionLocal
from app.api.ingest import get_db
from main import app


@pytest.fixture(autouse=True)
def init_db():
    # Re-create database schema on the shared engine for clean test state
    Base.metadata.drop_all(bind=shared_engine)
    Base.metadata.create_all(bind=shared_engine)
    yield
    Base.metadata.drop_all(bind=shared_engine)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def v1_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "ct200_manual.md"


@pytest.fixture
def v2_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "ct200_manual_v2.md"
