from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from redis import Redis
from redis.exceptions import WatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.finance import seed_user_data
from app.models import AuthSession, User, utcnow


router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)
PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
SMS_CODE_PATTERN = re.compile(r"^\d{6}$")
GENERIC_SMS_ERROR = "验证码错误或已过期"
_redis: Redis | None = None

class SmsSendRequest(BaseModel):
    phone: str
    purpose: str = "login"
    turnstile_token: str | None = None


class SmsLoginRequest(BaseModel):
    phone: str
    sms_code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProfileUpdateRequest(BaseModel):
    display_name: str


@dataclass
class AuthContext:
    user: User
    payload: dict[str, Any]


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def normalize_phone(value: str) -> str:
    phone = re.sub(r"\D", "", value or "")
    if phone.startswith("86") and len(phone) == 13:
        phone = phone[2:]
    if not PHONE_PATTERN.fullmatch(phone):
        raise HTTPException(status_code=422, detail="请输入有效的中国大陆手机号")
    return phone


def client_ip(request: Request) -> str:
    for header in ("cf-connecting-ip", "x-forwarded-for"):
        value = request.headers.get(header)
        if value:
            return value.split(",", 1)[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


def is_loopback_request(request: Request) -> bool:
    host = (request.url.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def device_name(user_agent: str) -> str:
    lowered = user_agent.lower()
    if "iphone" in lowered:
        return "iPhone"
    if "ipad" in lowered:
        return "iPad"
    if "android" in lowered:
        return "Android 设备"
    if "macintosh" in lowered:
        return "Mac 浏览器"
    if "windows" in lowered:
        return "Windows 浏览器"
    return "浏览器"


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_sms_code(phone: str, purpose: str, code: str) -> str:
    material = f"{settings.sms_code_pepper}:{purpose}:{phone}:{code}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def create_access_token(user: User, session_id: str) -> str:
    now = utcnow()
    payload = {
        "sub": user.id,
        "sid": session_id,
        "scope": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="登录状态已失效") from exc
    if payload.get("scope") != "access" or not payload.get("sub") or not payload.get("sid"):
        raise HTTPException(status_code=401, detail="登录状态已失效")
    return payload


def get_current_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="请先登录")
    payload = decode_access_token(credentials.credentials)
    user = db.scalar(select(User).where(User.id == payload["sub"], User.is_active.is_(True)))
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.id == payload["sid"],
            AuthSession.user_id == payload["sub"],
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )
    if not user or not session:
        raise HTTPException(status_code=401, detail="登录状态已失效")
    return AuthContext(user=user, payload=payload)


def validate_cookie_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").rstrip("/")
    if origin and origin not in settings.allowed_origins:
        raise HTTPException(status_code=403, detail="请求来源不受信任")
    if settings.is_production and not origin:
        raise HTTPException(status_code=403, detail="缺少请求来源")


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        path="/api/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/auth",
    )


def create_session(db: Session, user: User, request: Request) -> tuple[str, str]:
    refresh_token = secrets.token_urlsafe(48)
    ip = client_ip(request)
    user_agent = request.headers.get("user-agent", "")[:500]
    session = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        device_name=device_name(user_agent),
        user_agent=user_agent,
        created_ip=ip,
        last_seen_ip=ip,
        expires_at=utcnow() + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(session)
    db.commit()
    return create_access_token(user, session.id), refresh_token


def _increment_rate(redis: Redis, key: str, seconds: int) -> int:
    for _ in range(5):
        try:
            with redis.pipeline() as pipe:
                pipe.watch(key)
                current = int(pipe.get(key) or 0)
                pipe.multi()
                if current:
                    pipe.set(key, current + 1, keepttl=True)
                else:
                    pipe.set(key, 1, ex=seconds)
                pipe.execute()
                return current + 1
        except WatchError:
            continue
    raise HTTPException(status_code=503, detail="短信安全检查繁忙，请稍后重试")


async def verify_turnstile(token: str | None, ip: str) -> None:
    if not settings.turnstile_secret_key:
        if settings.is_production:
            raise HTTPException(status_code=503, detail="人机验证尚未配置")
        return
    if not token:
        raise HTTPException(status_code=403, detail="请完成人机验证后重试")
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": settings.turnstile_secret_key,
                "response": token,
                "remoteip": ip,
            },
        )
    if not response.is_success or not response.json().get("success"):
        raise HTTPException(status_code=403, detail="人机验证未通过")


def _use_remote_sms() -> bool:
    return (
        settings.sms_remote_enabled
        and not settings.sms_dev_force_local
        and bool(settings.sms_access_key)
        and bool(settings.sms_secret_key)
    )


def _dypns_client():
    try:
        from alibabacloud_dypnsapi20170525.client import Client
        from alibabacloud_tea_openapi import models as open_api_models
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="短信服务组件未安装") from exc
    config = open_api_models.Config(
        access_key_id=settings.sms_access_key,
        access_key_secret=settings.sms_secret_key,
    )
    config.endpoint = "dypnsapi.aliyuncs.com"
    return Client(config)


