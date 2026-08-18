"""Webhook delivery worker.

Run as its own process alongside the API:

    python -m app.worker

The API only ever writes delivery rows; this loop is what actually posts them.
Running it separately means a slow or unreachable subscriber can never add
latency to an API request, and the worker can be scaled or restarted on its
own.
"""

import logging
import signal
import time
from types import FrameType
from typing import Optional

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.webhook_transport import HttpxTransport, WebhookTransport
from app.db.session import SessionLocal
from app.services.webhook_delivery_service import DispatchSummary, dispatch_pending

logger = logging.getLogger("app.worker")

# How long to sleep when a pass found nothing. Short enough that a fresh event
# goes out promptly, long enough that an idle worker isn't hammering the table.
IDLE_SLEEP_SECONDS = 5.0


class _ShutdownFlag:
    """Turns SIGTERM/SIGINT into a clean stop after the current pass.

    Killing the process mid-attempt would leave a delivery row claiming an
    attempt that may or may not have been made; finishing the pass first keeps
    the row honest.
    """

    def __init__(self) -> None:
        self.stopping = False

    def request_stop(self, signum: int, _frame: Optional[FrameType]) -> None:
        logger.info("worker shutdown requested", extra={"signal": signum})
        self.stopping = True


def run_once(transport: Optional[WebhookTransport] = None) -> DispatchSummary:
    """One dispatch pass. Exposed separately so cron-style runs are possible."""
    settings = get_settings()
    session = SessionLocal()
    try:
        return dispatch_pending(
            session,
            transport or HttpxTransport(),
            limit=settings.webhook_batch_size,
            max_attempts=settings.webhook_max_attempts,
            timeout_seconds=settings.webhook_timeout_seconds,
            backoff_base_seconds=settings.webhook_backoff_base_seconds,
            lease_seconds=settings.webhook_lease_seconds,
            verify_target=settings.webhook_validate_dns,
        )
    finally:
        session.close()


def run_forever(
    transport: Optional[WebhookTransport] = None,
    *,
    idle_sleep_seconds: float = IDLE_SLEEP_SECONDS,
    flag: Optional[_ShutdownFlag] = None,
) -> None:
    shutdown = flag or _ShutdownFlag()
    active_transport = transport or HttpxTransport()

    while not shutdown.stopping:
        try:
            summary = run_once(active_transport)
        except Exception:
            # One bad pass — a dropped connection to the database, say — must
            # not take the worker down; the next pass picks the rows back up.
            logger.exception("webhook dispatch pass failed")
            time.sleep(idle_sleep_seconds)
            continue

        if summary.attempted:
            logger.info(
                "webhook dispatch pass complete",
                extra={
                    "attempted": summary.attempted,
                    "succeeded": summary.succeeded,
                    "failed": summary.failed,
                    "retrying": summary.retrying,
                },
            )
        else:
            time.sleep(idle_sleep_seconds)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    shutdown = _ShutdownFlag()
    signal.signal(signal.SIGTERM, shutdown.request_stop)
    signal.signal(signal.SIGINT, shutdown.request_stop)

    logger.info("webhook worker started")
    run_forever(flag=shutdown)
    logger.info("webhook worker stopped")


if __name__ == "__main__":
    main()
