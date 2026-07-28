from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import auth
from app.config import settings
from app.models import AuthSession, User, utcnow


def test_send_code_rejects_invalid_phone(client):
    response = client.post("/api/auth/sms/send", json={"phone": "123", "purpose": "login"})
    assert response.status_code == 422


def test_send_code_and_cooldown(client):
    first = client.post("/api/auth/sms/send", json={"phone": "13800138000", "purpose": "login"})
    second = client.post("/api/auth/sms/send", json={"phone": "13800138000", "purpose": "login"})
    assert first.status_code == 200
    assert first.json()["debug_code"] == "123456"
    assert second.status_code == 429


def test_debug_sms_is_never_exposed_through_public_host(client):
    response = client.post(
        "/api/auth/sms/send",
        headers={"Host": "finance.chiraliumai.cn"},
        json={"phone": "13800138998", "purpose": "login"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "短信服务尚未配置"


def test_loopback_host_detection_supports_ipv6(client):
    response = client.post(
        "/api/auth/sms/send",
        headers={"Host": "[::1]:18081"},
        json={"phone": "13800138996", "purpose": "login"},
    )
    assert response.status_code == 200
    assert response.json()["debug_code"] == "123456"


def test_phone_hour_limit(client, fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "sms_phone_hour_limit", 2)
    phone = "13800138001"
    assert client.post("/api/auth/sms/send", json={"phone": phone}).status_code == 200
    fake_redis.delete(f"sms:cooldown:{phone}")
    assert client.post("/api/auth/sms/send", json={"phone": phone}).status_code == 200
    fake_redis.delete(f"sms:cooldown:{phone}")
    assert client.post("/api/auth/sms/send", json={"phone": phone}).status_code == 429


def test_phone_day_limit(client, fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "sms_phone_hour_limit", 10)
    monkeypatch.setattr(settings, "sms_phone_day_limit", 2)
    phone = "13800138101"
    assert client.post("/api/auth/sms/send", json={"phone": phone}).status_code == 200
    fake_redis.delete(f"sms:cooldown:{phone}")
    assert client.post("/api/auth/sms/send", json={"phone": phone}).status_code == 200
    fake_redis.delete(f"sms:cooldown:{phone}")
    response = client.post("/api/auth/sms/send", json={"phone": phone})
    assert response.status_code == 429
    assert "今日" in response.json()["detail"]


def test_ip_limit(client, fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "sms_ip_hour_limit", 1)
    assert client.post("/api/auth/sms/send", json={"phone": "13800138002"}).status_code == 200
    response = client.post("/api/auth/sms/send", json={"phone": "13800138003"})
    assert response.status_code == 429


def test_global_day_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "sms_global_day_limit", 1)
    assert client.post("/api/auth/sms/send", json={"phone": "13800138102"}).status_code == 200
    response = client.post("/api/auth/sms/send", json={"phone": "13800138103"})
    assert response.status_code == 503
    assert "安全上限" in response.json()["detail"]


def test_turnstile_is_required_after_abnormal_threshold(client, fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "sms_phone_hour_limit", 10)
    monkeypatch.setattr(settings, "turnstile_enforce_after_phone_hourly", 1)
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    phone = "13800138104"
    assert client.post("/api/auth/sms/send", json={"phone": phone}).status_code == 200
    fake_redis.delete(f"sms:cooldown:{phone}")
    response = client.post("/api/auth/sms/send", json={"phone": phone})
    assert response.status_code == 403
    assert "人机验证" in response.json()["detail"]


def test_wrong_expired_and_attempt_limited_codes(client, fake_redis):
    phone = "13800138004"
    sent = client.post("/api/auth/sms/send", json={"phone": phone})
    assert sent.status_code == 200
    for _ in range(settings.sms_verify_attempt_limit):
        response = client.post("/api/auth/login/sms", json={"phone": phone, "sms_code": "000000"})
        assert response.status_code == 400
    locked = client.post("/api/auth/login/sms", json={"phone": phone, "sms_code": "000000"})
    assert locked.status_code == 429

    expired_phone = "13800138005"
    client.post("/api/auth/sms/send", json={"phone": expired_phone})
    fake_redis.delete(f"sms:code:login:{expired_phone}")
    expired = client.post(
        "/api/auth/login/sms",
        json={"phone": expired_phone, "sms_code": "123456"},
    )
    assert expired.status_code == 400


def test_code_is_one_time_and_concurrent_safe(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "sms_remote_enabled", False)
    monkeypatch.setattr(settings, "sms_dev_force_local", True)
    monkeypatch.setattr(settings, "sms_code_pepper", "test-pepper")
    phone = "13800138006"
    fake_redis.set(
        f"sms:code:login:{phone}",
        auth.hash_sms_code(phone, "login", "123456"),
        ex=300,
    )

    def consume():
        try:
            auth.consume_login_code(fake_redis, phone, "123456")
            return "ok"
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: consume(), range(2)))
    assert results.count("ok") == 1
    assert results.count(400) == 1


