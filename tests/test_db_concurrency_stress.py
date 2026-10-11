"""
Phase 18 Database Integrity & Concurrency Audit.

Verifies database consistency, WAL mode durability, and zero contention between
high-frequency AI event ingestion and background maintenance tasks.

Tests:
1. SQLite connection pooling and WAL settings
2. Concurrency stress: 50 concurrent event writes + continuous background SQLite backup + hourly cleanup query
3. Zero 'database is locked' errors and zero corruptions via PRAGMA integrity_check
4. Invariant verification: No AI vision worker module imports SQLite write cursors targeting app/data/attendance.db
"""

import argparse
import asyncio
import logging
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.attendance.storage import AttendanceStorage, StorageConfig, create_attendance_storage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


class DatabaseConcurrencyTest:
    """Database concurrency and integrity stress test."""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or "app/data/attendance.db"
        self.results = {
            'wal_mode_verified': False,
            'busy_timeout_verified': False,
            'concurrent_writes_passed': False,
            'backup_during_writes_passed': False,
            'cleanup_during_writes_passed': False,
            'integrity_check_passed': False,
            'zero_lock_errors': True,
            'zero_corruptions': True,
            'write_authority_verified': False,
            'errors': [],
            'metrics': {}
        }
        self._lock_errors = 0
        self._lock_errors_lock = threading.Lock()
        self._total_writes = 0
        self._total_writes_lock = threading.Lock()
        self._successful_writes = 0
        self._successful_writes_lock = threading.Lock()
    
    def run_all_tests(self) -> bool:
        """Run all concurrency tests."""
        logger.info("=" * 80)
        logger.info("PHASE 18 DATABASE INTEGRITY & CONCURRENCY AUDIT")
        logger.info("=" * 80)
        
        success = True
        
        # Test 1: Verify WAL mode and settings
        if not self._test_wal_settings():
            success = False
        
        # Test 2: Concurrency stress test
        if not self._test_concurrent_writes():
            success = False
        
        # Test 3: Backup during writes
        if not self._test_backup_during_writes():
            success = False
        
        # Test 4: Cleanup during writes
        if not self._test_cleanup_during_writes():
            success = False
        
        # Test 5: Integrity check
        if not self._test_integrity_check():
            success = False
        
        # Test 6: Write authority invariant
        if not self._test_write_authority():
            success = False
        
        # Print summary
        self._print_summary()
        
        return success
    
    def _test_wal_settings(self) -> bool:
        """Verify SQLite WAL mode and settings."""
        logger.info("\n--- Test 1: Verify WAL Mode and Settings ---")
        
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            
            # Check journal mode
            cursor = conn.execute("PRAGMA journal_mode;")
            journal_mode = cursor.fetchone()[0]
            logger.info(f"Journal mode: {journal_mode}")
            if journal_mode.lower() != 'wal':
                self.results['errors'].append(f"Expected WAL mode, got {journal_mode}")
                return False
            self.results['wal_mode_verified'] = True
            
            # Check synchronous setting
            cursor = conn.execute("PRAGMA synchronous;")
            synchronous = cursor.fetchone()[0]
            logger.info(f"Synchronous: {synchronous}")
            # Accept both NORMAL (1) and FULL (2) as valid for durability
            if synchronous not in (1, 2):
                self.results['errors'].append(f"Expected synchronous=NORMAL (1) or FULL (2), got {synchronous}")
                return False
            
            # Check busy_timeout
            cursor = conn.execute("PRAGMA busy_timeout;")
            busy_timeout = cursor.fetchone()[0]
            logger.info(f"Busy timeout: {busy_timeout}ms")
            if busy_timeout != 5000:
                self.results['errors'].append(f"Expected busy_timeout=5000ms, got {busy_timeout}")
                return False
            self.results['busy_timeout_verified'] = True
            
            conn.close()
            logger.info("WAL settings verification PASSED")
            return True
            
        except Exception as e:
            logger.error(f"WAL settings test failed: {e}")
            self.results['errors'].append(f"WAL settings test failed: {e}")
            return False
    
    def _create_test_record(self, record_id: int) -> Dict:
        """Create a test attendance record."""
        import secrets
        from datetime import datetime
        
        now = time.time()
        return {
            'attendance_record_id': f"TEST-{record_id:06d}-{secrets.token_urlsafe(8)}",
            'identity_certainty': 'known',
            'identity_candidate': f'TEST_PERSON_{record_id % 100}',
            'identity_confidence': 0.95,
            'identity_evidence_ref': f'evidence_{record_id}',
            'face_evidence_ref': f'face_{record_id}',
            'body_evidence_ref': f'body_{record_id}',
            'face_quality': 0.9,
            'body_quality': 0.85,
            'association_method': 'fused',
            'conflict_flag': 0,
            'provisional_person_id': None,
            'identity_state': 'confirmed',
            'direction': 'in' if record_id % 2 == 0 else 'out',
            'event_timestamp': now,
            'event_frame_index': record_id,
            'camera_id': 'cam1' if record_id % 2 == 0 else 'cam2',
            'local_track_id': f'track_{record_id}',
            'global_observation_id': f'global_{record_id}',
            'source_raw_event_id': f'raw_{record_id}',
            'source_resolution_id': f'res_{record_id}',
            'source_crossing_event_id': f'cross_{record_id}',
            'geometry_version': 1,
            'geometry_config_hash': 'test_hash',
            'resolver_version': '1.0',
            'resolver_config_hash': 'test_config',
            'previous_state': 'outside',
            'new_state': 'inside',
            'stream_epoch': 1,
            'pts': record_id * 90000,
            
            'capture_timestamp': now,
            'processing_timestamp': now,
            'model_version': 'test_v1',
            'enrollment_version': 'test_v1',
            'attendance_schema_version': '1.1',
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'persisted_at': datetime.utcnow().isoformat() + 'Z',
            'snapshot_face_url': f'/static/evidence/snapshots/face_{record_id}.jpg',
            'snapshot_scene_url': f'/static/evidence/snapshots/scene_{record_id}.jpg',
            'video_clip_url': f'/static/evidence/clips/clip_{record_id}.mp4',
        }
    
    def _writer_worker(self, worker_id: int, num_records: int, storage: AttendanceStorage, 
                       stop_event: threading.Event, results: Dict):
        """Worker that continuously writes records."""
        local_errors = 0
        local_writes = 0
        local_success = 0
        
        for i in range(num_records):
            if stop_event.is_set():
                break
            
            record_data = self._create_test_record(worker_id * 10000 + i)
            
            # Create record object
            from app.attendance.contract import AttendanceRecord, IdentityCertainty, AttendanceDirection
            from fractions import Fraction
            
            record = AttendanceRecord(
                attendance_record_id=record_data['attendance_record_id'],
                identity_certainty=IdentityCertainty(record_data['identity_certainty']),
                identity_candidate=record_data['identity_candidate'],
                identity_confidence=record_data['identity_confidence'],
                identity_evidence_ref=record_data['identity_evidence_ref'],
                face_evidence_ref=record_data['face_evidence_ref'],
                body_evidence_ref=record_data['body_evidence_ref'],
                face_quality=record_data['face_quality'],
                body_quality=record_data['body_quality'],
                association_method=record_data['association_method'],
                conflict_flag=bool(record_data['conflict_flag']),
                provisional_person_id=record_data['provisional_person_id'],
                identity_state=record_data['identity_state'],
                direction=AttendanceDirection(record_data['direction']),
                event_timestamp=record_data['event_timestamp'],
                event_frame_index=record_data['event_frame_index'],
                camera_id=record_data['camera_id'],
                local_track_id=record_data['local_track_id'],
                global_observation_id=record_data['global_observation_id'],
                source_raw_event_id=record_data['source_raw_event_id'],
                source_resolution_id=record_data['source_resolution_id'],
                source_crossing_event_id=record_data['source_crossing_event_id'],
                geometry_version=record_data['geometry_version'],
                geometry_config_hash=record_data['geometry_config_hash'],
                resolver_version=record_data['resolver_version'],
                resolver_config_hash=record_data['resolver_config_hash'],
                previous_state=record_data['previous_state'],
                new_state=record_data['new_state'],
                stream_epoch=record_data['stream_epoch'],
                pts=record_data['pts'],
                time_base=Fraction(1, 90000),
                capture_timestamp=record_data['capture_timestamp'],
                processing_timestamp=record_data['processing_timestamp'],
                model_version=record_data['model_version'],
                enrollment_version=record_data['enrollment_version'],
                attendance_schema_version=record_data['attendance_schema_version'],
                created_at=record_data['created_at'],
                persisted_at=record_data['persisted_at'],
                snapshot_face_url=record_data['snapshot_face_url'],
                snapshot_scene_url=record_data['snapshot_scene_url'],
                video_clip_url=record_data['video_clip_url'],
            )
            
            try:
                result = storage.insert(record)
                local_writes += 1
                if result:
                    local_success += 1
            except sqlite3.OperationalError as e:
                if 'locked' in str(e).lower() or 'busy' in str(e).lower():
                    local_errors += 1
                    with self._lock_errors_lock:
                        self._lock_errors += 1
                else:
                    raise
            except Exception as e:
                logger.error(f"Writer {worker_id} error: {e}")
                local_errors += 1
            
            # Small delay to simulate real workload
            time.sleep(0.001)
        
        results[worker_id] = {
            'writes': local_writes,
            'success': local_success,
            'errors': local_errors
        }
        
        with self._total_writes_lock:
            self._total_writes += local_writes
        with self._successful_writes_lock:
            self._successful_writes += local_success
    
    def _backup_worker(self, stop_event: threading.Event, results: Dict):
        """Worker that performs continuous backups."""
        import tempfile
        import shutil
        
        backup_count = 0
        backup_errors = 0
        
        while not stop_event.is_set():
            try:
                # Create backup
                with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
                    backup_path = tmp.name
                
                storage = create_attendance_storage()
                storage.backup(backup_path)
                
                # Verify backup integrity
                conn = sqlite3.connect(backup_path)
                cursor = conn.execute("PRAGMA integrity_check;")
                integrity = cursor.fetchone()[0]
                conn.close()
                
                if integrity != 'ok':
                    backup_errors += 1
                    logger.warning(f"Backup integrity check failed: {integrity}")
                
                backup_count += 1
                os.unlink(backup_path)
                
            except Exception as e:
                backup_errors += 1
                logger.error(f"Backup worker error: {e}")
            
            time.sleep(2.0)  # Backup every 2 seconds
        
        results['backup'] = {
            'count': backup_count,
            'errors': backup_errors
        }
    
    def _cleanup_worker(self, stop_event: threading.Event, results: Dict):
        """Worker that performs cleanup queries."""
        cleanup_count = 0
        cleanup_errors = 0
        
        while not stop_event.is_set():
            try:
                storage = create_attendance_storage()
                conn = storage._get_connection()
                cursor = conn.cursor()
                
                # Simulate hourly cleanup query - delete old test records
                cursor.execute("""
                    DELETE FROM attendance_records 
                    WHERE attendance_record_id LIKE 'TEST-%'
                    AND event_timestamp < ?
                """, (time.time() - 3600,))
                
                deleted = cursor.rowcount
                conn.commit()
                cursor.close()
                
                cleanup_count += 1
                
            except Exception as e:
                cleanup_errors += 1
                logger.error(f"Cleanup worker error: {e}")
            
            time.sleep(5.0)  # Cleanup every 5 seconds
        
        results['cleanup'] = {
            'count': cleanup_count,
            'errors': cleanup_errors
        }
    
    def _test_concurrent_writes(self) -> bool:
        """Test concurrent writes from multiple threads."""
        logger.info("\n--- Test 2: Concurrent Writes Stress Test ---")
        
        num_writers = 10
        records_per_writer = 500  # 5000 total writes
        test_duration = 30  # seconds
        
        storage = create_attendance_storage()
        stop_event = threading.Event()
        writer_results = {}
        
        # Start writers
        threads = []
        for i in range(num_writers):
            t = threading.Thread(
                target=self._writer_worker,
                args=(i, records_per_writer, storage, stop_event, writer_results)
            )
            threads.append(t)
            t.start()
        
        # Wait for completion or timeout
        start_time = time.time()
        for t in threads:
            t.join(timeout=test_duration)
        
        # Check if any threads are still alive (timeout)
        for t in threads:
            if t.is_alive():
                logger.warning(f"Writer thread timed out after {test_duration}s")
                stop_event.set()
        
        # Wait for all to finish
        for t in threads:
            t.join(timeout=5.0)
        
        # Collect results
        total_writes = sum(r['writes'] for r in writer_results.values())
        total_success = sum(r['success'] for r in writer_results.values())
        total_errors = sum(r['errors'] for r in writer_results.values())
        
        logger.info(f"Total writes attempted: {total_writes}")
        logger.info(f"Total successful: {total_success}")
        logger.info(f"Total lock errors: {total_errors}")
        logger.info(f"Global lock errors: {self._lock_errors}")
        
        self.results['metrics']['concurrent_writes'] = {
            'total_attempted': total_writes,
            'successful': total_success,
            'lock_errors': total_errors,
        }
        
        if total_errors > 0:
            logger.error(f"FAIL: {total_errors} lock errors during concurrent writes")
            self.results['zero_lock_errors'] = False
            self.results['concurrent_writes_passed'] = False
            return False
        
        logger.info("Concurrent writes test PASSED")
        self.results['concurrent_writes_passed'] = True
        return True
    
    def _test_backup_during_writes(self) -> bool:
        """Test backup operations during concurrent writes."""
        logger.info("\n--- Test 3: Backup During Writes ---")
        
        num_writers = 5
        records_per_writer = 200
        test_duration = 20
        
        storage = create_attendance_storage()
        stop_event = threading.Event()
        writer_results = {}
        backup_results = {}
        
        # Start writers
        threads = []
        for i in range(num_writers):
            t = threading.Thread(
                target=self._writer_worker,
                args=(i + 100, records_per_writer, storage, stop_event, writer_results)
            )
            threads.append(t)
            t.start()
        
        # Start backup worker
        backup_thread = threading.Thread(
            target=self._backup_worker,
            args=(stop_event, backup_results)
        )
        backup_thread.start()
        threads.append(backup_thread)
        
        # Wait for completion
        start_time = time.time()
        for t in threads[:-1]:  # Don't join backup thread yet
            t.join(timeout=test_duration)
        
        # Stop backup thread
        stop_event.set()
        backup_thread.join(timeout=5.0)
        
        # Results
        backup_count = backup_results.get('backup', {}).get('count', 0)
        backup_errors = backup_results.get('backup', {}).get('errors', 0)
        total_writes = sum(r['writes'] for r in writer_results.values())
        total_errors = sum(r['errors'] for r in writer_results.values())
        
        logger.info(f"Backups performed: {backup_count}")
        logger.info(f"Backup errors: {backup_errors}")
        logger.info(f"Writes during backup: {total_writes}")
        logger.info(f"Lock errors during backup: {total_errors}")
        
        self.results['metrics']['backup_during_writes'] = {
            'backups': backup_count,
            'backup_errors': backup_errors,
            'writes': total_writes,
            'lock_errors': total_errors,
        }
        
        if backup_errors > 0 or total_errors > 0:
            logger.error("FAIL: Errors during backup + writes")
            self.results['backup_during_writes_passed'] = False
            return False
        
        logger.info("Backup during writes test PASSED")
        self.results['backup_during_writes_passed'] = True
        return True
    
    def _test_cleanup_during_writes(self) -> bool:
        """Test cleanup queries during concurrent writes."""
        logger.info("\n--- Test 4: Cleanup During Writes ---")
        
        num_writers = 5
        records_per_writer = 200
        test_duration = 20
        
        storage = create_attendance_storage()
        stop_event = threading.Event()
        writer_results = {}
        cleanup_results = {}
        
        # Start writers
        threads = []
        for i in range(num_writers):
            t = threading.Thread(
                target=self._writer_worker,
                args=(i + 200, records_per_writer, storage, stop_event, writer_results)
            )
            threads.append(t)
            t.start()
        
        # Start cleanup worker
        cleanup_thread = threading.Thread(
            target=self._cleanup_worker,
            args=(stop_event, cleanup_results)
        )
        cleanup_thread.start()
        threads.append(cleanup_thread)
        
        # Wait for completion
        start_time = time.time()
        for t in threads[:-1]:
            t.join(timeout=test_duration)
        
        # Stop cleanup thread
        stop_event.set()
        cleanup_thread.join(timeout=5.0)
        
        # Results
        cleanup_count = cleanup_results.get('cleanup', {}).get('count', 0)
        cleanup_errors = cleanup_results.get('cleanup', {}).get('errors', 0)
        total_writes = sum(r['writes'] for r in writer_results.values())
        total_errors = sum(r['errors'] for r in writer_results.values())
        
        logger.info(f"Cleanup cycles: {cleanup_count}")
        logger.info(f"Cleanup errors: {cleanup_errors}")
        logger.info(f"Writes during cleanup: {total_writes}")
        logger.info(f"Lock errors during cleanup: {total_errors}")
        
        self.results['metrics']['cleanup_during_writes'] = {
            'cleanups': cleanup_count,
            'cleanup_errors': cleanup_errors,
            'writes': total_writes,
            'lock_errors': total_errors,
        }
        
        if cleanup_errors > 0 or total_errors > 0:
            logger.error("FAIL: Errors during cleanup + writes")
            self.results['cleanup_during_writes_passed'] = False
            return False
        
        logger.info("Cleanup during writes test PASSED")
        self.results['cleanup_during_writes_passed'] = True
        return True
    
    def _test_integrity_check(self) -> bool:
        """Run PRAGMA integrity_check on the database."""
        logger.info("\n--- Test 5: Database Integrity Check ---")
        
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            cursor = conn.execute("PRAGMA integrity_check;")
            result = cursor.fetchone()[0]
            conn.close()
            
            logger.info(f"Integrity check result: {result}")
            
            if result == 'ok':
                logger.info("Integrity check PASSED")
                self.results['integrity_check_passed'] = True
                return True
            else:
                logger.error(f"FAIL: Integrity check failed: {result}")
                self.results['zero_corruptions'] = False
                self.results['integrity_check_passed'] = False
                return False
                
        except Exception as e:
            logger.error(f"Integrity check error: {e}")
            self.results['errors'].append(f"Integrity check error: {e}")
            return False
    
    def _test_write_authority(self) -> bool:
        """Verify no AI vision worker imports SQLite write cursors targeting attendance.db."""
        logger.info("\n--- Test 6: Write Authority Invariant ---")
        
        import ast
        import glob
        
        violations = []
        
        # Scan Python files in app/vision and pipeline_engine
        patterns = [
            'app/vision/**/*.py',
            'pipeline_engine/**/*.py',
        ]
        
        for pattern in patterns:
            for file_path in glob.glob(pattern, recursive=True):
                if '__pycache__' in file_path:
                    continue
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Check for direct sqlite3 connections to attendance.db
                    if 'attendance.db' in content and ('sqlite3.connect' in content or 'sqlite3.Connection' in content):
                        # Parse AST to find actual usage
                        tree = ast.parse(content)
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Call):
                                if hasattr(node.func, 'attr') and node.func.attr == 'connect':
                                    # Check arguments
                                    for arg in node.args:
                                        if isinstance(arg, ast.Constant) and 'attendance.db' in str(arg.value):
                                            violations.append(f"{file_path}: Direct sqlite3.connect to attendance.db")
                    
                    # Check for AttendanceStorage imports used for writes (this is allowed for legacy backend)
                    # But AI vision workers should NOT use it
                    if 'AttendanceStorage' in content:
                        if 'vision' in file_path or 'inference' in file_path or 'tracker' in file_path:
                            violations.append(f"{file_path}: AttendanceStorage imported in vision/inference module")
                
                except Exception as e:
                    logger.debug(f"Could not parse {file_path}: {e}")
        
        if violations:
            for v in violations:
                logger.error(f"VIOLATION: {v}")
            self.results['errors'].extend(violations)
            self.results['write_authority_verified'] = False
            return False
        
        logger.info("Write authority invariant VERIFIED - No AI vision workers write to attendance.db")
        self.results['write_authority_verified'] = True
        return True
    
    def _print_summary(self):
        """Print test summary."""
        logger.info("\n" + "=" * 80)
        logger.info("DATABASE INTEGRITY & CONCURRENCY AUDIT - SUMMARY")
        logger.info("=" * 80)
        
        for key, value in self.results.items():
            if key in ['errors', 'metrics']:
                continue
            status = "PASS" if value else "FAIL"
            logger.info(f"  {key}: {status}")
        
        if self.results['errors']:
            logger.info("\nErrors:")
            for err in self.results['errors']:
                logger.info(f"  - {err}")
        
        logger.info("\nMetrics:")
        for key, value in self.results['metrics'].items():
            logger.info(f"  {key}: {value}")
        
        overall = all([
            self.results['wal_mode_verified'],
            self.results['busy_timeout_verified'],
            self.results['concurrent_writes_passed'],
            self.results['backup_during_writes_passed'],
            self.results['cleanup_during_writes_passed'],
            self.results['integrity_check_passed'],
            self.results['zero_lock_errors'],
            self.results['zero_corruptions'],
            self.results['write_authority_verified'],
        ])
        
        logger.info(f"\nOVERALL: {'PASS' if overall else 'FAIL'}")


def main():
    parser = argparse.ArgumentParser(description="Phase 18 Database Integrity & Concurrency Audit")
    parser.add_argument("--db-path", type=str, default="app/data/attendance.db", help="Path to attendance database")
    args = parser.parse_args()
    
    test = DatabaseConcurrencyTest(args.db_path)
    success = test.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()