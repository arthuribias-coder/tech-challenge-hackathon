"""
Buffer em memória para logs da aplicação.

Captura todas as entradas de log via um handler Python padrão e as mantém em
um deque circular. SSE subscribers recebem novos entries em tempo real via
asyncio.Queue.
"""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator

_MAX_ENTRIES = 500  # máximo de entradas mantidas em memória

LEVEL_COLORS = {
    "DEBUG": "log-debug",
    "INFO": "log-info",
    "WARNING": "log-warning",
    "ERROR": "log-error",
    "CRITICAL": "log-critical",
}


@dataclass
class LogEntry:
    timestamp: str
    level: str
    logger: str
    message: str
    level_class: str = field(init=False)

    def __post_init__(self) -> None:
        self.level_class = LEVEL_COLORS.get(self.level, "log-info")

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
            "level_class": self.level_class,
        }


class _LogBuffer(logging.Handler):
    """Handler que armazena LogEntry em deque e distribui para subscribers SSE."""

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        super().__init__()
        self._entries: deque[LogEntry] = deque(maxlen=max_entries)
        self._subscribers: list[asyncio.Queue] = []

    # ------------------------------------------------------------------
    # logging.Handler API
    # ------------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3],
                level=record.levelname,
                logger=record.name,
                message=self.format(record),
            )
            self._entries.append(entry)
            self._notify(entry)
        except Exception:  # noqa: BLE001
            self.handleError(record)

    # ------------------------------------------------------------------
    # Acesso ao buffer
    # ------------------------------------------------------------------

    def recent(self, n: int = _MAX_ENTRIES) -> list[LogEntry]:
        """Retorna as `n` entradas mais recentes."""
        entries = list(self._entries)
        return entries[-n:]

    # ------------------------------------------------------------------
    # SSE pub/sub
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _notify(self, entry: LogEntry) -> None:
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    async def stream(self) -> AsyncIterator[LogEntry]:
        """Gerador assíncrono: retorna entries à medida que chegam."""
        q = self.subscribe()
        try:
            while True:
                entry = await q.get()
                yield entry
        finally:
            self.unsubscribe(q)


# Instância global — instalada uma única vez em main.py
log_buffer = _LogBuffer()
log_buffer.setFormatter(logging.Formatter("%(message)s"))


def install(level: int = logging.DEBUG) -> None:
    """Registra o handler no logger raiz. Chamar uma única vez na inicialização."""
    log_buffer.setLevel(level)
    logging.getLogger().addHandler(log_buffer)