def test_first_login_creates_user_and_existing_login_reuses_it(client, login, db_session, fake_redis):
    first = login("13800138007")
    user = db_session.scalar(select(User).where(User.phone == first["phone"]))
    assert user is not None
    user_id = user.id
    fake_redis.delete(f"sms:cooldown:{first['phone']}")
    second = login(first["phone"])
    assert db_session.scalar(select(User).where(User.phone == first["phone"])).id == user_id
    assert first["token"] != second["token"]


def test_refresh_cookie_rotation_and_thirty_day_session(client, login, db_session):
    result = login("13800138008")
    set_cookie = result["response"].headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Max-Age=2592000" in set_cookie
    old_cookie = client.cookies.get(settings.refresh_cookie_name)
    refresh = client.post("/api/auth/refresh", headers={"Origin": settings.frontend_origin})
    assert refresh.status_code == 200
    assert client.cookies.get(settings.refresh_cookie_name) != old_cookie
    assert client.post(
        "/api/auth/refresh",
        headers={"Origin": settings.frontend_origin},
        cookies={settings.refresh_cookie_name: old_cookie},
    ).status_code == 401
    session = db_session.scalar(select(AuthSession).order_by(AuthSession.created_at.desc()))
    remaining = session.expires_at - utcnow().replace(tzinfo=session.expires_at.tzinfo)
    assert timedelta(days=29) < remaining <= timedelta(days=30)


def test_secure_cookie_flag(client, login, monkeypatch, fake_redis):
    monkeypatch.setattr(settings, "cookie_secure", True)
    response = login("13800138009")["response"]
    assert "Secure" in response.headers["set-cookie"]


def test_logout_revokes_refresh(client, login):
    login("13800138010")
    logout = client.post("/api/auth/logout", headers={"Origin": settings.frontend_origin})
    assert logout.status_code == 200
    assert client.post("/api/auth/refresh", headers={"Origin": settings.frontend_origin}).status_code == 204


def test_refresh_without_session_is_anonymous_not_an_error(client):
    response = client.post("/api/auth/refresh", headers={"Origin": settings.frontend_origin})
    assert response.status_code == 204


def test_invalid_refresh_cookie_is_cleared(client):
    client.cookies.set(settings.refresh_cookie_name, "invalid-session", path="/api/auth")
    response = client.post("/api/auth/refresh", headers={"Origin": settings.frontend_origin})
    assert response.status_code == 401
    set_cookie = response.headers["set-cookie"]
    assert f"{settings.refresh_cookie_name}=" in set_cookie
    assert "Max-Age=0" in set_cookie
    assert "Path=/api/auth" in set_cookie


def test_inactive_user_cannot_refresh(client, login, db_session):
    result = login("13800138011")
    user = db_session.scalar(select(User).where(User.phone == result["phone"]))
    user.is_active = False
    db_session.commit()
    assert client.post("/api/auth/refresh", headers={"Origin": settings.frontend_origin}).status_code == 401


def test_untrusted_origin_is_rejected(client, login):
    login("13800138012")
    response = client.post("/api/auth/refresh", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_session_listing_and_revocation(client, login):
    result = login("13800138013")
    listing = client.get("/api/auth/sessions", headers=result["headers"])
    assert listing.status_code == 200
    current = listing.json()["sessions"][0]
    assert current["current"] is True
    revoked = client.delete(f"/api/auth/sessions/{current['id']}", headers=result["headers"])
    assert revoked.status_code == 200
    assert client.get("/api/auth/me", headers=result["headers"]).status_code == 401
