"""
Phase 32 — MediaMTX Configuration.

Reproducible MediaMTX configuration for exactly CAM1 and CAM2.
Defines RTMP input, RTSP output, deterministic path names, H.264-compatible transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml


@dataclass(frozen=True)
class MediaMTXPathConfig:
    """Configuration for a single MediaMTX path (camera)."""
    name: str
    rtmp_stream_key: str
    rtsp_path: str
    source: str = "publisher"
    rtsp_transport: str = "tcp"
    codec: str = "h264"
    run_on_init: str = ""
    run_on_init_restart: bool = False
    run_on_demand: str = ""
    run_on_demand_start_timeout: str = "10s"
    run_on_demand_close_after: str = "10s"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "rtmp_stream_key": self.rtmp_stream_key,
            "rtsp_path": self.rtsp_path,
            "source": self.source,
            "rtsp_transport": self.rtsp_transport,
            "codec": self.codec,
            "run_on_init": self.run_on_init,
            "run_on_init_restart": self.run_on_init_restart,
            "run_on_demand": self.run_on_demand,
            "run_on_demand_start_timeout": self.run_on_demand_start_timeout,
            "run_on_demand_close_after": self.run_on_demand_close_after,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaMTXPathConfig":
        return cls(
            name=data["name"],
            rtmp_stream_key=data["rtmp_stream_key"],
            rtsp_path=data["rtsp_path"],
            source=data.get("source", "publisher"),
            rtsp_transport=data.get("rtsp_transport", "tcp"),
            codec=data.get("codec", "h264"),
            run_on_init=data.get("run_on_init", ""),
            run_on_init_restart=data.get("run_on_init_restart", False),
            run_on_demand=data.get("run_on_demand", ""),
            run_on_demand_start_timeout=data.get("run_on_demand_start_timeout", "10s"),
            run_on_demand_close_after=data.get("run_on_demand_close_after", "10s"),
        )
@dataclass
class MediaMTXConfig:
    """Complete MediaMTX configuration."""
    rtmp_address: str = ":1935"
    rtsp_address: str = ":8554"
    rtmp_encryption: str = "no"
    rtsp_encryption: str = "no"
    api_address: str = ":9997"
    paths: Dict[str, MediaMTXPathConfig] = field(default_factory=dict)
    log_level: str = "info"
    log_format: str = "text"
    auth_method: str = "none"
    
    def add_path(self, path_config: MediaMTXPathConfig) -> None:
        """Add a camera path."""
        self.paths[path_config.name] = path_config
    
    def get_path(self, name: str) -> Optional[MediaMTXPathConfig]:
        """Get a path by name."""
        return self.paths.get(name)
    
    def remove_path(self, name: str) -> bool:
        """Remove a path by name."""
        if name in self.paths:
            del self.paths[name]
            return True
        return False
    
    def to_yaml(self) -> str:
        """Generate MediaMTX YAML configuration."""
        config = {
            "rtmpAddress": self.rtmp_address,
            "rtspAddress": self.rtsp_address,
            "rtmpEncryption": self.rtmp_encryption,
            "rtspEncryption": self.rtsp_encryption,
            "apiAddress": self.api_address,
            "logLevel": self.log_level,
            "logFormat": self.log_format,
            "authMethod": self.auth_method,
            "paths": {},
        }
        
        for name, path in self.paths.items():
            path_dict = {
                "source": path.source,
                "rtspTransport": path.rtsp_transport,
            }
            if path.run_on_init:
                path_dict["runOnInit"] = path.run_on_init
            if path.run_on_init_restart:
                path_dict["runOnInitRestart"] = path.run_on_init_restart
            if path.run_on_demand:
                path_dict["runOnDemand"] = path.run_on_demand
                path_dict["runOnDemandStartTimeout"] = path.run_on_demand_start_timeout
                path_dict["runOnDemandCloseAfter"] = path.run_on_demand_close_after
            
            config["paths"][name] = path_dict
        
        return yaml.dump(config, default_flow_style=False, sort_keys=False)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "rtmp_address": self.rtmp_address,
            "rtsp_address": self.rtsp_address,
            "rtmp_encryption": self.rtmp_encryption,
            "rtsp_encryption": self.rtsp_encryption,
            "api_address": self.api_address,
            "log_level": self.log_level,
            "log_format": self.log_format,
            "auth_method": self.auth_method,
            "paths": {name: path.to_dict() for name, path in self.paths.items()},
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaMTXConfig":
        paths = {}
        for name, path_data in data.get("paths", {}).items():
            paths[name] = MediaMTXPathConfig.from_dict(path_data)
        
        return cls(
            rtmp_address=data.get("rtmp_address", ":1935"),
            rtsp_address=data.get("rtsp_address", ":8554"),
            rtmp_encryption=data.get("rtmp_encryption", "no"),
            rtsp_encryption=data.get("rtsp_encryption", "no"),
            api_address=data.get("api_address", ":9997"),
            log_level=data.get("log_level", "info"),
            log_format=data.get("log_format", "text"),
            auth_method=data.get("auth_method", "none"),
            paths=paths,
        )
    
    def validate(self) -> tuple[bool, List[str]]:
        """Validate the configuration."""
        errors = []
        
        expected_cameras = {"cam1", "cam2"}
        actual_cameras = set(self.paths.keys())
        
        if actual_cameras != expected_cameras:
            errors.append(f"Expected exactly cam1 and cam2, got: {sorted(actual_cameras)}")
        
        for name, path in self.paths.items():
            if not path.rtmp_stream_key:
                errors.append(f"Path {name}: rtmp_stream_key is required")
            if not path.rtsp_path:
                errors.append(f"Path {name}: rtsp_path is required")
            if path.codec != "h264":
                errors.append(f"Path {name}: Only H.264 codec is supported, got {path.codec}")
        
        stream_keys = [p.rtmp_stream_key for p in self.paths.values()]
        if len(stream_keys) != len(set(stream_keys)):
            errors.append("Duplicate RTMP stream keys found")
        
        rtsp_paths = [p.rtsp_path for p in self.paths.values()]
        if len(rtsp_paths) != len(set(rtsp_paths)):
            errors.append("Duplicate RTSP paths found")
        
        return len(errors) == 0, errors


def create_mediamtx_config(
    cam1_rtmp_key: str = "cam1",
    cam1_rtsp_path: str = "cam1",
    cam2_rtmp_key: str = "cam2",
    cam2_rtsp_path: str = "cam2",
) -> MediaMTXConfig:
    """Create a standard MediaMTX configuration for CAM1 and CAM2."""
    config = MediaMTXConfig()
    
    config.add_path(MediaMTXPathConfig(
        name="cam1",
        rtmp_stream_key=cam1_rtmp_key,
        rtsp_path=cam1_rtsp_path,
    ))
    
    config.add_path(MediaMTXPathConfig(
        name="cam2",
        rtmp_stream_key=cam2_rtmp_key,
        rtsp_path=cam2_rtsp_path,
    ))
    
    return config


def validate_mediamtx_config(config: MediaMTXConfig) -> tuple[bool, List[str]]:
    """Validate a MediaMTX configuration."""
    return config.validate()


MEDIAMTX_DEFAULT_CONFIG_YAML = """# MediaMTX Configuration for Phase 32 - CAM1 + CAM2
# RTMP input on :1935, RTSP output on :8554

rtmpAddress: ":1935"
rtspAddress: ":8554"
rtmpEncryption: "no"
rtspEncryption: "no"
apiAddress: ":9997"
logLevel: "info"
logFormat: "text"
authMethod: "none"

paths:
  cam1:
    source: "publisher"
    rtspTransport: "tcp"

  cam2:
    source: "publisher"
    rtspTransport: "tcp"
"""