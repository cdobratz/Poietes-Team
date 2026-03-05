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
      /projects — list projects
      /run <task> — trigger a new run (calls on_command callback)
    """

    def __init__(self, token: str, chat_id: str, on_command: Callable[[str], None] | None = None):
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot is not installed")
        self.token = token
        self.chat_id = chat_id
        self.on_command = on_command
        self._bot = Bot(token=token)
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── Sending ───────────────────────────────────────────────────────────

    def send(self, message: str) -> None:
        """Thread-safe send (creates event loop if needed)."""
        try:
            asyncio.run(self._async_send(message))
        except RuntimeError:
            # Already in an event loop
            threading.Thread(
                target=lambda: asyncio.run(self._async_send(message)),
                daemon=True,
            ).start()

    async def _async_send(self, message: str) -> None:
        # Telegram max message length is 4096 chars
        chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
        for chunk in chunks:
            await self._bot.send_message(chat_id=self.chat_id, text=chunk)

    # ── Receiving (command polling) ───────────────────────────────────────

    def start_polling(self) -> None:
        """Start Telegram command listener in a background thread."""
        if not self.on_command:
            return
        thread = threading.Thread(target=self._poll_loop, daemon=True)
        thread.start()
        logger.info("Telegram polling started")

    def _poll_loop(self) -> None:
        asyncio.run(self._run_bot())

    async def _run_bot(self) -> None:
        app = Application.builder().token(self.token).build()

        async def handle_run(update: Update, context):
            task = " ".join(context.args) if context.args else "scan all projects"
            if self.on_command:
                threading.Thread(target=self.on_command, args=(task,), daemon=True).start()
            await update.message.reply_text(f"▶️ Starting: {task}")

        async def handle_status(update: Update, context):
            await update.message.reply_text("ℹ️ Agent team is running.")

        app.add_handler(CommandHandler("run", handle_run))
        app.add_handler(CommandHandler("status", handle_status))
        await app.run_polling()


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
            )
            messengers.append(tg)
            logger.info("Telegram messenger configured")
        except Exception as e:
            logger.warning(f"Telegram setup failed: {e}")

    return CompositeMessenger(messengers)
