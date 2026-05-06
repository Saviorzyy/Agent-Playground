"""Ember Protocol — Agent Test Client

WebSocket client that connects to the game server and simulates an agent.
Can be used for automated testing and as a reference implementation for
Skill/MCP plugins.
"""
from __future__ import annotations
import asyncio
import json
import sys
import argparse
import websockets


class EmberAgent:
    """Test agent that connects to the game server via WebSocket."""

    def __init__(self, server_url: str, token: str, agent_name: str = "TestAgent"):
        self.server_url = server_url
        self.token = token
        self.agent_name = agent_name
        self.ws = None
        self.state = {}
        self.tick = 0
        self.connected = False
        self.action_log: list[dict] = []

    async def connect(self):
        """Connect to the game server."""
        ws_url = f"{self.server_url}/ws/game?token={self.token}"
        print(f"Connecting to {ws_url}")
        self.ws = await websockets.connect(ws_url)
        self.connected = True
        print("Connected!")

        # Wait for session frame
        session = json.loads(await self.ws.recv())
        print(f"Session: {json.dumps(session, indent=2)}")
        self.state = session.get("state", {})

        # Send ready
        await self.ws.send(json.dumps({"type": "ready"}))
        print("Ready sent")

        # Start game loop
        await self._game_loop()

    async def _game_loop(self):
        """Main game loop - receive tick, decide, send actions."""
        while self.connected:
            try:
                raw = await self.ws.recv()
                frame = json.loads(raw)
                frame_type = frame.get("type")

                if frame_type == "tick":
                    self.tick = frame.get("tick", 0)
                    actions = self._decide_actions(frame)
                    if actions:
                        await self.ws.send(json.dumps({
                            "type": "actions",
                            "tick": self.tick,
                            "actions": actions,
                        }))
                        self.action_log.append({"tick": self.tick, "actions": actions})

                elif frame_type == "result":
                    results = frame.get("results", [])
                    for r in results:
                        status = "✓" if r.get("success") else "✗"
                        print(f"  [{status}] {r.get('type')}: {r.get('detail', r.get('error_code', ''))}")

                elif frame_type == "event":
                    print(f"  [Event] {frame.get('event')}: {frame.get('data', {})}")

                elif frame_type == "ping":
                    await self.ws.send(json.dumps({"type": "pong", "ts": frame.get("ts")}))

                elif frame_type == "error":
                    print(f"  [Error] {frame.get('error_code')}: {frame.get('detail')}")

            except websockets.ConnectionClosed:
                print("Connection closed")
                self.connected = False
                break
            except Exception as e:
                print(f"Error: {e}")
                break

    def _decide_actions(self, frame: dict) -> list[dict]:
        """Agent decision logic. Override for custom behavior."""
        # Default: just rest to save energy
        return []  # Empty actions = do nothing this tick

    async def disconnect(self):
        self.connected = False
        if self.ws:
            await self.ws.close()


class TutorialAgent(EmberAgent):
    """Agent that follows the tutorial phases automatically."""

    def _decide_actions(self, frame: dict) -> list[dict]:
        messages = frame.get("messages", [])
        user_content = ""
        for m in messages:
            if m.get("role") == "user":
                user_content = m.get("content", "")

        tutorial_phase = self.state.get("tutorial_phase")

        if tutorial_phase == 0:
            # Inspect inventory
            return [{"type": "inspect", "target": "inventory"}]
        elif tutorial_phase == 1:
            return [{"type": "inspect", "target": "self"}]
        elif tutorial_phase == 2:
            return [{"type": "inspect", "target": "recipes"}]
        else:
            return [{"type": "rest"}]


class ExplorerAgent(EmberAgent):
    """Agent that explores by moving randomly."""

    def _decide_actions(self, frame: dict) -> list[dict]:
        import random
        actions = []
        # Random direction
        d = random.choice(["north", "south", "east", "west"])
        actions.append({"type": "move", "direction": d})
        # Sometimes scan
        if random.random() < 0.1:
            actions.append({"type": "scan"})
        return actions


class ResourceAgent(EmberAgent):
    """Agent that mines and collects resources."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = "explore"  # explore, mine, craft

    def _decide_actions(self, frame: dict) -> list[dict]:
        import random
        actions = []
        messages = frame.get("messages", [])
        user_content = ""
        for m in messages:
            if m.get("role") == "user":
                user_content = m.get("content", "")

        # Check vicinity for minable resources
        if "石料" in user_content and self.mode == "explore":
            self.mode = "mine"
            # Parse coordinates from vicinity
            actions.append({"type": "mine", "target": {"x": 100, "y": 100}})
        else:
            # Move randomly
            d = random.choice(["north", "south", "east", "west"])
            actions.append({"type": "move", "direction": d})

        return actions


async def main():
    parser = argparse.ArgumentParser(description="Ember Protocol Agent Client")
    parser.add_argument("--server", default="ws://localhost:8765", help="Server URL")
    parser.add_argument("--token", required=True, help="Game token")
    parser.add_argument("--type", choices=["tutorial", "explorer", "resource", "dummy"],
                        default="dummy", help="Agent type")
    args = parser.parse_args()

    agent_classes = {
        "tutorial": TutorialAgent,
        "explorer": ExplorerAgent,
        "resource": ResourceAgent,
        "dummy": EmberAgent,
    }
    agent_cls = agent_classes[args.type]
    agent = agent_cls(args.server, args.token)

    try:
        await agent.connect()
    except KeyboardInterrupt:
        print("\nDisconnecting...")
        await agent.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
