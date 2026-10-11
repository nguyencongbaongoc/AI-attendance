"""
Pipeline Engine Configuration Loader
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineConfig(BaseModel):
    """Root configuration model."""
    
    runtime: Dict[str, Any] = Field(default_factory=dict)
    gpu: Dict[str, Any] = Field(default_factory=dict)
    paths: Dict[str, Any] = Field(default_factory=dict)
    cameras: Dict[str, Any] = Field(default_factory=dict)
    decode: Dict[str, Any] = Field(default_factory=dict)
    inference: Dict[str, Any] = Field(default_factory=dict)
    models: Dict[str, Any] = Field(default_factory=dict)
    tracking: Dict[str, Any] = Field(default_factory=dict)
    attendance: Dict[str, Any] = Field(default_factory=dict)
    annotation: Dict[str, Any] = Field(default_factory=dict)
    encode: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    backend: Dict[str, Any] = Field(default_factory=dict)
    frontend: Dict[str, Any] = Field(default_factory=dict)
    monitoring: Dict[str, Any] = Field(default_factory=dict)
    integration: Dict[str, Any] = Field(default_factory=dict)


class Settings(BaseSettings):
    """Settings with environment variable support."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )
    
    config_file: Optional[str] = None
    project_root: Path = Field(default_factory=Path.cwd)


def load_pipeline_config(config_path: Optional[Path] = None) -> PipelineConfig:
    """
    Load pipeline configuration from YAML file.
    
    Args:
        config_path: Path to pipeline.yaml. If None, searches standard locations.
        
    Returns:
        PipelineConfig with all settings loaded.
    """
    settings = Settings()
    
    if config_path is None:
        # Search standard locations
        search_paths = [
            settings.project_root / "pipeline_engine" / "config" / "pipeline.yaml",
            settings.project_root / "config" / "pipeline.yaml",
            Path.cwd() / "pipeline_engine" / "config" / "pipeline.yaml",
        ]
        
        for path in search_paths:
            if path.exists():
                config_path = path
                break
    
    if config_path is None or not config_path.exists():
        raise FileNotFoundError(
            f"Pipeline configuration not found. Searched: {[str(p) for p in search_paths]}"
        )
    
    with open(config_path, "r", encoding="utf-8") as f:
        raw_config = yaml.safe_load(f) or {}
    
    return PipelineConfig(**raw_config)


def get_camera_config(config: PipelineConfig, camera_id: str) -> Dict[str, Any]:
    """Get configuration for a specific camera."""
    cameras = config.cameras or {}
    if camera_id not in cameras:
        raise ValueError(f"Camera '{camera_id}' not configured. Available: {list(cameras.keys())}")
    return cameras[camera_id]


def get_model_config(config: PipelineConfig, model_name: str) -> Dict[str, Any]:
    """Get configuration for a specific model."""
    models = config.models or {}
    if model_name not in models:
        raise ValueError(f"Model '{model_name}' not configured. Available: {list(models.keys())}")
    return models[model_name]


# Global config instance (loaded once)
_config: Optional[PipelineConfig] = None


def get_config() -> PipelineConfig:
    """Get the global pipeline configuration (loads on first call)."""
    global _config
    if _config is None:
        _config = load_pipeline_config()
    return _config


def reload_config(config_path: Optional[Path] = None) -> PipelineConfig:
    """Reload configuration from file."""
    global _config
    _config = load_pipeline_config(config_path)
    return _config