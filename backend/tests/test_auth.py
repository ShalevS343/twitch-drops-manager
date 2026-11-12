from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.config import Settings
from app.core.db import Base
from app.core.exceptions import (
    AccountConflictError,
    AccountDisabledError,
    InvalidAuthRequestError,
    LastAdminError,
    ProviderError,
    RegistrationClosedError,
)
from app.core.middleware import CSRFMiddleware, NoStoreMiddleware
from app.core.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    clear_auth_cookies,
    compare_secrets,
    create_auth_session,
    get_current_user,
    get_optional_user,
    hash_token,
    new_opaque_token,
    prune_expired_sessions,
    set_auth_cookies,
)
from app.domain.models import (
    TwitchAccount,
    UserCampaignStart,
    UserDropProgress,
    UserNotification,
    UserSession,
    UserWatchFocus,
)
from app.repositories.user_games import UserGameRepository
from app.repositories.users import UserRepository
from app.services.auth_service import AuthService, RegistrationState


class FakeTwitchProvider:
    def __init__(self, info=None, profile=None, token="token", error=None):
        self.info = info or {
            "client_id": "client",
            "user_id": "123",
            "login": "viewer",
            "expires_in": 3600,
        }
        self.profile = profile or {}
        self.token = token
        self.error = error
        self.profile_error = None
        self.profile_calls = []

    def parse_oauth_token(self, _value):
        return self.token

    async def validate(self, _token):
        if self.error is not None:
            raise self.error
        return dict(self.info)

    async def fetch_profile(self, access_token, user_id=""):
        self.profile_calls.append((access_token, user_id))
        if self.profile_error is not None:
            raise self.profile_error
        return dict(self.profile)


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "registration_code": "",
        "registration_open": False,
        "default_games": "",
        "telegram_chat_id": "",
        "twitch_gql_client_id": "client",
        "session_ttl_days": 30,
    }
    values.update(overrides)
    return Settings(**values)