def send_sms_via_provider(phone: str) -> None:
    from alibabacloud_dypnsapi20170525 import models as dypns_models

    template = settings.sms_template_code_login or settings.sms_template_code
    request = dypns_models.SendSmsVerifyCodeRequest(
        phone_number=phone,
        country_code="86",
        sign_name=settings.sms_sign_name,
        template_code=template,
        template_param=json.dumps({"code": "##code##", "min": "5"}, ensure_ascii=False),
        code_length=6,
        code_type=1,
        valid_time=settings.sms_code_expire_seconds,
        interval=settings.sms_cooldown_seconds,
        duplicate_policy=1,
        return_verify_code=False,
    )
    try:
        response = _dypns_client().send_sms_verify_code(request)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="短信发送失败，请稍后重试") from exc
    body = getattr(response, "body", None)
    if getattr(body, "code", None) != "OK":
        raise HTTPException(status_code=502, detail="短信发送失败，请稍后重试")


def verify_sms_via_provider(phone: str, code: str) -> bool:
    from alibabacloud_dypnsapi20170525 import models as dypns_models

    request = dypns_models.CheckSmsVerifyCodeRequest(
        phone_number=phone,
        country_code="86",
        verify_code=code,
    )
    try:
        response = _dypns_client().check_sms_verify_code(request)
    except Exception:
        return False
    body = getattr(response, "body", None)
    return (
        getattr(body, "code", None) == "OK"
        and getattr(getattr(body, "model", None), "verify_result", None) == "PASS"
    )


async def send_login_code(
    redis: Redis,
    phone: str,
    ip: str,
    turnstile_token: str | None,
) -> str | None:
    cooldown_key = f"sms:cooldown:{phone}"
    if not redis.set(cooldown_key, "1", nx=True, ex=settings.sms_cooldown_seconds):
        raise HTTPException(status_code=429, detail="发送过于频繁，请稍后重试")

    now = utcnow()
    hour = now.strftime("%Y%m%d%H")
    day = now.strftime("%Y%m%d")
    try:
        phone_hour = _increment_rate(redis, f"sms:rate:phone:hour:{phone}:{hour}", 3700)
        phone_day = _increment_rate(redis, f"sms:rate:phone:day:{phone}:{day}", 90000)
        ip_hour = _increment_rate(redis, f"sms:rate:ip:hour:{ip}:{hour}", 3700)
        if phone_hour > settings.sms_phone_hour_limit:
            raise HTTPException(status_code=429, detail="该手机号请求过多，请稍后重试")
        if phone_day > settings.sms_phone_day_limit:
            raise HTTPException(status_code=429, detail="该手机号今日请求次数已达上限")
        if ip_hour > settings.sms_ip_hour_limit:
            raise HTTPException(status_code=429, detail="当前网络请求过多，请稍后重试")
        if phone_hour > settings.turnstile_enforce_after_phone_hourly:
            await verify_turnstile(turnstile_token, ip)
        global_day = _increment_rate(redis, f"sms:rate:global:day:{day}", 90000)
        if global_day > settings.sms_global_day_limit:
            raise HTTPException(status_code=503, detail="短信服务今日已达安全上限")

        if _use_remote_sms():
            send_sms_via_provider(phone)
            return None
        if settings.is_production:
            raise HTTPException(status_code=503, detail="短信服务尚未配置")
        code = settings.sms_test_code or f"{secrets.randbelow(1_000_000):06d}"
        redis.set(
            f"sms:code:login:{phone}",
            hash_sms_code(phone, "login", code),
            ex=settings.sms_code_expire_seconds,
        )
        redis.delete(f"sms:attempts:login:{phone}")
        return code if settings.sms_dev_expose_code else None
    except Exception:
        redis.delete(cooldown_key)
        raise


def consume_login_code(redis: Redis, phone: str, code: str) -> None:
    if not SMS_CODE_PATTERN.fullmatch(code):
        raise HTTPException(status_code=400, detail=GENERIC_SMS_ERROR)
    attempts_key = f"sms:attempts:login:{phone}"
    attempts = int(redis.incr(attempts_key))
    if attempts == 1:
        redis.expire(attempts_key, settings.sms_code_expire_seconds)
    if attempts > settings.sms_verify_attempt_limit:
        raise HTTPException(status_code=429, detail="验证失败次数过多，请重新获取验证码")

    replay_key = f"sms:consumed:login:{phone}:{hash_sms_code(phone, 'login', code)}"
    if _use_remote_sms():
        if redis.exists(replay_key) or not verify_sms_via_provider(phone, code):
            raise HTTPException(status_code=400, detail=GENERIC_SMS_ERROR)
        if not redis.set(replay_key, "1", nx=True, ex=settings.sms_code_expire_seconds):
            raise HTTPException(status_code=400, detail=GENERIC_SMS_ERROR)
        redis.delete(attempts_key)
        return

    code_key = f"sms:code:login:{phone}"
    expected = hash_sms_code(phone, "login", code)
    for _ in range(4):
        try:
            with redis.pipeline() as pipe:
                pipe.watch(code_key)
                stored = pipe.get(code_key)
                if not stored or not secrets.compare_digest(stored, expected):
                    pipe.unwatch()
                    raise HTTPException(status_code=400, detail=GENERIC_SMS_ERROR)
                pipe.multi()
                pipe.delete(code_key)
                pipe.delete(attempts_key)
                pipe.set(replay_key, "1", ex=settings.sms_code_expire_seconds)
                pipe.execute()
                return
        except WatchError:
            continue
    raise HTTPException(status_code=400, detail=GENERIC_SMS_ERROR)


