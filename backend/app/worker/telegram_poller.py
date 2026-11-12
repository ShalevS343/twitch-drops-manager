"""Long-poll Telegram updates for auto-linking and alert commands."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotConfiguredError, ProviderError
from app.domain.models import AppMeta
from app.providers.telegram import TelegramConflictError, TelegramProvider
from app.services.telegram_link_service import TelegramLinkService

logger = logging.getLogger(__name__)

OFFSET_KEY = "telegram_update_offset"
POLL_TIMEOUT = 25
INITIAL_BACKOFF_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 300.0


class TelegramPoller:
    """Consume ``getUpdates`` and answer /start, /stop, and /unlink.

    One instance lives for the worker process. The update offset is persisted
    in ``app_meta`` so a restart does not replay old commands.
    """

    def __init__(
        self,
        provider: TelegramProvider,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        self.provider = provider
        self.session_factory = session_factory
        self._stopped = asyncio.Event()

    async def stop(self) -> None:
        self._stopped.set()

    async def run(self) -> None:
        if not self.provider.configured:
            logger.info("Telegram poller disabled: bot token is not configured")
            return

        offset: int | None = None
        offset_loaded = False
        backoff = INITIAL_BACKOFF_SECONDS
        while not self._stopped.is_set():
            try:
                if not offset_loaded:
                    offset = await self._load_offset()
                    offset_loaded = True

                updates = await self.provider.get_updates(
                    offset, timeout=POLL_TIMEOUT
                )

                for update in updates:
                    if not isinstance(update, dict):
                        continue
                    try:
                        await self._handle_update(update)
                    except Exception as exc:  # noqa: BLE001 - keep polling
                        # Never log update text or the bot token; only the type.
                        logger.warning(
                            "Telegram update handling failed (%s)",
                            type(exc).__name__,
                        )
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = max(offset or 0, update_id + 1)

                if updates:
                    await self._save_offset(offset)
                backoff = INITIAL_BACKOFF_SECONDS
            except TelegramConflictError as exc:
                logger.error(
                    "Telegram poller stopped: %s. Delete the bot webhook "
                    "(deleteWebhook) or disable the worker poller, then restart.",
                    exc,
                )
                return
            except NotConfiguredError:
                logger.info("Telegram poller disabled: bot token is not configured")
                return
            except Exception as exc:  # noqa: BLE001 - DB/provider hiccups
                # Never log update text or the bot token; only the error type.
                logger.warning(
                    "Telegram polling failed (%s)", type(exc).__name__
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    async def _handle_update(self, update: dict) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return

        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        chat_type = str(chat.get("type") or "")
        if chat_type != "private":
            return

        chat_id = chat.get("id")
        if chat_id is None:
            return
        chat_id_text = str(chat_id)

        text = message.get("text")
        if not isinstance(text, str):
            return

        parts = text.strip().split()
        if not parts:
            return
        command = parts[0].split("@", 1)[0].lower()
        argument = parts[1] if len(parts) > 1 else ""

        if command == "/start":
            if not argument:
                async with self.session_factory() as session:
                    service = TelegramLinkService(session, provider=self.provider)
                    user = await service.enable_for_chat(chat_id_text)
                message_text = (
                    "Alerts are on."
                    if user is not None
                    else (
                        "Your Telegram chat id is "
                        f"{chat_id_text}. To link this chat, open "
                        "Settings → Telegram and click Connect Telegram."
                    )
                )
                await self._send(message_text, chat_id_text)
                return
            async with self.session_factory() as session:
                service = TelegramLinkService(session, provider=self.provider)
                result = await service.link_chat(argument, chat_id_text, chat_type)
            await self._send(result.message, chat_id_text)
            return

        if command == "/stop":
            async with self.session_factory() as session:
                service = TelegramLinkService(session, provider=self.provider)
                user = await service.disable_for_chat(chat_id_text)
            message_text = (
                "Alerts are off. Send /start to the bot to turn them back on, "
                "or manage alerts in Settings → Telegram."
                if user is not None
                else "This chat is not linked to Twitch Drops Manager."
            )
            await self._send(message_text, chat_id_text)
            return

        if command == "/unlink":
            async with self.session_factory() as session:
                service = TelegramLinkService(session, provider=self.provider)
                user = await service.unlink_chat(chat_id_text)
            message_text = (
                "This chat is no longer linked. Open Settings → Telegram and "
                "click Connect Telegram for a new link."
                if user is not None
                else "This chat is not linked to Twitch Drops Manager."
            )
            await self._send(message_text, chat_id_text)
            return

    async def _send(self, message: str, chat_id: str) -> None:
        try:
            await self.provider.send(message, chat_id)
        except ProviderError as exc:
            logger.warning("Telegram reply failed: %s", exc)

    async def _load_offset(self) -> int | None:
        async with self.session_factory() as session:
            row = await session.get(AppMeta, OFFSET_KEY)
        if row is None:
            return None
        try:
            return int(row.value)
        except (TypeError, ValueError):
            return None

    async def _save_offset(self, offset: int | None) -> None:
        if offset is None:
            return
        async with self.session_factory() as session:
            row = await session.get(AppMeta, OFFSET_KEY)
            if row is None:
                session.add(AppMeta(key=OFFSET_KEY, value=str(offset)))
            else:
                row.value = str(offset)
            await session.commit()

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stopped.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
