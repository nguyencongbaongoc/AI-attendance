#!/usr/bin/env python3
"""
Phase 44 — WebSocket Diagnostic Probe.
Tests the actual WebSocket endpoint from the running backend.
"""

import asyncio
import json
import sys
import websockets


async def test_websocket():
    """Test WebSocket connection to the backend."""
    ws_url = "ws://localhost:17095/api/v1/health/ws"
    
    print(f"[INFO] Connecting to {ws_url}")
    
    try:
        async with websockets.connect(ws_url) as ws:
            print("[SUCCESS] WebSocket connection established")
            
            # Wait for initial message
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print(f"[RECEIVED] Initial message: {message}")
                
                # Try to parse as JSON
                try:
                    data = json.loads(message)
                    print(f"[PARSED] Type: {data.get('type', 'unknown')}")
                    print(f"[PARSED] Keys: {list(data.keys())}")
                except json.JSONDecodeError:
                    print("[WARN] Message is not valid JSON")
                    
            except asyncio.TimeoutError:
                print("[WARN] No initial message received within 5 seconds")
            
            # Wait for subsequent messages (heartbeat/realtime events)
            print("[INFO] Waiting for subsequent messages (10 seconds)...")
            message_count = 0
            try:
                while message_count < 5:
                    message = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    message_count += 1
                    print(f"[RECEIVED #{message_count}] {message[:200]}...")
                    
                    try:
                        data = json.loads(message)
                        print(f"  Type: {data.get('type', 'unknown')}")
                    except json.JSONDecodeError:
                        print("  [WARN] Not valid JSON")
                        
            except asyncio.TimeoutError:
                print(f"[INFO] No more messages after {message_count} messages")
            
            print("[SUCCESS] WebSocket test completed")
            return True
            
    except websockets.exceptions.InvalidURI:
        print("[ERROR] Invalid WebSocket URI")
        return False
    except websockets.exceptions.InvalidHandshake as e:
        print(f"[ERROR] WebSocket handshake failed: {e}")
        return False
    except ConnectionRefusedError:
        print("[ERROR] Connection refused - WebSocket endpoint not available")
        return False
    except Exception as e:
        print(f"[ERROR] Unexpected error: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    result = asyncio.run(test_websocket())
    sys.exit(0 if result else 1)