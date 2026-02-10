import logging
import os
import sys
from datetime import datetime


class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors based on log level."""

    # ANSI Color Codes
    GREY = "\033[38;20m"
    BLUE = "\033[34m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD_RED = "\033[31;1m"
    RESET = "\033[0m"

    # Mapping levels to colors
    FORMATS = {
        logging.DEBUG: GREY + "%(asctime)s - %(name)s - %(levelname)s - %(message)s" + RESET,
        logging.INFO: BLUE + "%(asctime)s - %(levelname)s - %(message)s" + RESET,
        logging.WARNING: YELLOW + "%(asctime)s - %(levelname)s - %(message)s" + RESET,
        logging.ERROR: RED + "%(asctime)s - %(levelname)s - %(message)s" + RESET,
        logging.CRITICAL: BOLD_RED + "%(asctime)s - %(levelname)s - %(message)s" + RESET
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        return formatter.format(record)


def setup_logger(name="project_logger", log_to_file=True, level=logging.INFO):
    """Sets up a logger that can be used globally."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent duplicate handlers if setup_logger is called multiple times
    if logger.hasHandlers():
        return logger

    # 1. Console Handler (with Colors)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)

    # 2. File Handler (Clean text, no ANSI codes)
    if log_to_file:
        os.makedirs('logs', exist_ok=True)
        log_filename = f"logs/log_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_filename)

        # Simple format for file logging (standard text is better for grepping files)
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger