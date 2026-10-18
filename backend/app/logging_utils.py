"""Logging that carries only IDs and statuses — never field values."""
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **ids) -> None:
    parts = " ".join(f"{k}={v}" for k, v in ids.items())
    logger.info("%s %s", event, parts)