@router.get("/config")
def auth_config() -> dict:
    return {
        "turnstile_site_key": settings.turnstile_site_key,
        "phone_country_code": "86",
        "refresh_days": settings.refresh_token_expire_days,
    }


@router.post("/sms/send")
async def sms_send(
    body: SmsSendRequest,
    request: Request,
    redis: Redis = Depends(get_redis),
) -> dict:
    if body.purpose != "login":
        raise HTTPException(status_code=400, detail="不支持的验证码用途")
    if not _use_remote_sms() and not is_loopback_request(request):
        raise HTTPException(status_code=503, detail="短信服务尚未配置")
    phone = normalize_phone(body.phone)
    debug_code = await send_login_code(redis, phone, client_ip(request), body.turnstile_token)
    payload = {"message": "验证码已发送"}
    if debug_code:
        payload["debug_code"] = debug_code
    return payload


@router.post("/login/sms", response_model=TokenResponse)
def login_sms(
    body: SmsLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    phone = normalize_phone(body.phone)
    consume_login_code(redis, phone, body.sms_code)
    user = db.scalar(select(User).where(User.phone == phone))
    if user and not user.is_active:
        raise HTTPException(status_code=403, detail="账号暂不可用")
    if not user:
        user = User(phone=phone)
        db.add(user)
        db.flush()
        if settings.demo_seed_new_users:
            seed_user_data(db, user)
        db.commit()
    access_token, refresh_token = create_session(db, user, request)
    set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=None)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse | Response:
    validate_cookie_origin(request)
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        return Response(status_code=204)
    session = db.scalar(
        select(AuthSession)
        .where(
            AuthSession.refresh_token_hash == hash_refresh_token(raw_token),
            AuthSession.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if not session or _as_utc(session.expires_at) <= utcnow():
        error_response = JSONResponse(status_code=401, content={"detail": "登录状态已失效"})
        clear_refresh_cookie(error_response)
        return error_response
    user = db.scalar(select(User).where(User.id == session.user_id, User.is_active.is_(True)))
    if not user:
        session.revoked_at = utcnow()
        db.commit()
        error_response = JSONResponse(status_code=401, content={"detail": "登录状态已失效"})
        clear_refresh_cookie(error_response)
        return error_response
    new_refresh = secrets.token_urlsafe(48)
    session.refresh_token_hash = hash_refresh_token(new_refresh)
    session.last_seen_at = utcnow()
    session.last_seen_ip = client_ip(request)
    db.commit()
    set_refresh_cookie(response, new_refresh)
    return TokenResponse(access_token=create_access_token(user, session.id))


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    validate_cookie_origin(request)
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_token:
        session = db.scalar(
            select(AuthSession).where(
                AuthSession.refresh_token_hash == hash_refresh_token(raw_token),
                AuthSession.revoked_at.is_(None),
            )
        )
        if session:
            session.revoked_at = utcnow()
            db.commit()
    clear_refresh_cookie(response)
    return {"message": "已退出登录"}


@router.get("/me")
def me(auth: AuthContext = Depends(get_current_auth)) -> dict:
    return {
        "id": auth.user.id,
        "phone": auth.user.phone,
        "display_name": auth.user.display_name,
        "masked_phone": f"{auth.user.phone[:3]}****{auth.user.phone[-4:]}",
        "created_at": auth.user.created_at.isoformat(),
    }


@router.patch("/me")
def update_me(
    body: ProfileUpdateRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    display_name = re.sub(r"\s+", " ", body.display_name).strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="请输入用户名")
    if len(display_name) > 40:
        raise HTTPException(status_code=400, detail="用户名不能超过 40 个字符")
    auth.user.display_name = display_name
    db.commit()
    return me(auth)


@router.get("/sessions")
def sessions(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    rows = list(
        db.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == auth.user.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
            .order_by(AuthSession.last_seen_at.desc())
        )
    )
    return {
        "sessions": [
            {
                "id": row.id,
                "device_name": row.device_name,
                "created_ip": row.created_ip,
                "last_seen_ip": row.last_seen_ip,
                "created_at": row.created_at.isoformat(),
                "last_seen_at": row.last_seen_at.isoformat(),
                "expires_at": row.expires_at.isoformat(),
                "current": row.id == auth.payload["sid"],
            }
            for row in rows
        ]
    }


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: str,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> dict:
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == auth.user.id,
            AuthSession.revoked_at.is_(None),
        )
    )
    if not session:
        raise HTTPException(status_code=404, detail="设备会话不存在")
    session.revoked_at = utcnow()
    db.commit()
    return {"revoked": session_id, "current": session_id == auth.payload["sid"]}
