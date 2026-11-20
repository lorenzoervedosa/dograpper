"""Logger setup."""

import logging
import sys

def setup_logger(verbose: bool = False, quiet: bool = False) -> logging.Logger:
    """Configures the root logger based on verbosity flags."""
    logger = logging.getLogger("dograpper")
    
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
        
    logger.setLevel(level)
    
    # Remove existing handlers if setup_logger is called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()
        
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    formatter = logging.Formatter('%(levelname)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger
