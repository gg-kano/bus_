"""
Background Scheduler for Payment Deadline Enforcement

This module runs a background task that periodically checks for
bookings that have exceeded their payment deadline and cancels them.
"""

import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Check interval in seconds (check every 30 seconds)
CHECK_INTERVAL_SECONDS = 30


class PaymentDeadlineScheduler:
    """Background scheduler to cancel expired bookings."""

    def __init__(self):
        self._task: asyncio.Task = None
        self._running = False

    async def start(self, db_session_factory):
        """Start the background scheduler."""
        if self._running:
            return

        self._running = True
        self._db_session_factory = db_session_factory
        self._task = asyncio.create_task(self._run_loop())
        logger.info("[Scheduler] Payment deadline checker started.")

    async def stop(self):
        """Stop the background scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Scheduler] Payment deadline checker stopped.")

    async def _run_loop(self):
        """Main scheduler loop."""
        # Import here to avoid circular imports
        import crud

        while self._running:
            try:
                # Get a new DB session
                db = self._db_session_factory()
                try:
                    cancelled_ids = crud.cancel_expired_bookings(db)
                    if cancelled_ids:
                        logger.info(f"[Scheduler] {datetime.now().strftime('%H:%M:%S')} - "
                                    f"Cancelled {len(cancelled_ids)} expired bookings")
                finally:
                    db.close()

            except Exception as e:
                logger.error(f"[Scheduler] Error in deadline check: {e}")

            # Wait before next check
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# Global scheduler instance
payment_scheduler = PaymentDeadlineScheduler()


@asynccontextmanager
async def lifespan_scheduler(app, db_session_factory):
    """
    Async context manager for FastAPI lifespan.

    Usage in main.py:
        from scheduler import lifespan_scheduler, payment_scheduler

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            async with lifespan_scheduler(app, SessionLocal):
                yield

        app = FastAPI(lifespan=lifespan)
    """
    await payment_scheduler.start(db_session_factory)
    yield
    await payment_scheduler.stop()
