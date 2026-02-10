"""
Custom Logging Library
A simple wrapper for color-coded console output and clean file logging.
"""

from .logger import setup_logger

# This defines what is available when someone imports * from your package
__all__ = ["setup_logger"]

__version__ = "1.0.0"
__author__ = "Your Name"