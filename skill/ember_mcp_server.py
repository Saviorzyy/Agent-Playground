#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         Ember Protocol — MCP Server for Hermes/Claude Agent Integration      ║
║                         标准 MCP (Model Context Protocol) 接入               ║
╚══════════════════════════════════════════════════════════════════════════════╝

Architecture (PRD §6 & §8):
  Game Server ←─WebSocket─→ Ember MCP Server ←──stdio MCP──→ Hermes/Claude
                                (this file)

The MCP server exposes 3 tools to the agent:
  - ember_tick:   Wait for game tick, return full state with action guide
  - ember_act:    Submit actions to game, return results
  - ember_status: Query agent state (HP, energy, inventory, position)

Quick Start — Configure in Hermes (~/.hermes/config.yaml):
  mcp_servers:
    ember:
      command: python3
      args:
        - "/path/to/ember_mcp_server.py"
        - "--token"
        - "et_xxx"
        - "--server"
        - "ws://localhost:8765"

Or register on first run:
  python ember_mcp_server.py --register --name "MyAgent" --api-url http://localhost:8765

Dependencies: pip install websockets mcp requests
"""

from __future__ import annotations
import asyncio, json, sys, os, argparse
from typing import Optional

import websockets
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types


# ═══════════════════════════════════════════════════════════════════════════════
# Game Client — WebSocket bridge
# ═══════════════════════════════════════════════════════════════════════════════

class GameClient:
    """Manages WebSocket connection to game server."""

    def __init__(self, server_url: str, token: str):
        self.url = server_url.rstrip("/")
        self.token = token
        self.ws = None
        self.agent_id: Optional[str] = None
        self.agent_name: Optional[str] = None
        self._tick_q: asyncio.Queue = asyncio.Queue()
        self._result_q: asyncio.Queue = asyncio.Queue()
        self._event_q: asyncio.Queue = asyncio.Queue()
        self._ok = False
        self._tick_n = 0
        self._state = {}

    async def connect(self) -> dict:
        self.ws = await websockets.connect(f"{self.url}/ws/game?token={self.token}")
        session = json.loads(await self.ws.recv())
        if session.get("type") != "session":
            raise RuntimeError(f"Expected session, got {session.get('type')}")
        self.agent_id = session["agent_id"]
        self.agent_name = session["agent_name"]
        self._state = session.get("state", {})
        await self.ws.send(json.dumps({"type": "ready"}))
        self._ok = True
        asyncio.create_task(self._reader())
        print(f"[Ember MCP] Connected: {self.agent_name} ({self.agent_id})", file=sys.stderr)
        return session

    async def _reader(self):
        try:
            async for raw in self.ws:
                frame = json.loads(raw)
                t = frame.get("type")
                if t == "tick":
                    self._tick_n = frame.get("tick", 0)
                    await self._tick_q.put(frame)
                elif t == "result":
                    await self._result_q.put(frame)
                elif t == "event":
                    await self._event_q.put(frame)
                elif t == "ping":
                    try:
                        await self.ws.send(json.dumps({"type": "pong", "ts": frame.get("ts")}))
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Ember MCP] Connection closed: {e}", file=sys.stderr)
            self._ok = False

    async def wait_tick(self, timeout=8.0) -> dict:
        return await asyncio.wait_for(self._tick_q.get(), timeout=timeout)

    async def send_actions(self, tick: int, actions: list[dict], timeout=5.0) -> dict:
        await self.ws.send(json.dumps({"type": "actions", "tick": tick, "actions": actions}))
        return await asyncio.wait_for(self._result_q.get(), timeout=timeout)

    @property
    def state(self): return self._state
    @property
    def connected(self): return self._ok
    @property
    def tick_number(self): return self._tick_n


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

ACTIONS_GUIDE = """## 可用行动

| 行动 | 参数 | 能量 |
|------|------|------|
| move | direction:"north"\|"south"\|"east"\|"west" | 1 |
| mine | target:{x,y} | 2 |
| chop | target:{x,y} | 2 |
| craft | recipe:"配方ID" | 3 |
| build | building_type, target:{x,y} | 5 |
| rest | — | +3恢复 |
| scan | — | 2 |
| inspect | target:"inventory"\|"self"\|"recipes"\|"map" | 0 |
| equip | item_id, slot:"main_hand" | 0 |
| pickup | — | 1 |
| drop | item_id, amount | 0 |
| radio_broadcast | content:"消息" | 1 |
| radio_scan | — | 1 |
| talk | target_agent, content | 0 |
| use | item_id:"repair_kit"\|"battery"\|"radiation_antidote" | 1 |

