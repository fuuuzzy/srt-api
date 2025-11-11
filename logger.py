"""日志管理模块"""
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# 标记是否已初始化
_initialized = False

# 日志格式
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# 颜色代码（用于控制台输出）
COLORS = {
    'DEBUG': '\033[36m',  # 青色
    'INFO': '\033[32m',  # 绿色
    'WARNING': '\033[33m',  # 黄色
    'ERROR': '\033[31m',  # 红色
    'CRITICAL': '\033[35m',  # 紫色
    'RESET': '\033[0m'  # 重置
}


class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器（用于控制台）"""

    def format(self, record):
        # 添加颜色
        levelname = record.levelname
        if levelname in COLORS:
            record.levelname = f"{COLORS[levelname]}{levelname}{COLORS['RESET']}"

        return super().format(record)


def setup_logging(
        log_level: str = 'INFO',
        log_file: Optional[str] = None,
        log_dir: Optional[str] = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        enable_console: bool = True,
        enable_file: bool = True,
        force_reinit: bool = False
):
    """
    配置全局日志
    
    Args:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件名，默认为 app_YYYYMMDD.log
        log_dir: 日志目录，默认为基于模块所在目录的 logs/，如果为 None 则自动计算
        max_bytes: 单个日志文件最大字节数，默认10MB
        backup_count: 保留的日志文件数量，默认5个
        enable_console: 是否输出到控制台
        enable_file: 是否输出到文件
        force_reinit: 是否强制重新初始化（即使已经初始化过）
    """
    global _initialized
    
    # 如果已经初始化且不强制重新初始化，则跳过
    if _initialized and not force_reinit:
        return
    
    # 获取根logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # 清除现有的handlers
    root_logger.handlers.clear()

    # 控制台处理器
    # Python 3 默认使用 UTF-8，直接使用 sys.stdout 即可
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_formatter = ColoredFormatter(LOG_FORMAT, DATE_FORMAT)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

    # 文件处理器
    if enable_file:
        # 如果未指定日志目录，使用模块所在目录下的 logs 目录
        if log_dir is None:
            # 获取 logger.py 所在目录
            module_dir = Path(__file__).parent
            log_path = module_dir / 'logs'
        else:
            # 如果是相对路径，基于模块所在目录
            log_dir_path = Path(log_dir)
            if not log_dir_path.is_absolute():
                module_dir = Path(__file__).parent
                log_path = module_dir / log_dir
            else:
                log_path = log_dir_path
        
        # 创建日志目录
        log_path.mkdir(parents=True, exist_ok=True)

        # 默认日志文件名
        if log_file is None:
            log_file = f"app_{datetime.now().strftime('%Y%m%d')}.log"

        log_file_path = log_path / log_file

        # 使用RotatingFileHandler（按大小轮转）
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # 标记为已初始化
    _initialized = True

    # 记录初始化信息
    root_logger.info("=" * 60)
    root_logger.info("日志系统初始化完成")
    root_logger.info(f"日志级别: {log_level.upper()}")
    if enable_console:
        root_logger.info("控制台输出: 已启用")
    if enable_file:
        root_logger.info(f"文件输出: {log_file_path}")
    root_logger.info("=" * 60)


def get_logger(name: str = None) -> logging.Logger:
    """
    获取logger实例
    
    如果日志系统尚未初始化，会自动使用默认配置进行初始化。
    如果需要自定义配置，可以在调用 get_logger() 之前先调用 setup_logging()。
    
    Args:
        name: logger名称，通常使用 __name__
        
    Returns:
        Logger实例
    """
    global _initialized
    
    # 如果尚未初始化，自动使用默认配置初始化
    if not _initialized:
        setup_logging()
    
    if name is None:
        name = __name__

    return logging.getLogger(name)
