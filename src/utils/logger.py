import sys
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.logging import RichHandler
import logging


def get_logger(name: str = "code_analyzer", log_file: Optional[str] = None, level: str = "DEBUG"):
    """
    获取配置好的 logger

    Args:
        name: logger 名称
        log_file: 日志文件路径
        level: 日志级别

    Returns:
        配置好的 logger 实例
    """
    logger = logging.getLogger(name)

    # 如果已经配置过，直接返回
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper()))

    # Rich 控制台处理器
    console = Console(force_terminal=True, file=sys.stderr)
    rich_handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        show_time=True,
        show_path=False,
        enable_link_path=False
    )
    rich_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(rich_handler)

    # 文件处理器
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)

    return logger


# 默认 logger 实例
default_logger = get_logger()
