"""Ember Protocol — Demo Agent with full behavior loop"""
import asyncio, json, random, sys
import websockets, requests

BASE = "http://localhost:8765"
WS = "ws://localhost:8765"

AGENT_NAME = sys.argv[1] if len(sys.argv) > 1 else "DemoBot"
CHASSIS = {
    "head": {"tier": "high"},      # PER=3, cost=3
    "torso": {"tier": "mid"},      # CON=2, cost=2
    "locomotion": {"tier": "low"}, # AGI=1, cost=1
}

TICK_ACTIONS = {
    0: "register",
    1: "ready",
    2: "inspect_inventory",
    3: "move_out",
    4: "inspect_map",
    5: "scan_area",
    6: "mine_if_possible",
    7: "drop_excess",
    8: "rest",
}


async def run():
    print(f"\n{'='*60}")
    print(f"  🔥 余烬协议 — Demo Agent: {AGENT_NAME}")
    print(f"{'='*60}")

    # 1. Register
    print("\n📋 Step 1: 注册角色")
    resp = requests.post(f"{BASE}/api/v1/auth/register", json={
        "agent_name": AGENT_NAME, "chassis": CHASSIS,
    })
    data = resp.json()
    agent_id = data["agent_id"]
    token = data["game_token"]
    pos = data["spawn_location"]
    print(f"   Agent ID: {agent_id}")
    print(f"   出生点: ({pos['x']}, {pos['y']})")
    print(f"   Token: {token[:20]}...")

    # 2. Connect
    print("\n🔌 Step 2: WebSocket 连接")
    ws = await websockets.connect(f"{WS}/ws/game?token={token}")
    session = json.loads(await ws.recv())
    state = session.get("state", {})
    print(f"   连接成功! tutorial_phase={session['tutorial_phase']}")
    print(f"   HP={state['health']} 能量={state['energy']}")
    print(f"   背包: {state['inventory_summary']}")

    # 3. Ready
    await ws.send(json.dumps({"type": "ready"}))
    print("\n✅ Step 3: 发送 Ready")

    # 4. Game loop
    print(f"\n{'='*60}")
    print(f"  🎮 游戏循环开始")
    print(f"{'='*60}")

    tick_count = 0
    mined = False
    scanned = False
    moved = False

    for tick_count in range(1, 12):
        # Wait for tick
        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
        frame = json.loads(msg)

        if frame["type"] == "tick":
            tn = frame["tick"]
            messages = frame.get("messages", [])
            user_content = ""
            for m in messages:
                if m.get("role") == "user":
                    user_content = m.get("content", "")

            # Decide actions based on game state
            actions = []

            if tick_count == 1:
                # First tick: inspect inventory
                actions = [{"type": "inspect", "target": "inventory"}]
                print(f"\n📦 Tick {tn}: 查看背包")

            elif tick_count == 2:
                # Move north to leave drop pod
                actions = [{"type": "move", "direction": "north"}]
                print(f"\n🚶 Tick {tn}: 向北移动")

            elif tick_count == 3:
                actions = [{"type": "move", "direction": "north"}]
                print(f"\n🚶 Tick {tn}: 继续向北")

            elif tick_count == 4:
                # Inspect map to see surroundings
                actions = [{"type": "inspect", "target": "map"}]
                print(f"\n🗺️ Tick {tn}: 查看地图")

            elif tick_count == 5:
                # Scan for ores
                if not scanned:
                    actions = [{"type": "scan"}]
                    print(f"\n📡 Tick {tn}: 探测矿脉")
                    scanned = True
                else:
                    actions = [{"type": "rest"}]
                    print(f"\n😴 Tick {tn}: 休息恢复能量")

            elif tick_count == 6:
                # Try to mine if we see stone
                actions = [
                    {"type": "move", "direction": "east"},
                ]
                print(f"\n🚶 Tick {tn}: 东移探索")

            elif tick_count == 7:
                # Radio broadcast to find other agents
                actions = [{"type": "radio_broadcast", "content": f"这里是{AGENT_NAME}，有人收到吗？"}]
                print(f"\n📻 Tick {tn}: 无线电广播")

            elif tick_count == 8:
                # Radio scan
                actions = [{"type": "radio_scan"}]
                print(f"\n🔍 Tick {tn}: 扫描附近Agent")

            elif tick_count == 9:
                # Inspect recipes
                actions = [{"type": "inspect", "target": "recipes"}]
                print(f"\n📖 Tick {tn}: 查看合成配方")

            elif tick_count == 10:
                # Inspect self
                actions = [{"type": "inspect", "target": "self"}]
                print(f"\n👤 Tick {tn}: 查看自身状态")

            else:
                # Rest to demonstrate energy recovery
                actions = [{"type": "rest"}]
                print(f"\n😴 Tick {tn}: 休息")

            # Send actions
            if actions:
                await ws.send(json.dumps({"type": "actions", "tick": tn, "actions": actions}))
                print(f"   ➤ 发送 {len(actions)} 个行动: {[a['type'] for a in actions]}")

        elif frame["type"] == "result":
            results = frame.get("results", [])
            for r in results:
                status = "✅" if r.get("success") else "❌"
                detail = r.get("detail", r.get("error_code", ""))
                print(f"   {status} {r['type']}: {detail}")

                # Show extra info
                if r["type"] == "inspect" and r.get("success"):
                    if "items" in r:
                        item_strs = [f"{i['item_id']}x{i['amount']}" for i in r['items']]
                    print(f"      物品: {item_strs}")
                    if "recipes" in r:
                        print(f"      配方数: {len(r['recipes'])}")
                    if "state" in r:
                        s = r["state"]
                        print(f"      HP={s['health']}/{s['max_health']} 能量={s['energy']}")

                if r["type"] == "scan" and r.get("success"):
                    found = r.get("found", [])
                    if found:
                        for f in found[:3]:
                            print(f"      发现矿脉: {f['ore']} 在 ({f['x']},{f['y']})")

                if r["type"] == "radio_scan" and r.get("success"):
                    agents = r.get("agents", [])
                    if agents:
                        for a in agents:
                            print(f"      附近: {a['name']} 距离{a['distance']}格")
                    else:
                        print(f"      附近无其他Agent在线")

        elif frame["type"] == "error":
            print(f"   ❌ 错误: {frame.get('error_code')}: {frame.get('detail')}")

        elif frame["type"] == "event":
            print(f"   ⚡ 事件: {frame.get('event')} — {frame.get('data', {})}")

    # Show final state
    resp = requests.get(f"{BASE}/api/v1/agents")
    agents = resp.json()["agents"]
    for a in agents:
        if a["agent_id"] == agent_id:
            print(f"\n{'='*60}")
            print(f"  📊 最终状态")
            print(f"{'='*60}")
            print(f"  位置: ({a['position'][0]}, {a['position'][1]})")
            print(f"  HP: {a['health']}/{a['max_health']}")
            print(f"  能量: {a['energy']}/100")
            print(f"  手持: {a['held']}")
            print(f"  在线: {'是' if a['online'] else '否'}")

    await ws.close()
    print(f"\n✅ Demo Agent 运行完成 (共 {tick_count} ticks)")


asyncio.run(run())