def _request(
    *,
    path: str = "/api/v1/auth/me",
    method: str = "GET",
    cookies: dict[str, str] | None = None,
    scheme: str = "http",
    host: str = "testserver",
) -> Request:
    headers = []
    if cookies:
        header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        headers.append((b"cookie", header.encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": scheme,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": (host, 80),
    }
    return Request(scope)


class FakeResponse:
    def __init__(self) -> None:
        self.cookies: dict[str, dict[str, object]] = {}

    def set_cookie(self, key, value, **kwargs):
        self.cookies[key] = {"value": value, **kwargs}

    def delete_cookie(self, key, **kwargs):
        self.cookies[key] = {"deleted": True, **kwargs}


@pytest.mark.asyncio
async def test_first_user_becomes_admin_and_token_is_saved():
    engine, factory = await _session()
    provider = FakeTwitchProvider(
        profile={
            "displayName": "Viewer Name",
            "profileImageURL": "https://example.test/avatar.png",
        }
    )

    async with factory() as session:
        service = AuthService(session, settings=_settings(), provider=provider)
        result = await service.connect("https://twitch.tv/#access_token=token", "")

        assert result.created is True
        assert result.user.role == "admin"
        assert result.user.twitch_user_id == "123"
        assert result.user.login == "viewer"
        assert result.user.display_name == "Viewer Name"
        assert result.user.profile_image_url == "https://example.test/avatar.png"
        assert result.user.last_login_at is not None

        account = result.user
        assert account.is_active is True

        stored = (
            await session.execute(
                select(UserSession).where(UserSession.user_id == result.user.id)
            )
        ).scalar_one()
        assert stored.token_hash == hash_token(result.session_token)
        assert stored.token_hash != result.session_token
        assert stored.csrf_token_hash == hash_token(result.csrf_token)
        assert stored.expires_at.replace(tzinfo=timezone.utc) > datetime.now(
            timezone.utc
        )
        assert provider.profile_calls == [("token", "123")]

    await engine.dispose()


@pytest.mark.asyncio
async def test_second_user_requires_a_valid_invite_code(monkeypatch):
    engine, factory = await _session()
    calls: list[tuple[str, str]] = []

    def fake_compare(left, right):
        calls.append((left, right))
        return left == right

    monkeypatch.setattr("app.services.auth_service.compare_secrets", fake_compare)
    settings = _settings(registration_code="secret-code")

    async with factory() as session:
        first = FakeTwitchProvider()
        await AuthService(session, settings=settings, provider=first).connect("url", "")

        second = FakeTwitchProvider(
            info={
                "client_id": "client",
                "user_id": "456",
                "login": "second",
                "expires_in": 3600,
            }
        )
        service = AuthService(session, settings=settings, provider=second)

        with pytest.raises(RegistrationClosedError):
            await service.connect("url", "wrong-code")

        result = await service.connect("url", "secret-code")
        assert result.created is True
        assert result.user.role == "user"
        assert calls == [("secret-code", "wrong-code"), ("secret-code", "secret-code")]

    await engine.dispose()


@pytest.mark.asyncio
async def test_registration_is_closed_when_code_is_empty():
    engine, factory = await _session()
    settings = _settings(registration_open=False)

    async with factory() as session:
        await AuthService(
            session, settings=settings, provider=FakeTwitchProvider()
        ).connect("url", "")

        service = AuthService(
            session,
            settings=settings,
            provider=FakeTwitchProvider(
                info={
                    "client_id": "client",
                    "user_id": "456",
                    "login": "second",
                    "expires_in": 3600,
                }
            ),
        )
        with pytest.raises(RegistrationClosedError):
            await service.connect("url", "")

    await engine.dispose()


@pytest.mark.asyncio
async def test_explicit_open_registration_allows_a_new_user():
    engine, factory = await _session()
    settings = _settings(registration_open=True)

    async with factory() as session:
        await AuthService(
            session, settings=settings, provider=FakeTwitchProvider()
        ).connect("url", "")
        result = await AuthService(
            session,
            settings=settings,
            provider=FakeTwitchProvider(
                info={
                    "client_id": "client",
                    "user_id": "456",
                    "login": "second",
                    "expires_in": 3600,
                }
            ),
        ).connect("url", "")
        assert result.user.role == "user"

    await engine.dispose()


@pytest.mark.asyncio
async def test_existing_user_logs_in_without_creating_a_duplicate():
    engine, factory = await _session()
    settings = _settings(registration_code="secret-code", default_games="Rust")

    async with factory() as session:
        first = await AuthService(
            session, settings=settings, provider=FakeTwitchProvider()
        ).connect("url", "")
        second = await AuthService(
            session, settings=settings, provider=FakeTwitchProvider()
        ).connect("url", "ignored")

        assert second.created is False
        assert second.user.id == first.user.id
        assert (await UserRepository(session).count()) == 1
        assert len(await UserGameRepository(session).selected_names(second.user.id)) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_inactive_user_is_rejected():
    engine, factory = await _session()

    async with factory() as session:
        settings = _settings()
        first = await AuthService(
            session, settings=settings, provider=FakeTwitchProvider()
        ).connect("url", "")
        await UserRepository(session).set_active(first.user, False)
        await session.commit()

        with pytest.raises(AccountDisabledError):
            await AuthService(
                session, settings=settings, provider=FakeTwitchProvider()
            ).connect("url", "")

    await engine.dispose()


@pytest.mark.asyncio
async def test_connecting_a_different_twitch_account_while_signed_in_conflicts():
    engine, factory = await _session()

    async with factory() as session:
        settings = _settings(registration_open=True)
        first = await AuthService(
            session, settings=settings, provider=FakeTwitchProvider()
        ).connect("url", "")

        other = FakeTwitchProvider(
            info={
                "client_id": "client",
                "user_id": "456",
                "login": "other",
                "expires_in": 3600,
            }
        )
        with pytest.raises(AccountConflictError):
            await AuthService(session, settings=settings, provider=other).connect(
                "url", "", current_user=first.user
            )

    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "info",
    [
        {"client_id": "client", "login": "viewer", "expires_in": 3600},
        {"client_id": "client", "user_id": "123", "expires_in": 3600},
    ],
)
async def test_missing_twitch_identity_fields_are_rejected(info):
    engine, factory = await _session()

    async with factory() as session:
        service = AuthService(
            session,
            settings=_settings(),
            provider=FakeTwitchProvider(info=info),
        )
        with pytest.raises(InvalidAuthRequestError):
            await service.connect("url", "")

    await engine.dispose()


