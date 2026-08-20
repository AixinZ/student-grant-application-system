"""Record useful exception context without logging application data or error values."""

import traceback
from pathlib import Path


def log_exception_context(logger, event: str, error: BaseException) -> None:
    """Log actionable exception metadata without messages, values, or locals.

    Args:
        logger: The configured application logger that receives the event.
        event: A stable event name identifying the failed operation.
        error: The exception whose type, cause type, and final traceback
            location are safe to record.

    Notes:
        This function intentionally omits exception messages, SQL parameters,
        local variables, and submitted application data from the log entry.
    """
    frames = traceback.extract_tb(error.__traceback__)
    if frames:
        frame = frames[-1]
        location = f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
    else:
        location = "unavailable"

    cause = error.__cause__ or error.__context__
    cause_type = type(cause).__name__ if cause is not None else "none"
    logger.error(
        "%s exception_type=%s cause_type=%s traceback=%s",
        event,
        type(error).__name__,
        cause_type,
        location,
    )
