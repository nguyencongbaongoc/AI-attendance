#!/usr/bin/env python3
"""
Phase 41A-D Final Validation Script
Tests all backend endpoints, WebSocket, SSE, and frontend build
"""

import requests
import websocket
import subprocess
import sys
import os

def test_backend_endpoints(base_url):
    """Test all REST API endpoints"""
    endpoints = [
        ('Health system', '/api/v1/health/system'),
        ('Health cameras', '/api/v1/health/cameras'),
        ('Health GPU', '/api/v1/health/gpu'),
        ('Health metrics', '/api/v1/health/metrics'),
        ('Attendance summary', '/api/v1/attendance/summary'),
        ('Attendance records', '/api/v1/attendance/records'),
        ('Attendance stats', '/api/v1/attendance/stats'),
        ('Persons', '/api/v1/persons'),
        ('Enrolled persons', '/api/v1/persons/enrollment/persons'),
        ('Enrollment stats', '/api/v1/persons/enrollment/stats'),
        ('Timetable', '/api/v1/timetable'),
        ('Timetable entries', '/api/v1/timetable/entries'),
        ('Excel exports', '/api/v1/excel/exports'),
        ('Parents', '/api/v1/parents'),
        ('Telegram queue stats', '/api/v1/telegram/queue/stats'),
        ('Queue metrics', '/api/v1/health/queue/metrics'),
        ('Queue alerts', '/api/v1/health/queue/alerts'),
    ]

    print('Testing REST endpoints:')
    all_pass = True
    for name, path in endpoints:
        try:
            resp = requests.get(base_url + path, timeout=5)
            status = 'PASS' if resp.status_code == 200 else 'FAIL ({})'.format(resp.status_code)
            if resp.status_code != 200:
                all_pass = False
            print('  {}: {}'.format(name, status))
        except Exception as e:
            print('  {}: ERROR - {}'.format(name, e))
            all_pass = False
    return all_pass

def test_websocket(base_url):
    """Test WebSocket connection"""
    print()
    print('Testing WebSocket:')
    try:
        ws_url = base_url.replace('http://', 'ws://') + '/api/v1/health/ws'
        ws = websocket.create_connection(ws_url)
        result = ws.recv()
        print('  WebSocket: PASS (received {} chars)'.format(len(result)))
        ws.close()
        return True
    except Exception as e:
        print('  WebSocket: ERROR - {}'.format(e))
        return False

def test_sse(base_url):
    """Test SSE endpoint"""
    print()
    print('Testing SSE:')
    try:
        resp = requests.get(base_url + '/api/v1/health/stream', timeout=5, stream=True)
        if resp.status_code == 200:
            for line in resp.iter_lines():
                if line:
                    print('  SSE: PASS (received event)')
                    return True
        else:
            print('  SSE: FAIL ({})'.format(resp.status_code))
            return False
    except Exception as e:
        print('  SSE: ERROR - {}'.format(e))
        return False

def test_frontend_build():
    """Test frontend TypeScript and build"""
    print()
    print('Testing Frontend:')
    figma_dir = os.path.join(os.path.dirname(__file__), '..', 'figma')
    
    # TypeScript check
    try:
        result = subprocess.run(['npx', 'tsc', '--noEmit'], cwd=figma_dir, capture_output=True, text=True, timeout=60, shell=True)
        if result.returncode == 0:
            print('  TypeScript: PASS')
            ts_pass = True
        else:
            print('  TypeScript: FAIL')
            print('  {}'.format(result.stdout))
            print('  {}'.format(result.stderr))
            ts_pass = False
    except Exception as e:
        print('  TypeScript: ERROR - {}'.format(e))
        ts_pass = False
    
    # Build check
    try:
        result = subprocess.run(['npm', 'run', 'build'], cwd=figma_dir, capture_output=True, text=True, timeout=60, shell=True)
        if result.returncode == 0:
            print('  Vite Build: PASS')
            build_pass = True
        else:
            print('  Vite Build: FAIL')
            print('  {}'.format(result.stdout))
            print('  {}'.format(result.stderr))
            build_pass = False
    except Exception as e:
        print('  Vite Build: ERROR - {}'.format(e))
        build_pass = False
    
    return ts_pass and build_pass

def test_backend_tests():
    """Run backend unit tests"""
    print()
    print('Testing Backend Unit Tests:')
    try:
        result = subprocess.run([
            sys.executable, '-m', 'pytest',
            'tests/unit/test_streaming_health.py',
            'tests/unit/test_attendance_engine.py',
            'tests/unit/test_timetable_loader.py',
            'tests/unit/test_parent_registry.py',
            'tests/unit/test_policy_engine.py',
            '-v', '--tb=short'
        ], capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            print('  Backend Tests: PASS')
            return True
        else:
            print('  Backend Tests: FAIL')
            print('  {}'.format(result.stdout[-2000:]))
            return False
    except Exception as e:
        print('  Backend Tests: ERROR - {}'.format(e))
        return False

def main():
    base_url = 'http://localhost:8008'
    
    print('=' * 50)
    print('PHASE 41A-D FINAL VALIDATION')
    print('=' * 50)
    print()
    
    all_pass = True
    
    # Test backend endpoints
    all_pass &= test_backend_endpoints(base_url)
    
    # Test WebSocket
    all_pass &= test_websocket(base_url)
    
    # Test SSE
    all_pass &= test_sse(base_url)
    
    # Test frontend
    all_pass &= test_frontend_build()
    
    # Test backend tests
    all_pass &= test_backend_tests()
    
    print()
    print('=' * 50)
    if all_pass:
        print('OVERALL: ALL TESTS PASS - PRODUCTION READY')
    else:
        print('OVERALL: SOME TESTS FAILED - PASS_WITH_DOCUMENTED_LIMITATIONS')
    print('=' * 50)
    
    return 0 if all_pass else 1

if __name__ == '__main__':
    sys.exit(main())