@pytest.mark.asyncio
async def test_profile_failure_falls_back_to_login_name():
    engine, factory = await _session()
    provider = FakeTwitchProvider()
    provider.profile_error = ProviderError("twitch down")

    async with factory() as session:
        result = await AuthService(
            session, settings=_settings(), provider=provider
        ).connect("url", "")
        assert result.user.display_name == "viewer"

    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_session_is_rejected():
    engine, factory = await _session()

    async with factory() as session:
        user = await UserRepository(session).create(
            twitch_user_id="123", login="viewer"
        )
        token, csrf, _ = await create_auth_session(session, user.id, ttl_days=-1)
        await session.commit()

    async with factory() as session:
        request = _request(cookies={SESSION_COOKIE: token, CSRF_COOKIE: csrf})
        assert await get_optional_user(request, session) is None
        with pytest.raises(HTTPException) as excinfo:
            await get_current_user(request, session)
        assert excinfo.value.status_code == 401

    await engine.dispose()


@pytest.mark.asyncio
async def test_disabled_user_session_is_rejected():
    engine, factory = await _session()

    async with factory() as session:
        repo = UserRepository(session)
        user = await repo.create(twitch_user_id="123", login="viewer")
        token, csrf, _ = await create_auth_session(session, user.id, ttl_days=1)
        await repo.set_active(user, False)
        await session.commit()

    async with factory() as session:
        request = _request(cookies={SESSION_COOKIE: token, CSRF_COOKIE: csrf})
        assert await get_optional_user(request, session) is None
        with pytest.raises(HTTPException) as excinfo:
            await get_current_user(request, session)
        assert excinfo.value.status_code == 401

    await engine.dispose()


@pytest.mark.asyncio
async def test_logout_deletes_only_that_session():
    engine, factory = await _session()

    async with factory() as session:
        user = await UserRepository(session).create(
            twitch_user_id="123", login="viewer"
        )
        first_token, _, _ = await create_auth_session(session, user.id, 30)
        second_token, _, _ = await create_auth_session(session, user.id, 30)
        await session.commit()

        service = AuthService(session, settings=_settings(), provider=FakeTwitchProvider())
        await service.logout(first_token)

        remaining = (
            await session.execute(select(UserSession))
        ).scalars().all()
        assert len(remaining) == 1
        assert remaining[0].token_hash == hash_token(second_token)

    await engine.dispose()


