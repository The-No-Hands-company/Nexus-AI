"""Compatibility layer for optional C++ logging hooks used by RAG modules."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class _CPPLoggerCompat:
    """Drop-in shim for modules that expect CPPLogger methods."""

    @staticmethod
    def debug(message: str, component: Optional[str] = None) -> None:
        logger.debug("[%s] %s", component or "rag", message)

    @staticmethod
    def info(message: str, component: Optional[str] = None) -> None:
        logger.info("[%s] %s", component or "rag", message)

    @staticmethod
    def warning(message: str, component: Optional[str] = None) -> None:
        logger.warning("[%s] %s", component or "rag", message)

    @staticmethod
    def error(message: str, component: Optional[str] = None) -> None:
        logger.error("[%s] %s", component or "rag", message)


HAS_CPP_LOGGER = False
CPPLogger = _CPPLoggerCompat()
