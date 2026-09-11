"""Watch scheduler — standalone process that ticks due watches every 10 minutes.

Runs alongside the FastAPI worker.  Started by start_env.bat in a
separate window so the logs are visible and it can be stopped
independently.

    python watch_scheduler.py

No external dependencies beyond what app1 already requires (supabase,
python-dotenv).  Loads .env, calls tick_due_watches() on an interval,
and sleeps between ticks.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watch-scheduler] %(levelname)s %(message)s",
)
logger = logging.getLogger("watch-scheduler")

TICK_INTERVAL_SECONDS = int(os.environ.get("WATCH_TICK_INTERVAL", "600"))  # 10 min
SHUTDOWN = False


def _handle_signal(signum, _frame):
    global SHUTDOWN
    logger.info("Signal %s received — shutting down after current tick.", signum)
    SHUTDOWN = True


def main() -> None:
    load_dotenv()

    # Import after env is loaded so supabase client picks up credentials.
    from app.watches import tick_due_watches

    logger.info(
        "Watch scheduler started — ticking every %ds", TICK_INTERVAL_SECONDS
    )

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not SHUTDOWN:
        try:
            result = tick_due_watches()
            if result["started"] or result["paused"] or result["errors"]:
                logger.info(
                    "Tick: started=%d paused=%d errors=%d checked=%d",
                    len(result["started"]),
                    len(result["paused"]),
                    len(result["errors"]),
                    result["checked"],
                )
            else:
                logger.debug("Tick: nothing due (checked=%d)", result["checked"])
        except Exception as exc:  # noqa: BLE001
            logger.exception("Watch tick failed: %s", exc)

        # Sleep in small increments so SIGINT/SIGTERM is responsive.
        slept = 0
        while not SHUTDOWN and slept < TICK_INTERVAL_SECONDS:
            time.sleep(1)
            slept += 1

    logger.info("Watch scheduler stopped.")


if __name__ == "__main__":
    main()
