#!/usr/bin/env python3
"""
AI Worker Entry Point

Standalone script to run the AI Worker with PipelineEngine and Legacy Backend integration.

Usage:
    python scripts/run_worker.py [--config CONFIG_PATH] [--worker-id WORKER_ID] [--backend-url URL]

Environment Variables:
    WORKER_ID              Worker identifier (default: pipeline_engine_1)
    WORKER_VERSION         Worker version (default: 1.0.0)
    BACKEND_BASE_URL       Legacy Backend base URL (default: http://localhost:19146)
    AI_WORKER_API_KEY      API key for health/event endpoints
    AI_CONTROL_API_KEY     API key for control endpoints
    PIPELINE_CONFIG_PATH   Path to pipeline.yaml config
    HEALTH_REPORT_INTERVAL Health report interval seconds (default: 5.0)
    CONTROL_POLL_INTERVAL  Control poll interval seconds (default: 2.0)
    EVENT_DELIVERY_INTERVAL Event delivery interval seconds (default: 1.0)
    SHUTDOWN_TIMEOUT       Graceful shutdown timeout seconds (default: 30.0)
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pipeline_engine.core.worker import AIWorker, WorkerConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Worker for PipelineEngine")
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to pipeline.yaml configuration file"
    )
    parser.add_argument(
        "--worker-id",
        type=str,
        help="Worker identifier"
    )
    parser.add_argument(
        "--backend-url",
        type=str,
        help="Legacy Backend base URL"
    )
    parser.add_argument(
        "--health-interval",
        type=float,
        help="Health report interval (seconds)"
    )
    parser.add_argument(
        "--control-interval",
        type=float,
        help="Control poll interval (seconds)"
    )
    parser.add_argument(
        "--event-interval",
        type=float,
        help="Event delivery interval (seconds)"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )
    return parser.parse_args()


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )
    
    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("onnxruntime").setLevel(logging.WARNING)
    logging.getLogger("torch").setLevel(logging.WARNING)


async def main() -> int:
    args = parse_args()
    setup_logging(args.log_level)
    
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("AI Worker Starting")
    logger.info("=" * 60)
    
    # Build config
    config = WorkerConfig()
    
    # Apply CLI args (override env)
    if args.config:
        config.pipeline_config_path = args.config
    if args.worker_id:
        config.worker_id = args.worker_id
    if args.backend_url:
        config.backend_base_url = args.backend_url
    if args.health_interval:
        config.health_report_interval = args.health_interval
    if args.control_interval:
        config.control_poll_interval = args.control_interval
    if args.event_interval:
        config.event_delivery_interval = args.event_interval
        
    # Log configuration
    logger.info(f"Worker ID: {config.worker_id}")
    logger.info(f"Worker Version: {config.worker_version}")
    logger.info(f"Backend URL: {config.backend_base_url}")
    logger.info(f"Pipeline Config: {config.pipeline_config_path or 'default'}")
    logger.info(f"Health Interval: {config.health_report_interval}s")
    logger.info(f"Control Interval: {config.control_poll_interval}s")
    logger.info(f"Event Interval: {config.event_delivery_interval}s")
    logger.info(f"Shutdown Timeout: {config.shutdown_timeout}s")
    
    # Check API keys
    if not config.ai_worker_api_key:
        logger.warning("AI_WORKER_API_KEY not set - health/event delivery will fail")
    if not config.ai_control_api_key:
        logger.warning("AI_CONTROL_API_KEY not set - control commands will fail")
        
    # Create and run worker
    worker = AIWorker(config)
    
    try:
        await worker.run_forever()
        return 0
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        return 0
    except Exception as e:
        logger.exception(f"Worker failed: {e}")
        return 1
    finally:
        await worker.stop()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)