## 策略提示
- **每tick做3-5个行动**，不要只做一个
- 视野中标注⛏的资源带坐标(x,y)，指定target去采集
- 教程Phase 0: inspect(inventory)一次进入自由模式
- 能量<30时加入rest
- 返回纯JSON数组，如: [{"type":"move","direction":"north"},{"type":"scan"}]"""


def _fmt_tick(frame: dict) -> str:
    """Format tick frame as readable Markdown for the agent."""
    msgs = frame.get("messages", [])
    parts = []
    for m in msgs:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "system":
            parts.append(f"**[系统]** {content}")
        else:
            parts.append(content)
    text = "\n\n".join(parts)
    text += f"\n\n{ACTIONS_GUIDE}"
    text += f"\n\n请分析游戏状态，决定行动。以JSON数组格式返回。"
    return text


def _fmt_result(frame: dict) -> str:
    """Format result frame."""
    results = frame.get("results", [])
    lines = [f"## 行动结果 (Tick {frame.get('tick', '?')})", ""]
    for r in results:
        icon = "✅" if r.get("success") else "❌"
        lines.append(f"- {icon} **{r.get('type')}**: {r.get('detail', r.get('error_code', ''))}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# MCP Server
# ═══════════════════════════════════════════════════════════════════════════════

def create_mcp_server(game: GameClient) -> Server:
    server = Server("ember-protocol")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="ember_tick",
                description="等待游戏服务器推送下一个tick。返回完整游戏状态：自身HP/能量/位置、视野内可采集资源(带坐标)、附近智能体、教程提示。这是你感知世界的核心方式，必须频繁调用。",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            types.Tool(
                name="ember_act",
                description="向游戏服务器提交行动。每次最多10个。必须在ember_tick之后调用，使用同一个tick号。返回每个行动的执行结果。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tick": {"type": "integer", "description": "当前tick号(从ember_tick获得)"},
                        "actions": {"type": "array", "description": "行动列表", "items": {"type": "object"}},
                    },
                    "required": ["tick", "actions"],
                },
            ),
            types.Tool(
                name="ember_status",
                description="查看自身完整状态：位置、HP、能量、背包物品、装备、备份机体数。不消耗游戏内能量。",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name == "ember_tick":
            frame = await game.wait_tick()
            return [types.TextContent(type="text", text=_fmt_tick(frame))]

        elif name == "ember_act":
            tick = arguments.get("tick", game.tick_number)
            actions = arguments.get("actions", [])
            if not actions:
                return [types.TextContent(type="text", text="未提交行动。")]
            result = await game.send_actions(tick, actions[:10])
            return [types.TextContent(type="text", text=_fmt_result(result))]

        elif name == "ember_status":
            s = game.state
            lines = [
                "## 智能体状态",
                f"- 名称: {game.agent_name}  ID: {game.agent_id}",
                f"- 位置: {s.get('position', '?')}",
                f"- HP: {s.get('health', '?')}/{s.get('max_health', '?')}",
                f"- 能量: {s.get('energy', '?')}/100",
                f"- 手持: {s.get('held_item') or '空手'}",
                f"- 备份机体: {s.get('backup_count', 0)}",
                f"- 背包: {s.get('inventory_summary', '空')}",
            ]
            if s.get("tutorial_phase") is not None:
                lines.append(f"- 教程: Phase {s['tutorial_phase']}")
            return [types.TextContent(type="text", text="\n".join(lines))]

        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser(description="Ember Protocol MCP Server")
    parser.add_argument("--token", default="", help="Game token (et_xxx)")
    parser.add_argument("--server", default="ws://localhost:8765", help="Game server WS URL")
    parser.add_argument("--register", action="store_true", help="Register new agent first")
    parser.add_argument("--name", default="Hermes", help="Agent name (for --register)")
    parser.add_argument("--head", default="high", choices=["high", "mid", "low"], help="头部等级")
    parser.add_argument("--torso", default="mid", choices=["high", "mid", "low"], help="躯干等级")
    parser.add_argument("--loco", default="low", choices=["high", "mid", "low"], help="运动机构等级")
    parser.add_argument("--api-url", default="http://localhost:8765", help="HTTP API URL")
    args = parser.parse_args()

    if args.register:
        import requests as req
        resp = req.post(f"{args.api_url}/api/v1/auth/register", json={
            "agent_name": args.name,
            "chassis": {
                "head": {"tier": args.head},
                "torso": {"tier": args.torso},
                "locomotion": {"tier": args.loco},
            },
        }, timeout=10)
        if resp.status_code != 200:
            print(f"Register failed: {resp.text}", file=sys.stderr)
            sys.exit(1)
        data = resp.json()
        args.token = data["game_token"]
        print(f"Registered: {data['agent_id']}", file=sys.stderr)
        print(f"Token: {args.token}", file=sys.stderr)

    if not args.token:
        print("Error: --token required (or use --register)", file=sys.stderr)
        sys.exit(1)

    game = GameClient(args.server, args.token)
    await game.connect()
    mcp = create_mcp_server(game)

    async with stdio_server() as (read, write):
        await mcp.run(read, write, mcp.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