@pytest.mark.asyncio
async def test_disconnect_clears_personal_data_but_keeps_user():
    engine, factory = await _session()

    async with factory() as session:
        user = await UserRepository(session).create(
            twitch_user_id="123", login="viewer"
        )
        session.add_all(
            [
                UserDropProgress(user_id=user.id, drop_id="drop-1"),
                UserNotification(user_id=user.id, dedupe_key="key"),
                UserCampaignStart(user_id=user.id, external_id="campaign-1"),
                UserWatchFocus(user_id=user.id, enabled=True),
            ]
        )
        await session.flush()

        service = AuthService(session, settings=_settings(), provider=FakeTwitchProvider())
        await service.disconnect(user.id)

        for model in (
            UserDropProgress,
            UserNotification,
            UserCampaignStart,
            UserWatchFocus,
        ):
            rows = (await session.execute(select(model))).scalars().all()
            assert rows == []
        assert await UserRepository(session).get(user.id) is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_disabling_telegram_clears_pending_campaign_starts():
    engine, factory = await _session()

    async with factory() as session:
        user = await UserRepository(session).create(
            twitch_user_id="123", login="viewer"
        )
        session.add(UserCampaignStart(user_id=user.id, external_id="campaign-1"))
        await session.flush()

        service = AuthService(session, settings=_settings(), provider=FakeTwitchProvider())
        updated = await service.update_telegram(user.id, "555", False)

        assert updated.telegram_chat_id == "555"
        assert updated.telegram_enabled is False
        rows = (await session.execute(select(UserCampaignStart))).scalars().all()
        assert rows == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_disabling_telegram_only_clears_that_users_pending_starts():
    engine, factory = await _session()

    async with factory() as session:
        first = await UserRepository(session).create(
            twitch_user_id="123", login="first"
        )
        second = await UserRepository(session).create(
            twitch_user_id="456", login="second"
        )
        session.add_all(
            [
                UserCampaignStart(user_id=first.id, external_id="campaign-1"),
                UserCampaignStart(user_id=second.id, external_id="campaign-2"),
            ]
        )
        await session.commit()

        service = AuthService(session, settings=_settings(), provider=FakeTwitchProvider())
        await service.update_telegram(first.id, "", False)

        rows = (await session.execute(select(UserCampaignStart))).scalars().all()
        assert {row.user_id for row in rows} == {second.id}

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconnecting_clears_the_reconnect_required_flag():
    engine, factory = await _session()

    async with factory() as session:
        user = await UserRepository(session).create(
            twitch_user_id="123", login="viewer"
        )
        session.add(
            TwitchAccount(
                user_id=user.id,
                access_token="expired-token",
                reconnect_required=True,
                last_error="Twitch login expired; reconnect your account",
            )
        )
        await session.commit()

        service = AuthService(session, settings=_settings(), provider=FakeTwitchProvider())
        await service.connect("url")
        await session.commit()

        account = (
            await session.execute(
                select(TwitchAccount).where(TwitchAccount.user_id == user.id)
            )
        ).scalar_one()
        assert account.reconnect_required is False
        assert account.last_error == ""
        assert account.access_token == "token"

    await engine.dispose()


