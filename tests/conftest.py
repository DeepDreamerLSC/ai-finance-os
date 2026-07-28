from __future__ import annotations

from collections.abc import Generator

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_redis
from app.config import settings
from app.database import get_db
from app.models import Base
from app.server import app


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def client(db_session, fake_redis, tmp_path, monkeypatch):
    def override_db():
        yield db_session

    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(settings, "sms_remote_enabled", False)
    monkeypatch.setattr(settings, "sms_dev_force_local", True)
    monkeypatch.setattr(settings, "sms_dev_expose_code", True)
    monkeypatch.setattr(settings, "sms_test_code", "123456")
    monkeypatch.setattr(settings, "sms_code_pepper", "test-pepper")
    monkeypatch.setattr(settings, "jwt_secret_key", "test-jwt-secret-that-is-long-enough-1234")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "demo_seed_new_users", True)
    monkeypatch.setattr(settings, "sms_phone_hour_limit", 5)
    monkeypatch.setattr(settings, "sms_phone_day_limit", 10)
    monkeypatch.setattr(settings, "sms_ip_hour_limit", 20)
    monkeypatch.setattr(settings, "sms_global_day_limit", 500)
    monkeypatch.setattr(settings, "turnstile_enforce_after_phone_hourly", 99)
    monkeypatch.setattr(settings, "turnstile_secret_key", "")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = lambda: fake_redis
    with TestClient(app, base_url="http://127.0.0.1:18081") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def login(client):
    def perform(phone: str = "13800138000") -> dict:
        sent = client.post(
            "/api/auth/sms/send",
            json={"phone": phone, "purpose": "login"},
        )
        assert sent.status_code == 200, sent.text
        response = client.post(
            "/api/auth/login/sms",
            json={"phone": phone, "sms_code": sent.json()["debug_code"]},
        )
        assert response.status_code == 200, response.text
        return {
            "phone": phone,
            "token": response.json()["access_token"],
            "headers": {"Authorization": f"Bearer {response.json()['access_token']}"},
            "response": response,
        }

    return perform
