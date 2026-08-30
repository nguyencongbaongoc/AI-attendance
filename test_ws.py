import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:11415/api/v1/health/ws"
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to WebSocket")
            
            # Receive initial snapshot
            message = await websocket.recv()
            data = json.loads(message)
            print(f"Received initial snapshot: type={data.get('type')}, seq={data.get('seq')}")
            print(f"Overall status: {data.get('overall_status')}")
            print(f"Components: {len(data.get('components', []))}")
            
            # Send ping
            await websocket.send(json.dumps({"type": "ping"}))
            pong = await websocket.recv()
            print(f"Pong received: {pong}")
            
            # Wait for one health update
            message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            data = json.loads(message)
            print(f"Received health update: type={data.get('type')}, seq={data.get('seq')}")
            
            print("WebSocket test PASSED")
    except Exception as e:
        print(f"WebSocket test FAILED: {e}")

asyncio.run(test_websocket())