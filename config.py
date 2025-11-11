"""配置管理模块"""
from pathlib import Path
from typing import Dict, Any

import yaml


class Config:
    """配置管理类"""

    def __init__(self, config_path: str = None):
        """
        初始化配置
        
        Args:
            config_path: 配置文件路径，默认为项目根目录下的config.yaml
        """
        if config_path is None:
            # 获取项目根目录
            root_dir = Path(__file__).parent
            config_path = root_dir / "config.yaml"

        self.config_path = config_path
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    @property
    def models(self) -> Dict[str, Any]:
        """获取配置"""
        return self._config.get('models', {})

    def get(self, key: str, default=None):
        """获取配置项"""
        return self._config.get(key, default)


# 全局配置实例
config = Config()
