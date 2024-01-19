from autonomous.logger import Logger
from autonomous import log


class TestLogger:
    """
    Set the log level to by setting the LOG_LEVEL environment variable to:
    "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"

    Default: WARNING
    """

    def test_create_logger(self):
        logger = Logger()
        logger.set_level("DEBUG")
        logger.enable(True)
        logger("test", "test", "test")
        logger({"test": 3}, [1, 2, 3], 3, "test")

    def test_use_logger(self):
        log.set_level("DEBUG")
        log.enable(True)
        log("test", "test", "test")
        log.enable(False)
        log({"test": 3}, [1, 2, 3], 3, "test")
