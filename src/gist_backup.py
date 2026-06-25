from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def restore_from_gist() -> dict:
    logger.info("gist restore skipped (not implemented)")
    return {"restored": False}


def push_now() -> dict:
    logger.info("gist push skipped (not implemented)")
    return {"pushed": False}
