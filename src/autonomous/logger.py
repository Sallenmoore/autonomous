import datetime
import inspect
import logging
import os

log_levels = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class Logger:
    """
    Leveled logger with optional file archive.

    ``LOG_LEVEL`` (DEBUG / INFO / WARNING / ERROR / CRITICAL; default WARNING)
    controls the **threshold** — the minimum severity that gets emitted to
    stderr / handlers. It does not control the severity of any particular
    message. Bare ``log(obj)`` calls always emit at DEBUG; reserve ERROR for
    explicit ``log.error(...)`` / exception paths once those are wired up.
    File writes can be disabled by setting ``LOG_TO_FILES=0`` or by calling
    ``logger.enable_file_logging(False)``.

    ``Logger()`` itself has no side effects — the logs directory and any
    file paths are resolved on the first ``__call__``. This keeps the ORM,
    auth, and AI modules importable in processes that don't need disk logging
    (tests, docs builds, CLI scripts).
    """

    def __init__(self, name: str = "gunicorn.error"):
        self.logger = logging.getLogger(name)
        level = os.environ.get("LOG_LEVEL") or logging.getLevelName(self.logger.level)
        self.logger.setLevel(log_levels.get(level, logging.WARNING))
        self.enabled = True
        self._file_logging = os.environ.get("LOG_TO_FILES", "1") != "0"
        self._log_dir = "logs"
        self._logfile: str | None = None
        self._logarchive: str | None = None
        self._initialized_paths = False

    def _ensure_paths(self) -> None:
        """Create the log directory and resolve file paths on first call."""
        if self._initialized_paths:
            return
        if self._file_logging:
            os.makedirs(self._log_dir, exist_ok=True)
            self._logfile = f"{self._log_dir}/current_run_error_log.log"
            self._logarchive = (
                f"{self._log_dir}/"
                f"error_log-{datetime.datetime.now().strftime('%Y-%m-%d')}.log"
            )
        self._initialized_paths = True

    def set_level(self, level: str) -> None:
        self.logger.setLevel(log_levels[level])

    def enable(self, enable: bool = True) -> None:
        self.enabled = enable

    def enable_file_logging(self, enable: bool = True) -> None:
        self._file_logging = enable
        self._initialized_paths = False  # re-resolve on next call

    def _format(self, *args, **kwargs) -> str:
        caller = inspect.stack()[2]
        fn = caller.filename.split("/")[-1]
        msg = f"\n\n{'='*20}\t{fn}:{caller.function}()::{caller.lineno}\t{'='*20}\n"
        msg += f"\n{'='*20}\n"
        if args:
            msg += "\n---\n".join([f"{v}" for v in args])
        if kwargs:
            msg += "\n---\n".join([f"{k} : {v}" for k, v in kwargs.items()])
        msg += f"\n{'='*20}\n"
        return msg

    def __call__(self, *args, **kwargs) -> None:
        if not self.enabled:
            return
        is_printed = kwargs.pop("_print", False)
        msg = self._format(*args, **kwargs)
        # Bare ``log(obj)`` is a content-dump pattern (developer probe), not
        # an error. Emit at DEBUG so prod consumers running with
        # LOG_LEVEL=WARNING or higher don't see it — and so error-monitoring
        # regexes don't flag it. Earlier code emitted at ``self.logger.level``
        # (the threshold), which made bare calls inherit whatever severity
        # the threshold was set to (often ERROR in prod).
        self.logger.log(logging.DEBUG, f"{msg}\n")
        if self._file_logging:
            self._ensure_paths()
            try:
                with open(self._logfile, "w") as current:
                    current.write(f"{msg}\n")
                with open(self._logarchive, "a") as archive:
                    archive.write(f"{msg}\n")
            except OSError:
                # A failing disk must not take down the caller.
                pass
        if is_printed:
            print(msg)

    def warning(self, *args, **kwargs) -> None:
        """Emit at WARNING — for conditions an operator must actually see.

        ``__call__`` deliberately emits at DEBUG (developer content dumps),
        which means a bare ``log(...)`` is invisible under the default
        ``LOG_LEVEL=WARNING``. Degraded-but-recovered paths (e.g. a legacy
        stored value that the ORM coerced instead of raising, #225) need
        the opposite: they must surface in prod logs so the underlying
        data can be migrated, without being an error the caller handles.
        """
        if not self.enabled:
            return
        kwargs.pop("_print", False)
        self.logger.warning(f"{self._format(*args, **kwargs)}\n")


_default_logger: Logger | None = None


def get_logger(name: str = "gunicorn.error") -> Logger:
    """Return a fresh ``Logger`` instance.

    Useful for tests that need isolation from the package-wide default, or
    for subsystems that want their own handler and level without touching
    the shared one.
    """
    return Logger(name=name)


def _get_default_logger() -> Logger:
    global _default_logger
    if _default_logger is None:
        _default_logger = Logger()
    return _default_logger


class _DefaultLoggerProxy:
    """Delegates every attribute access / call to the lazily-built default.

    Keeps ``from autonomous import log`` working without constructing a
    Logger at package-import time.
    """

    def __call__(self, *args, **kwargs):
        return _get_default_logger()(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(_get_default_logger(), name)


log = _DefaultLoggerProxy()
