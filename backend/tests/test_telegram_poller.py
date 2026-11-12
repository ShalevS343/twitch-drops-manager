"""Worker Telegram long-poll behaviour."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.domain.models import AppMeta, TelegramLinkCode, User, UserCampaignStart
from app.providers.telegram import TelegramConflictError
from app.services.telegram_link_service import TelegramLinkService
from app.worker.telegram_poller import TelegramPoller
from tests.support import create_user, make_engine

BOT_TOKEN = "123456:super-secret-bot-token"


class FakePollingTelegram:
    configured = True

    def __init__(self, batches: list[list[dict]] | None = None):
        self.batches = list(batches or [])
        self.offsets: list[int | None] = []
        self.sent: list[tuple[str, str]] = []
        self.on_empty = None

    async def get_me(self) -> dict:
        return {"username": "raspberrypitwitchbot"}

    async def get_updates(self, offset, timeout=25):
        self.offsets.append(offset)
        if self.batches:
            return self.batches.pop(0)
        if self.on_empty is not None:
            await self.on_empty()
        return []

    async def send(self, message: str, chat_id: str) -> None:
        self.sent.append((chat_id, message))


class ConflictTelegram(FakePollingTelegram):
    async def get_updates(self, offset, timeout=25):
        self.offsets.append(offset)
        raise TelegramConflictError(
            "Telegram polling conflict: a webhook is set for this bot"
        )


def _message(
    update_id: int,
    text: str,
    *,
    chat_id: int = 42,
    chat_type: str = "private",
) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "text": text,
            "chat": {"id": chat_id, "type": chat_type},
        },
    }


async def _run(poller: TelegramPoller, provider: FakePollingTelegram) -> None:
    async def stop_when_idle() -> None:
        await poller.stop()

    provider.on_empty = stop_when_idle
    await asyncio.wait_for(poller.run(), timeout=2)


async def _user_with_link(factory, provider, **kwargs) -> tuple[int, str]:
    async with factory() as session:
        user = await create_user(session, twitch_user_id="1", login="one", **kwargs)
        await session.commit()
        out = await TelegramLinkService(session, provider=provider).create_link(
            user.id
        )
        return user.id, out.deep_link.rsplit("start=", 1)[1]


async def _offset(factory) -> str | None:
    async with factory() as session:
        row = await session.get(AppMeta, "telegram_update_offset")
        return row.value if row is not None else None


@pytest.mark.asyncio
async def test_start_with_code_links_the_private_chat_and_persists_offset():
    engine, factory = await make_engine()
    provider = FakePollingTelegram()
    user_id, code = await _user_with_link(factory, provider)
    provider.batches = [[_message(10, f"/start {code}")]]

    poller = TelegramPoller(provider, factory)
    await _run(poller, provider)

    assert provider.sent == [
        (
            "42",
            (
                "Connected to Twitch Drops Manager as one. "
                "Alerts are on. Send /stop to stop alerts."
            ),
        )
    ]
    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.telegram_chat_id == "42"
        assert user.telegram_enabled is True
        link = (await session.execute(select(TelegramLinkCode))).scalar_one()
        assert link.used_at is not None
    assert await _offset(factory) == "11"

    await engine.dispose()


@pytest.mark.asyncio
async def test_start_without_a_code_points_to_the_link_flow():
    engine, factory = await make_engine()
    provider = FakePollingTelegram([[_message(5, "/start")]])

    poller = TelegramPoller(provider, factory)
    await _run(poller, provider)

    assert len(provider.sent) == 1
    chat_id, message = provider.sent[0]
    assert chat_id == "42"
    assert "not linked" in message.lower()
    assert "settings" in message.lower()
    assert "connect telegram" in message.lower()

    await engine.dispose()


@pytest.mark.asyncio
async def test_start_without_a_code_reenables_alerts_for_a_linked_chat():
    engine, factory = await make_engine()
    async with factory() as session:
        user = await create_user(
            session,
            twitch_user_id="1",
            login="one",
            telegram_chat_id="42",
            telegram_enabled=False,
        )
        await session.commit()
        user_id = user.id
    provider = FakePollingTelegram([[_message(5, "/start")]])

    poller = TelegramPoller(provider, factory)
    await _run(poller, provider)

    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.telegram_enabled is True
        assert user.telegram_chat_id == "42"
    assert provider.sent == [("42", "Alerts are on.")]

    await engine.dispose()


@pytest.mark.asyncio
async def test_stop_disables_alerts_for_the_matching_chat():
    engine, factory = await make_engine()
    async with factory() as session:
        user = await create_user(
            session,
            twitch_user_id="1",
            login="one",
            telegram_chat_id="42",
            telegram_enabled=True,
        )
        await session.commit()
        user_id = user.id
    provider = FakePollingTelegram([[_message(7, "/stop")]])

    poller = TelegramPoller(provider, factory)
    await _run(poller, provider)

    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.telegram_enabled is False
        assert user.telegram_chat_id == "42"
    assert len(provider.sent) == 1
    assert "off" in provider.sent[0][1].lower()

    await engine.dispose()


@pytest.mark.asyncio
async def test_unlink_clears_the_chat_and_pending_starts():
    engine, factory = await make_engine()
    async with factory() as session:
        user = await create_user(
            session,
            twitch_user_id="1",
            login="one",
            telegram_chat_id="42",
            telegram_enabled=True,
        )
        session.add(UserCampaignStart(user_id=user.id, external_id="campaign-1"))
        await session.commit()
        user_id = user.id
    provider = FakePollingTelegram([[_message(8, "/unlink")]])

    poller = TelegramPoller(provider, factory)
    await _run(poller, provider)

    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.telegram_chat_id == ""
        assert user.telegram_enabled is False
        starts = (
            await session.execute(
                select(UserCampaignStart).where(
                    UserCampaignStart.user_id == user_id
                )
            )
        ).scalars().all()
        assert starts == []
    assert len(provider.sent) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_group_chats_are_ignored_and_never_link():
    engine, factory = await make_engine()
    provider = FakePollingTelegram()
    user_id, code = await _user_with_link(factory, provider)
    provider.batches = [
        [_message(9, f"/start {code}", chat_id=-100, chat_type="group")]
    ]

    poller = TelegramPoller(provider, factory)
    await _run(poller, provider)

    async with factory() as session:
        user = await session.get(User, user_id)
        assert user.telegram_chat_id == ""
        assert user.telegram_enabled is False
    assert provider.sent == []
    assert await _offset(factory) == "10"

    await engine.dispose()


@pytest.mark.asyncio
async def test_a_restarted_poller_resumes_from_the_persisted_offset():
    engine, factory = await make_engine()
    first = FakePollingTelegram([[_message(10, "/start")]])
    first_poller = TelegramPoller(first, factory)
    await _run(first_poller, first)

    second = FakePollingTelegram()
    second_poller = TelegramPoller(second, factory)
    await _run(second_poller, second)

    assert second.offsets[0] == 11

    await engine.dispose()


@pytest.mark.asyncio
async def test_409_conflict_is_logged_and_does_not_crash(caplog):
    engine, factory = await make_engine()
    provider = ConflictTelegram()
    poller = TelegramPoller(provider, factory)

    with caplog.at_level("ERROR", logger="app.worker.telegram_poller"):
        await asyncio.wait_for(poller.run(), timeout=2)

    text = caplog.text.lower()
    assert "webhook" in text
    assert BOT_TOKEN not in caplog.text
    assert await _offset(factory) is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_reply_cooldown_suppresses_repeated_spam_for_one_chat():
    engine, factory = await make_engine()
    provider = FakePollingTelegram(
        [[_message(100 + index, "/start") for index in range(12)]]
    )

    poller = TelegramPoller(provider, factory)
    await _run(poller, provider)

    # Ten replies per chat per minute; the remaining updates are processed but
    # do not generate more outbound messages.
    assert len(provider.sent) == 10
    assert {chat_id for chat_id, _message_text in provider.sent} == {"42"}
    assert await _offset(factory) == "112"

    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_updates_and_send_failures_do_not_stop_the_poller():
    engine, factory = await make_engine()
    async with factory() as session:
        await create_user(
            session,
            twitch_user_id="1",
            login="one",
            telegram_chat_id="42",
            telegram_enabled=True,
        )
        await session.commit()

    class FailingSend(FakePollingTelegram):
        async def send(self, message: str, chat_id: str) -> None:
            from app.core.exceptions import ProviderError

            raise ProviderError("Telegram request failed (ConnectError)")

    provider = FailingSend(
        [
            [
                {"update_id": 11, "message": {"text": "/stop", "chat": {"id": 42, "type": "private"}}},
                {"update_id": 12, "edited_message": {}},
                _message(13, "/unknown-command"),
            ]
        ]
    )
    poller = TelegramPoller(provider, factory)
    await _run(poller, provider)

    assert await _offset(factory) == "14"

    await engine.dispose()


@pytest.mark.asyncio
async def test_offset_save_failure_does_not_terminate_the_next_iteration(
    monkeypatch, caplog
):
    from app.worker import telegram_poller as poller_module

    monkeypatch.setattr(poller_module, "INITIAL_BACKOFF_SECONDS", 0.01)
    engine, factory = await make_engine()
    provider = FakePollingTelegram(
        [[_message(10, "hello")], [_message(11, "hello")]]
    )

    class FailingSavePoller(TelegramPoller):
        def __init__(self, provider, factory):
            super().__init__(provider, factory)
            self.remaining_failures = 1

        async def _save_offset(self, offset):
            if self.remaining_failures:
                self.remaining_failures -= 1
                raise RuntimeError("database unavailable")
            await super()._save_offset(offset)

    poller = FailingSavePoller(provider, factory)
    with caplog.at_level("WARNING", logger="app.worker.telegram_poller"):
        await _run(poller, provider)

    assert provider.offsets == [None, 11, 12]
    assert await _offset(factory) == "12"
    assert "RuntimeError" in caplog.text
    assert "database unavailable" not in caplog.text

    await engine.dispose()


@pytest.mark.asyncio
async def test_poll_errors_back_off_exponentially_with_a_cap(monkeypatch):
    from app.worker import telegram_poller as poller_module

    monkeypatch.setattr(poller_module, "INITIAL_BACKOFF_SECONDS", 5.0)
    monkeypatch.setattr(poller_module, "MAX_BACKOFF_SECONDS", 15.0)
    engine, factory = await make_engine()

    class AlwaysFailing(FakePollingTelegram):
        async def get_updates(self, offset, timeout=25):
            from app.core.exceptions import ProviderError

            self.offsets.append(offset)
            raise ProviderError("temporary failure")

    provider = AlwaysFailing()
    poller = TelegramPoller(provider, factory)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 4:
            await poller.stop()

    poller._sleep = fake_sleep  # type: ignore[method-assign]
    await asyncio.wait_for(poller.run(), timeout=2)

    assert sleeps == [5.0, 10.0, 15.0, 15.0]

    await engine.dispose()