@pytest.mark.asyncio
async def test_registration_state_matches_the_registration_table():
    engine, factory = await _session()

    async with factory() as session:
        service = AuthService(session, settings=_settings(), provider=FakeTwitchProvider())
        assert await service.registration_state() == RegistrationState(
            open=True, invite_required=False
        )

        await UserRepository(session).create(twitch_user_id="123", login="viewer")
        await session.commit()

        assert await service.registration_state() == RegistrationState(
            open=False, invite_required=False
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_whitespace_registration_code_is_treated_as_empty():
    engine, factory = await _session()

    async with factory() as session:
        await UserRepository(session).create(twitch_user_id="123", login="viewer")
        await session.commit()
        service = AuthService(
            session,
            settings=_settings(registration_code="   ", registration_open=False),
            provider=FakeTwitchProvider(),
        )
        assert await service.registration_state() == RegistrationState(
            open=False, invite_required=False
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_registration_state_reports_invite_required():
    engine, factory = await _session()

    async with factory() as session:
        await UserRepository(session).create(twitch_user_id="123", login="viewer")
        await session.commit()
        service = AuthService(
            session,
            settings=_settings(registration_code="secret"),
            provider=FakeTwitchProvider(),
        )
        state = await service.registration_state()
        assert state.open is True
        assert state.invite_required is True

    await engine.dispose()


def test_auth_cookies_use_forwarded_scheme_and_csrf_is_readable():
    response = FakeResponse()
    request = _request(scheme="https")

    set_auth_cookies(response, request, "session-token", "csrf-token", 3600)

    session_cookie = response.cookies[SESSION_COOKIE]
    csrf_cookie = response.cookies[CSRF_COOKIE]
    assert session_cookie["httponly"] is True
    assert session_cookie["secure"] is True
    assert session_cookie["samesite"] == "lax"
    assert session_cookie["path"] == "/"
    assert session_cookie["max_age"] == 3600
    assert csrf_cookie["httponly"] is False
    assert csrf_cookie["secure"] is True

    clear_auth_cookies(response)
    assert response.cookies[SESSION_COOKIE]["deleted"] is True
    assert response.cookies[CSRF_COOKIE]["deleted"] is True


def test_cookie_secure_setting_can_force_http_cookies():
    response = FakeResponse()
    request = _request(scheme="https")

    set_auth_cookies(
        response,
        request,
        "session-token",
        "csrf-token",
        3600,
        settings=_settings(session_cookie_secure="false"),
    )
    assert response.cookies[SESSION_COOKIE]["secure"] is False


def test_compare_secrets_handles_non_ascii_values():
    assert compare_secrets("café", "café") is True
    assert compare_secrets("café", "cafe") is False
    assert compare_secrets("", "é") is False


@pytest.mark.asyncio
async def test_non_ascii_invite_code_is_compared_safely():
    engine, factory = await _session()
    settings = _settings(registration_code="café")

    async with factory() as session:
        await UserRepository(session).create(twitch_user_id="123", login="viewer")
        await session.commit()

        provider = FakeTwitchProvider(
            info={
                "client_id": "client",
                "user_id": "456",
                "login": "second",
                "expires_in": 3600,
            }
        )
        result = await AuthService(
            session, settings=settings, provider=provider
        ).connect("url", "café")
        assert result.created is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_first_admin_claim_prevents_a_second_admin():
    engine, factory = await _session()
    settings = _settings(registration_open=True)

    async with factory() as session:
        first = await AuthService(
            session,
            settings=settings,
            provider=FakeTwitchProvider(),
        ).connect("url", "")
        second = await AuthService(
            session,
            settings=settings,
            provider=FakeTwitchProvider(
                info={
                    "client_id": "client",
                    "user_id": "456",
                    "login": "second",
                    "expires_in": 3600,
                }
            ),
        ).connect("url", "")

        assert first.user.role == "admin"
        assert second.user.role == "user"

    await engine.dispose()


@pytest.mark.asyncio
async def test_last_active_admin_cannot_be_disabled():
    engine, factory = await _session()

    async with factory() as session:
        admin = await UserRepository(session).create(
            twitch_user_id="123", login="admin", role="admin"
        )
        await session.commit()
        service = AuthService(session, settings=_settings(), provider=FakeTwitchProvider())

        with pytest.raises(LastAdminError):
            await service.set_user_active(admin.id, False)

        assert (await UserRepository(session).get(admin.id)).is_active is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_prune_expired_sessions_deletes_only_expired_rows():
    engine, factory = await _session()

    async with factory() as session:
        user = await UserRepository(session).create(
            twitch_user_id="123", login="viewer"
        )
        await create_auth_session(session, user.id, ttl_days=-1)
        await create_auth_session(session, user.id, ttl_days=30)
        await session.commit()

        await prune_expired_sessions(session)

        remaining = (await session.execute(select(UserSession))).scalars().all()
        assert len(remaining) == 1
        assert remaining[0].expires_at.replace(tzinfo=timezone.utc) > datetime.now(
            timezone.utc
        )

    await engine.dispose()


def test_opaque_tokens_are_unique_and_hashes_are_stable():
    first = new_opaque_token()
    second = new_opaque_token()
    assert first != second
    assert len(first) >= 32
    assert hash_token(first) == hash_token(first)
    assert hash_token(first) != first
    assert len(hash_token(first)) == 64


@pytest.mark.asyncio
async def test_user_repository_lookup_and_telegram_update():
    engine, factory = await _session()

    async with factory() as session:
        repo = UserRepository(session)
        user = await repo.create(twitch_user_id="123", login="viewer")
        await session.commit()

        assert await repo.get(user.id) is not None
        assert await repo.get_by_twitch_id("123") is not None
        assert await repo.get_by_twitch_id("missing") is None
        assert await repo.count() == 1
        assert [row.id for row in await repo.list()] == [user.id]

        updated = await repo.set_telegram(user, "555", True)
        await session.commit()
        assert updated.telegram_chat_id == "555"
        assert updated.telegram_enabled is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_user_game_repository_creates_games_and_replaces_selection():
    engine, factory = await _session()

    async with factory() as session:
        user = await UserRepository(session).create(
            twitch_user_id="123", login="viewer"
        )
        await session.commit()
        repo = UserGameRepository(session)

        selected = await repo.replace(user.id, ["Rust", "Minecraft"])
        await session.commit()
        assert {game.name for game in selected} == {"Rust", "Minecraft"}
        assert set(await repo.selected_names(user.id)) == {"Rust", "Minecraft"}

        selected = await repo.replace(user.id, ["Rust"])
        await session.commit()
        assert [game.name for game in selected] == ["Rust"]
        assert await repo.selected_names(user.id) == ["Rust"]

    await engine.dispose()


async def _ok(_request):
    return JSONResponse({"ok": True})


def _middleware_app():
    app = Starlette(routes=[Route("/api/v1/thing", _ok, methods=["POST", "GET"])])
    app.add_middleware(CSRFMiddleware)
    return app


@pytest.mark.asyncio
async def test_csrf_token_mismatch_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.core.middleware.get_settings", lambda: _settings(cors_origins="")
    )
    transport = ASGITransport(app=_middleware_app())

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/thing",
            headers={
                "Cookie": "tdm_session=session; tdm_csrf=expected",
                "X-CSRF-Token": "wrong",
                "Origin": "http://testserver",
            },
        )
        assert response.status_code == 403

        response = await client.post(
            "/api/v1/thing",
            headers={
                "Cookie": "tdm_session=session; tdm_csrf=expected",
                "X-CSRF-Token": "expected",
                "Origin": "http://testserver",
            },
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_csrf_is_required_when_the_session_cookie_is_present(monkeypatch):
    monkeypatch.setattr(
        "app.core.middleware.get_settings", lambda: _settings(cors_origins="")
    )
    transport = ASGITransport(app=_middleware_app())

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/thing",
            headers={
                "Cookie": "tdm_session=session",
                "Origin": "http://testserver",
            },
        )
        assert response.status_code == 403

        response = await client.post(
            "/api/v1/thing", headers={"Origin": "http://testserver"}
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_csrf_accepts_matching_non_ascii_cookie_and_header(monkeypatch):
    monkeypatch.setattr(
        "app.core.middleware.get_settings", lambda: _settings(cors_origins="")
    )
    # HTTP header values arrive as latin-1 bytes; build the ASGI scope directly
    # because httpx refuses to encode non-ASCII header strings.
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/thing",
        "raw_path": b"/api/v1/thing",
        "query_string": b"",
        "headers": [
            (b"cookie", "tdm_session=session; tdm_csrf=café".encode("latin-1")),
            (b"x-csrf-token", "café".encode("latin-1")),
            (b"origin", b"http://testserver"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }

    async def call_next(_request):
        return JSONResponse({"ok": True})

    response = await CSRFMiddleware(app=None).dispatch(Request(scope), call_next)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_csrf_is_skipped_for_the_public_connect_endpoint(monkeypatch):
    monkeypatch.setattr(
        "app.core.middleware.get_settings", lambda: _settings(cors_origins="")
    )
    app = Starlette(
        routes=[
            Route(
                "/api/v1/auth/twitch/connect",
                _ok,
                methods=["POST"],
            )
        ]
    )
    app.add_middleware(CSRFMiddleware)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/auth/twitch/connect",
            headers={
                "Cookie": "tdm_session=session; tdm_csrf=expected",
                "X-CSRF-Token": "wrong",
            },
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_untrusted_origin_is_rejected_for_unsafe_methods(monkeypatch):
    monkeypatch.setattr(
        "app.core.middleware.get_settings",
        lambda: _settings(public_origin="https://drops.example"),
    )
    transport = ASGITransport(app=_middleware_app())

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/thing",
            headers={
                "Cookie": "tdm_session=session; tdm_csrf=expected",
                "X-CSRF-Token": "expected",
                "Origin": "https://evil.example",
            },
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_no_store_is_added_to_authenticated_api_responses(monkeypatch):
    app = Starlette(routes=[Route("/api/v1/thing", _ok, methods=["GET"])])
    app.add_middleware(NoStoreMiddleware)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/api/v1/thing", headers={"Cookie": "tdm_session=session"}
        )
        assert response.headers["cache-control"] == "no-store"

        response = await client.get("/api/v1/thing")
        assert "cache-control" not in response.headers
