"""Ember Protocol — E2E Test using WebSocket Agent Client"""
import asyncio
import json
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import websockets
import requests


BASE_URL = "http://localhost:8765"
WS_URL = "ws://localhost:8765"


async def recv_timeout(ws, timeout=5.0):
    """Receive with timeout."""
    try:
        return await asyncio.wait_for(ws.recv(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


async def e2e_test():
    """Full E2E test: register, connect, play tutorial, verify systems."""
    print("=" * 60)
    print("Ember Protocol E2E Test")
    print("=" * 60)

    # 1. Register agent
    print("\n--- 1. Register Agent ---")
    resp = requests.post(f"{BASE_URL}/api/v1/auth/register", json={
        "agent_name": "TestBot",
        "chassis": {
            "head": {"tier": "high"},
            "torso": {"tier": "mid"},
            "locomotion": {"tier": "low"},
        }
    })
    assert resp.status_code == 200, f"Register failed: {resp.text}"
    data = resp.json()
    agent_id = data["agent_id"]
    token = data["game_token"]
    print(f"  Agent: {agent_id}")
    print(f"  Token: {token[:20]}...")

    # 2. Connect via WebSocket
    print("\n--- 2. WebSocket Connection ---")
    ws = await websockets.connect(f"{WS_URL}/ws/game?token={token}")

    # Receive session frame
    session = json.loads(await ws.recv())
    assert session["type"] == "session"
    assert session["agent_id"] == agent_id
    print(f"  Session received: tutorial_phase={session['tutorial_phase']}")

    # Send ready
    await ws.send(json.dumps({"type": "ready"}))
    print("  Ready sent")

    # 3. Wait for first tick and respond
    print("\n--- 3. Game Loop Test ---")

    # Receive first tick
    tick_raw = await ws.recv()
    tick_frame = json.loads(tick_raw)
    print(f"  Frame 1: type={tick_frame['type']} tick={tick_frame.get('tick')}")
    assert tick_frame["type"] == "tick"
    tick_num = tick_frame["tick"]

    # Send actions immediately
    actions_msg = json.dumps({
        "type": "actions",
        "tick": tick_num,
        "actions": [
            {"type": "inspect", "target": "inventory"},
            {"type": "rest"},
        ],
    })
    await ws.send(actions_msg)
    print(f"  Sent actions for tick {tick_num}")

    # Now receive ALL pending frames and categorize them
    frames_received = []
    result_received = False
    for i in range(10):  # receive up to 10 frames
        msg = await recv_timeout(ws, timeout=3.0)
        if msg is None:
            print(f"  No more messages after {len(frames_received)} frames")
            break
        frame = json.loads(msg)
        frames_received.append(frame)
        ftype = frame.get("type")
        ftick = frame.get("tick", "?")
        print(f"  Frame {i+2}: type={ftype} tick={ftick}")

        if ftype == "result":
            result_received = True
            results = frame.get("results", [])
            for r in results:
                status = "✓" if r.get("success") else "✗"
                print(f"    > {status} {r.get('type')}: {r.get('detail', r.get('error_code', ''))}")
            break  # Got our result!
        elif ftype == "error":
            print(f"    ERROR: {frame.get('error_code')} - {frame.get('detail')}")
        elif ftype == "tick" and len(frames_received) > 3:
            # Too many ticks without result = failure
            print("    WARNING: No result frame received after multiple ticks!")
            break

    assert result_received, "Result frame was NOT received!"
    print("  ✓ Result frame received successfully")

    # 4. Verify result content
    results_list = frames_received[-1].get("results", [])
    inspect_result = None
    for r in results_list:
        if r.get("type") == "inspect":
            inspect_result = r
            break

    if inspect_result and inspect_result.get("success"):
        items = inspect_result.get("items", [])
        item_ids = [i["item_id"] for i in items]
        assert "workbench" in item_ids, f"No workbench in inventory: {item_ids}"
        assert "furnace" in item_ids, f"No furnace in inventory: {item_ids}"
        print(f"  ✓ Inventory verified: {item_ids}")

    # 5. Test movement
    print("\n--- 4. Move Test ---")
    # Wait for next tick
    next_tick = None
    for i in range(10):
        msg = await recv_timeout(ws, timeout=3.0)
        if msg is None:
            break
        frame = json.loads(msg)
        if frame["type"] == "tick":
            next_tick = frame
            break

    if next_tick is None:
        print("  Could not receive next tick, aborting move test")
        await ws.close()
        return

    tick_num = next_tick["tick"]
    await ws.send(json.dumps({
        "type": "actions",
        "tick": tick_num,
        "actions": [{"type": "move", "direction": "north"}],
    }))

    # Wait for result
    for i in range(10):
        msg = await recv_timeout(ws, timeout=3.0)
        if msg is None:
            break
        frame = json.loads(msg)
        if frame["type"] == "result":
            for r in frame["results"]:
                status = "✓" if r.get("success") else "✗"
                print(f"  {status} {r.get('type')}: {r.get('detail', r.get('error_code', ''))}")
            break

    # 6. Check server status
    print("\n--- 5. Server Status ---")
    status = requests.get(f"{BASE_URL}/api/v1/status").json()
    agents = requests.get(f"{BASE_URL}/api/v1/agents").json()
    print(f"  Tick: {status['tick']}")
    print(f"  Agents: {status['agents_online']}/{status['agents_total']} online")
    for a in agents.get("agents", []):
        print(f"    {a['name']} at ({a['position'][0]},{a['position'][1]}) HP={a['health']} E={a['energy']}")

    await ws.close()

    print("\n" + "=" * 60)
    if result_received:
        print("✅ E2E Test PASSED")
    else:
        print("❌ E2E Test FAILED - No result frame")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(e2e_test())
