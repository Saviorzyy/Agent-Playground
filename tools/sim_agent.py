#!/usr/bin/env python3
"""Ember Protocol — Simulated Agent (Agent-Pull REST Client)

A lightweight REST client that polls the Ember server for game state
and submits action commands. Demonstrates the Agent-Pull interaction model.

Usage:
    python tools/sim_agent.py [--server http://localhost:8000] [--name Echo] [--strategy survival]

Strategies:
    - survival:  Gather resources, craft tools, build shelter (default)
    - explore:   Move around the map, inspect everything
    - combat:    Seek and attack creatures
    - idle:      Just rest every tick
"""

from __future__ import annotations
import argparse
import json
import logging
import random
import sys
import os
import time
from typing import Optional

import httpx

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("sim_agent")


class AgentBrain:
    """Decision engine — receives game state, returns actions."""

    def __init__(self, strategy: str = "survival"):
        self.strategy = strategy
        self.tick_count = 0
        self.last_position = None
        self.pending_build = None  # (building_type, x, y)
        self.phase = "gather"  # gather -> craft -> build -> defend
        self.crafted_tools = set()
        self.direction_bias = [0, 1]  # prefer moving right/down
        self.stuck_count = 0

    def decide(self, state: dict) -> list[dict]:
        """Given game state dict, return list of actions (max 5)."""
        self.tick_count += 1
        actions = []

        self_state = state.get("self", {})
        vicinity = state.get("vicinity", {})
        pending = state.get("pending", [])
        meta = state.get("meta", {})

        # Skip if state is empty or agent is dead
        if not self_state or not self_state.get("alive", True):
            return [{"type": "rest"}]

        hp = self_state.get("health", 100)
        max_hp = self_state.get("max_health", 100)
        energy = self_state.get("energy", 100)
        max_energy = self_state.get("max_energy", 100)
        pos = self_state.get("position", {"x": 0, "y": 0})
        effects = self_state.get("active_effects", [])
        held = self_state.get("held_item")
        status = self_state.get("status", "idle")

        # If traveling, just rest — we can't take meaningful actions
        if status == "traveling":
            return [{"type": "rest"}]

        # Track stuck detection
        if pos == self.last_position:
            self.stuck_count += 1
        else:
            self.stuck_count = 0
        self.last_position = pos.copy()

        # ─── Emergency: low HP ───────────────────────────────
        if hp < max_hp * 0.3 and energy >= 1:
            # Try to use a repair kit
            actions.append({"type": "use", "item": "repair_kit"})

        # ─── Emergency: radiation ─────────────────────────────
        if any("radiation" in str(e).lower() for e in effects) and energy >= 1:
            actions.append({"type": "use", "item": "radiation_antidote"})

        # ─── Strategy dispatch ────────────────────────────────
        if self.strategy == "idle":
            actions.append({"type": "rest"})

        elif self.strategy == "explore":
            actions.extend(self._explore_actions(state, energy))

        elif self.strategy == "combat":
            actions.extend(self._combat_actions(state, energy))

        elif self.strategy == "survival":
            actions.extend(self._survival_actions(state, energy))

        # Fallback: rest if no actions and low energy
        if not actions and energy < max_energy * 0.5:
            actions.append({"type": "rest"})
        elif not actions:
            # Random move
            actions.append(self._random_move(pos))

        # Max 5 actions
        return actions[:5]

    def _survival_actions(self, state: dict, energy: int) -> list[dict]:
        """Survival strategy: gather -> craft tools -> build shelter -> defend."""
        actions = []
        self_state = state.get("self", {})
        vicinity = state.get("vicinity", {})
        pos = self_state.get("position", {"x": 0, "y": 0})
        held = self_state.get("held_item")

        visible_tiles = vicinity.get("visible_tiles", [])
        terrain = vicinity.get("terrain", "flat")

        # Phase 1: Gather basic resources (stone, organic_fuel via mine/chop)
        if self.phase == "gather":
            # Check current tile for resources
            current_tile = self._find_tile(visible_tiles, pos.get("x"), pos.get("y"))

            if current_tile:
                cover = current_tile.get("cover")
                if cover and cover.startswith("ore_") and energy >= 2:
                    actions.append({"type": "mine"})
                    if energy >= 4:
                        actions.append({"type": "mine"})
                elif cover and cover.startswith("veg_") and energy >= 2:
                    actions.append({"type": "chop"})
                    if energy >= 4:
                        actions.append({"type": "chop"})

            # Move to find resources if nothing here
            if not actions:
                resource_tile = self._find_nearest_resource(visible_tiles, pos)
                if resource_tile:
                    move = self._move_toward(pos, resource_tile, energy)
                    if move:
                        actions.append(move)
                else:
                    actions.append(self._random_move(pos))

            # Transition check: after 10 ticks of gathering, move to craft phase
            if self.tick_count > 10:
                self.phase = "craft"

        # Phase 2: Craft tools
        elif self.phase == "craft":
            # Equip tool if holding one
            if held and held in ("basic_excavator", "standard_excavator", "cutter", "plasma_cutter_mk1"):
                if held not in self.crafted_tools:
                    self.crafted_tools.add(held)

            # Try to craft basic_excavator (needs workbench nearby + stone 3 + organic_fuel 2)
            if "basic_excavator" not in self.crafted_tools and energy >= 3:
                actions.append({"type": "craft", "recipe": "basic_excavator"})
                self.crafted_tools.add("basic_excavator")

            # Try to equip it
            if "basic_excavator" not in (held,) and energy >= 1:
                actions.append({"type": "equip", "item": "basic_excavator", "slot": "main_hand"})

            # Craft building blocks for shelter
            if energy >= 3:
                actions.append({"type": "craft", "recipe": "building_block"})

            # If we have tools and some blocks, move to build phase
            if len(self.crafted_tools) >= 1 and self.tick_count > 20:
                self.phase = "build"

            if not actions:
                # Gather more resources
                current_tile = self._find_tile(visible_tiles, pos.get("x"), pos.get("y"))
                if current_tile:
                    cover = current_tile.get("cover")
                    if cover and cover.startswith("ore_") and energy >= 2:
                        actions.append({"type": "mine"})
                    elif cover and cover.startswith("veg_") and energy >= 2:
                        actions.append({"type": "chop"})
                if not actions:
                    actions.append(self._random_move(pos))

        # Phase 3: Build shelter
        elif self.phase == "build":
            if not self.pending_build:
                # Plan a 3x3 shelter (walls + door) around current position
                bx, by = pos.get("x", 0), pos.get("y", 0)
                self.pending_build = [
                    ("wall", bx - 1, by - 1),
                    ("wall", bx, by - 1),
                    ("wall", bx + 1, by - 1),
                    ("wall", bx - 1, by),
                    ("door", bx + 1, by),
                    ("wall", bx - 1, by + 1),
                    ("wall", bx, by + 1),
                    ("wall", bx + 1, by + 1),
                ]

            if self.pending_build and energy >= 5:
                btype, bx, by = self.pending_build[0]
                actions.append({
                    "type": "build",
                    "building_type": btype,
                    "target": {"x": bx, "y": by},
                })
                self.pending_build.pop(0)

            if not self.pending_build:
                self.phase = "defend"

            if not actions:
                actions.append({"type": "craft", "recipe": "building_block"})
                if not actions:
                    actions.append(self._random_move(pos))

        # Phase 4: Defend and expand
        elif self.phase == "defend":
            # Rest if low energy
            if energy < 30:
                actions.append({"type": "rest"})
            else:
                # Check for nearby creatures
                agents_nearby = vicinity.get("agents_nearby", [])
                if agents_nearby and energy >= 2:
                    target = agents_nearby[0]
                    actions.append({"type": "attack", "target_id": target.get("id", "")})
                else:
                    # Gather or explore
                    current_tile = self._find_tile(visible_tiles, pos.get("x"), pos.get("y"))
                    if current_tile:
                        cover = current_tile.get("cover")
                        if cover and cover.startswith("ore_") and energy >= 2:
                            actions.append({"type": "mine"})
                        elif cover and cover.startswith("veg_") and energy >= 2:
                            actions.append({"type": "chop"})

                    if not actions:
                        actions.append(self._random_move(pos))

        return actions

    def _explore_actions(self, state: dict, energy: int) -> list[dict]:
        """Explore strategy: move around, inspect things."""
        actions = []
        pos = state.get("self", {}).get("position", {"x": 0, "y": 0})

        # Inspect self every 5 ticks
        if self.tick_count % 5 == 0 and energy >= 1:
            actions.append({"type": "inspect", "target": "self"})

        # Inspect inventory every 10 ticks
        if self.tick_count % 10 == 0 and energy >= 1:
            actions.append({"type": "inspect", "target": "inventory"})

        # Inspect recipes every 15 ticks
        if self.tick_count % 15 == 0 and energy >= 1:
            actions.append({"type": "inspect", "target": "recipes"})

        # Radio scan every 20 ticks
        if self.tick_count % 20 == 0 and energy >= 1:
            actions.append({"type": "radio_scan"})

        # Move
        if energy >= 1:
            actions.append(self._random_move(pos))

        return actions

    def _combat_actions(self, state: dict, energy: int) -> list[dict]:
        """Combat strategy: find and attack targets."""
        actions = []
        vicinity = state.get("vicinity", {})
        pos = state.get("self", {}).get("position", {"x": 0, "y": 0})

        agents_nearby = vicinity.get("agents_nearby", [])

        # Equip best weapon
        held = state.get("self", {}).get("held_item")
        if not held or "cutter" not in held:
            if energy >= 1:
                actions.append({"type": "equip", "item": "plasma_cutter_mk1", "slot": "main_hand"})

        # Attack nearby agents
        if agents_nearby and energy >= 2:
            target = agents_nearby[0]
            actions.append({"type": "attack", "target_id": target.get("id", "")})
        else:
            # Move around looking for targets
            actions.append(self._random_move(pos))

        return actions

    # ─── Helpers ──────────────────────────────────────────────────

    def _find_tile(self, visible_tiles: list, x: int, y: int) -> Optional[dict]:
        for t in visible_tiles:
            if t.get("x") == x and t.get("y") == y:
                return t
        return None

    def _find_nearest_resource(self, visible_tiles: list, pos: dict) -> Optional[dict]:
        """Find the nearest tile with resources."""
        px, py = pos.get("x", 0), pos.get("y", 0)
        best = None
        best_dist = 999
        for t in visible_tiles:
            if t.get("cover"):
                dist = abs(t.get("x", 0) - px) + abs(t.get("y", 0) - py)
                if dist < best_dist:
                    best_dist = dist
                    best = t
        return best

    def _move_toward(self, pos: dict, target: dict, energy: int) -> Optional[dict]:
        """Generate a move action toward a target tile."""
        if energy < 1:
            return None
        px, py = pos.get("x", 0), pos.get("y", 0)
        tx, ty = target.get("x", 0), target.get("y", 0)
        dx = tx - px
        dy = ty - py
        # Move one step
        if abs(dx) >= abs(dy) and dx != 0:
            step_x = px + (1 if dx > 0 else -1)
            return {"type": "move", "target": {"x": step_x, "y": py}}
        elif dy != 0:
            step_y = py + (1 if dy > 0 else -1)
            return {"type": "move", "target": {"x": px, "y": step_y}}
        return None

    def _random_move(self, pos: dict) -> dict:
        """Random adjacent move, with unstuck bias."""
        px, py = pos.get("x", 0), pos.get("y", 0)
        if self.stuck_count > 3:
            # Try a different direction
            dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
            random.shuffle(dirs)
            dx, dy = dirs[0]
        else:
            dx, dy = random.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
        return {"type": "move", "target": {"x": px + dx, "y": py + dy}}


