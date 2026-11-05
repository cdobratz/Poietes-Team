"""
messaging/messenger.py — Unified messaging interface.
Supports Telegram (async bot) and rich CLI output.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from config.loader import MessagingConfig

logger = logging.getLogger(__name__)

# httpx logs full request URLs at INFO, and Telegram's URL contains the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
_console = Console()

# ─── Try Telegram ─────────────────────────────────────────────────────────────
try:
    from telegram import Bot, Update                        # type: ignore
    from telegram.ext import Application, CommandHandler, MessageHandler, filters  # type: ignore
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


class TelegramMessenger:
    """
    Sends messages to a configured Telegram chat.
    Also starts a polling loop so users can send commands back:
      /status — current run status
      /run <task> — trigger a new run (calls on_command callback)

    Only chats in the allowlist (chat_id plus allowed_chat_ids) may send commands;
    everyone else is ignored. At most ``max_concurrent_runs`` tasks run at once.
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        on_command: Callable[[str], None] | None = None,
        allowed_chat_ids: list[str] | None = None,
        max_concurrent_runs: int = 1,
    ):
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot is not installed")
        self.token = token
        self.chat_id = chat_id
        self.on_command = on_command
        self.allowed_chat_ids = {str(c) for c in [chat_id, *(allowed_chat_ids or [])] if str(c).strip()}
        self._run_slots = threading.BoundedSemaphore(max(1, max_concurrent_runs))
        self._stop = threading.Event()

    # ── Authorization & concurrency ───────────────────────────────────────

    def is_authorized(self, chat_id: object) -> bool:
        """True only if the sender's chat is in the allowlist."""
        return str(chat_id) in self.allowed_chat_ids

    def try_start_run(self, task: str) -> bool:
        """Start ``on_command(task)`` in a thread unless the concurrency cap is hit."""
        if not self.on_command:
            return False
        if not self._run_slots.acquire(blocking=False):
            return False

        def _worker() -> None:
            try:
                self.on_command(task)  # type: ignore[misc]
            except Exception:
                logger.exception("Telegram-triggered run failed")
            finally:
                self._run_slots.release()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    # ── Sending ───────────────────────────────────────────────────────────

    def send(self, message: str) -> None:
        """Thread-safe send. Runs in its own short-lived event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._async_send(message))
            return
        # Called from inside a running loop: hand off to a thread.
        threading.Thread(
            target=lambda: asyncio.run(self._async_send(message)),
            daemon=True,
        ).start()

    async def _async_send(self, message: str) -> None:
        # Telegram max message length is 4096 chars
        chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
        # A fresh Bot per call: its HTTP client is bound to this call's event loop.
        async with Bot(token=self.token) as bot:
            for chunk in chunks:
                await bot.send_message(chat_id=self.chat_id, text=chunk)

    # ── Receiving (command polling) ───────────────────────────────────────

    def start_polling(self) -> None:
        """Start Telegram command listener in a background thread."""
        if not self.on_command:
            return
        if not self.allowed_chat_ids:
            logger.warning("Telegram polling NOT started: no chat_id configured for the allowlist")
            return
        thread = threading.Thread(target=self._poll_loop, daemon=True)
        thread.start()
        logger.info("Telegram polling started")

    def stop_polling(self) -> None:
        self._stop.set()

    def _poll_loop(self) -> None:
        try:
            asyncio.run(self._run_bot())
        except Exception as e:
            # No traceback/str(e) verbatim: Telegram errors can echo the bot token.
            msg = str(e).replace(self.token, "***")
            logger.error(f"Telegram polling stopped unexpectedly: {type(e).__name__}: {msg}")

    async def _run_bot(self) -> None:
        # run_polling() installs signal handlers, which only works in the main
        # thread. Drive the Application lifecycle manually instead.
        app = Application.builder().token(self.token).build()

        async def handle_run(update: Update, context):
            chat = update.effective_chat
            if chat is None or not self.is_authorized(chat.id):
                logger.warning(f"Ignored /run from unauthorized chat {getattr(chat, 'id', None)}")
                return
            task = " ".join(context.args) if context.args else "scan all projects"
            if self.try_start_run(task):
                await update.message.reply_text(f"▶️ Starting: {task}")
            else:
                await update.message.reply_text("⏳ Busy: too many runs in progress. Try again later.")

        async def handle_status(update: Update, context):
            chat = update.effective_chat
            if chat is None or not self.is_authorized(chat.id):
                return
            await update.message.reply_text("ℹ️ Bot is up.")

        app.add_handler(CommandHandler("run", handle_run))
        app.add_handler(CommandHandler("status", handle_status))

        async with app:
            await app.start()
            await app.updater.start_polling()
            while not self._stop.is_set():
                await asyncio.sleep(0.5)
            await app.updater.stop()
            await app.stop()


class CLIMessenger:
    """Pretty console output using Rich."""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def send(self, message: str) -> None:
        if not self.verbose:
            return
        # Style based on content
        if "🚨" in message or "❌" in message or "ERROR" in message.upper():
            style = "bold red"
        elif "✅" in message or "complete" in message.lower():
            style = "bold green"
        elif "⚠️" in message or "WARNING" in message.upper():
            style = "bold yellow"
        elif "🔍" in message or "📝" in message or "🔒" in message:
            style = "bold cyan"
        else:
            style = "white"

        _console.print(Text(message, style=style))


class CompositeMessenger:
    """Sends to all enabled messengers."""

    def __init__(self, messengers: list):
        self._messengers = messengers

    def send(self, message: str) -> None:
        for m in self._messengers:
            try:
                m.send(message)
            except Exception as e:
                logger.warning(f"Messenger failed: {e}")

    def start_polling(self) -> None:
        for m in self._messengers:
            if hasattr(m, "start_polling"):
                m.start_polling()


def build_messenger(
    cfg: MessagingConfig,
    on_command: Callable[[str], None] | None = None,
) -> CompositeMessenger:
    """Factory: build messenger from config."""
    messengers = []

    if cfg.cli.get("enabled", True):
        messengers.append(CLIMessenger(verbose=cfg.cli.get("verbose", True)))

    if cfg.telegram.enabled and cfg.telegram.bot_token and TELEGRAM_AVAILABLE:
        try:
            tg = TelegramMessenger(
                token=cfg.telegram.bot_token,
                chat_id=cfg.telegram.chat_id,
                on_command=on_command,
                allowed_chat_ids=cfg.telegram.allowed_chat_ids,
                max_concurrent_runs=cfg.telegram.max_concurrent_runs,
            )
            messengers.append(tg)
            logger.info("Telegram messenger configured")
        except Exception as e:
            logger.warning(f"Telegram setup failed: {e}")

    return CompositeMessenger(messengers)
