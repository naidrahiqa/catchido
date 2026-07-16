import sys
from pathlib import Path
from loguru import logger

def setup_logger(log_file: str, log_level: str = "INFO") -> None:
    # Remove existing handlers
    logger.remove()

    # Format for logging
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # Console Handler (Stdout)
    logger.add(
        sys.stdout,
        format=log_format,
        level=log_level,
        colorize=True,
    )

    # File Handler
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.add(
        str(log_path),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        level=log_level,
        rotation="10 MB",
        retention=5,
        compression="zip",
        encoding="utf-8"
    )

    logger.info("Logger initialized. Log level: {}, File: {}", log_level, log_path)