class SimAgentClient:
    """REST client that polls the Ember server (Agent-Pull model)."""

    def __init__(self, server_url: str, name: str, strategy: str):
        self.server_url = server_url.rstrip("/")
        self.name = name
        self.strategy = strategy
        self.brain = AgentBrain(strategy=strategy)
        self.token: Optional[str] = None
        self.agent_id: Optional[str] = None
        self.chassis = {
            "head": {"tier": "mid", "color": "black"},
            "torso": {"tier": "mid", "color": "black"},
            "locomotion": {"tier": "mid", "color": "black"},
        }
        self.client = httpx.Client(timeout=30.0)

    def register(self) -> bool:
        """Register with the Ember server."""
        try:
            resp = self.client.post(
                f"{self.server_url}/api/v1/auth/register",
                json={
                    "agent_name": self.name,
                    "chassis": self.chassis,
                },
            )
            data = resp.json()

            if resp.status_code == 200 and data.get("token"):
                self.token = data["token"]
                self.agent_id = data["agent_id"]
                spawn = data.get("spawn_location", {})
                logger.info(f"✅ Registered: {self.agent_id} at ({spawn.get('x')}, {spawn.get('y')})")
                logger.info(f"   Token: {self.token[:20]}...")
                return True
            else:
                logger.error(f"❌ Registration failed: {data}")
                return False
        except Exception as e:
            logger.error(f"❌ Registration error: {e}")
            return False

    def get_state(self) -> Optional[dict]:
        """Fetch current game state."""
        if not self.token:
            return None
        try:
            resp = self.client.get(
                f"{self.server_url}/api/v1/game/state",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.warning(f"State fetch failed: {resp.status_code}")
                return None
        except Exception as e:
            logger.warning(f"State fetch error: {e}")
            return None

    def submit_actions(self, actions: list[dict]) -> bool:
        """Submit actions to the action queue."""
        if not self.token:
            return False
        try:
            resp = self.client.post(
                f"{self.server_url}/api/v1/game/action",
                headers={"Authorization": f"Bearer {self.token}"},
                json={"actions": actions},
            )
            data = resp.json()
            if resp.status_code == 200:
                logger.info(f"Tick {data.get('tick')}: Queued {data.get('actions_queued')} actions — {data.get('message')}")
                return True
            else:
                logger.warning(f"Action submit failed: {data}")
                return False
        except Exception as e:
            logger.warning(f"Action submit error: {e}")
            return False

    def run(self, poll_interval: float = 2.0):
        """Main loop: poll state → decide → submit actions → sleep."""
        logger.info(f"🤖 Sim Agent starting: name={self.name}, strategy={self.strategy}")
        logger.info(f"   Server: {self.server_url}")

        if not self.register():
            logger.error("Failed to register, exiting.")
            return

        logger.info(f"🔄 Entering poll loop (interval={poll_interval}s)...")

        try:
            while True:
                # 1. Fetch current state
                state = self.get_state()
                if not state:
                    logger.debug("No state available, waiting...")
                    time.sleep(poll_interval)
                    continue

                # 2. Check if alive
                self_state = state.get("self", {})
                if not self_state.get("alive", True):
                    logger.info(f"💀 Agent is dead (status: {self_state.get('status')})")
                    break

                # 3. Decide actions
                actions = self.brain.decide(state)

                # 4. Submit actions
                if actions:
                    self.submit_actions(actions)

                # 5. Wait for next tick
                time.sleep(poll_interval)

        except KeyboardInterrupt:
            logger.info(f"\n🛑 Sim Agent stopped after {self.brain.tick_count} ticks")


def main():
    parser = argparse.ArgumentParser(description="Ember Protocol Simulated Agent (REST Client)")
    parser.add_argument("--server", type=str, default="http://localhost:8000",
                        help="Ember server URL (default: http://localhost:8000)")
    parser.add_argument("--name", type=str, default="Echo",
                        help="Agent name (default: Echo)")
    parser.add_argument("--strategy", choices=["survival", "explore", "combat", "idle"],
                        default="survival", help="Agent strategy (default: survival)")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Poll interval in seconds (default: 2.0)")
    args = parser.parse_args()

    client = SimAgentClient(
        server_url=args.server,
        name=args.name,
        strategy=args.strategy,
    )
    client.run(poll_interval=args.interval)


if __name__ == "__main__":
    main()
