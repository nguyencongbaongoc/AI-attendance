#!/usr/bin/env python3
"""
Test script to verify AI Worker initialization flow.
"""

import asyncio
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from pipeline_engine.core.worker import AIWorker, WorkerConfig, WorkerState
from pipeline_engine.core.engine import PipelineEngine
from pipeline_engine.config import load_pipeline_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


async def test_worker_startup():
    """Test worker startup sequence."""
    logger.info("=" * 60)
    logger.info("Testing AI Worker Startup")
    logger.info("=" * 60)
    
    config = WorkerConfig()
    config.pipeline_config_path = project_root / "pipeline_engine" / "config" / "pipeline.yaml"
    config.backend_base_url = "http://localhost:19146"
    config.health_report_interval = 1.0
    config.control_poll_interval = 1.0
    config.event_delivery_interval = 1.0
    
    worker = AIWorker(config)
    
    # Track state changes
    states = []
    def state_callback(old, new):
        states.append((old, new))
        logger.info(f"State transition: {old.value} -> {new.value}")
    
    worker.register_state_callback(state_callback)
    
    # Test start
    logger.info("Starting worker...")
    success = await worker.start()
    
    if success:
        logger.info("Worker started successfully!")
        logger.info(f"Final state: {worker.state.value}")
        logger.info(f"Status: {worker.get_status_summary()}")
        
        # Wait a bit for background tasks
        await asyncio.sleep(2.0)
        
        # Check engine state
        if worker.engine:
            logger.info(f"Engine state: {worker.engine.state.value}")
            logger.info(f"Engine health: {worker.engine.get_health()}")
            
        # Check integration clients
        logger.info(f"Health client: {worker.health_client is not None}")
        logger.info(f"Control server: {worker.control_server is not None}")
        logger.info(f"Event client: {worker.event_client is not None}")
        
        if worker.event_client:
            logger.info(f"Event client stats: {worker.event_client.get_stats()}")
        
        # Test stop
        logger.info("Stopping worker...")
        await worker.stop()
        logger.info(f"Final state after stop: {worker.state.value}")
        
        # Verify state transitions
        expected_states = [
            WorkerState.STARTING,
            WorkerState.INITIALIZING,
            WorkerState.RUNNING,
            WorkerState.STOPPING,
            WorkerState.STOPPED,
        ]
        
        actual_states = [s[1] for s in states]
        logger.info(f"State sequence: {[s.value for s in actual_states]}")
        
        # Check if RUNNING was reached
        if WorkerState.RUNNING in actual_states:
            logger.info("SUCCESS: Worker reached RUNNING state")
            return True
        else:
            logger.error("FAILURE: Worker never reached RUNNING state")
            return False
    else:
        logger.error("Worker start failed!")
        logger.info(f"State sequence: {[s.value for s in [s[1] for s in states]]}")
        return False


async def test_pipeline_engine_direct():
    """Test PipelineEngine directly."""
    logger.info("=" * 60)
    logger.info("Testing PipelineEngine Direct")
    logger.info("=" * 60)
    
    engine = PipelineEngine()
    
    logger.info("Loading config...")
    if not engine.load_config():
        logger.error("Config load failed")
        return False
    logger.info("Config loaded")
    
    logger.info("Initializing...")
    if not engine.initialize():
        logger.error("Initialize failed")
        return False
    logger.info("Initialized")
    
    logger.info("Starting...")
    if not engine.start():
        logger.error("Start failed")
        return False
    logger.info("Started")
    
    # Wait a bit
    await asyncio.sleep(3.0)
    
    logger.info(f"Engine status: {engine.get_status_summary()}")
    
    logger.info("Stopping...")
    engine.stop()
    logger.info("Stopped")
    
    return True


async def main():
    """Run tests."""
    # Test PipelineEngine first
    logger.info("Running PipelineEngine direct test...")
    pe_success = await test_pipeline_engine_direct()
    
    if not pe_success:
        logger.error("PipelineEngine test failed, skipping worker test")
        return 1
    
    # Test worker
    logger.info("Running AI Worker test...")
    worker_success = await test_worker_startup()
    
    return 0 if worker_success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)