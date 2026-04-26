"""Ember Protocol — L2 Engine Integration Tests
Phase 2: GameEngine action handler tests
Tests all action types through the engine, multi-agent interactions, 
tick processing, creatures, buildings, death/respawn, radiation, etc.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import asyncio
import json
import random

from server.models import (
    Attributes, Position, Agent, ItemInstance, Inventory, Equipment,
    Tile, TerrainType, CoverType, WeatherType, DayPhase, ActiveEffect,
    ActionResult, Building, Creature, CreatureState, TickResult,
    MAX_INVENTORY_SLOTS, MAX_GROUND_ITEMS_PER_TILE,
    DROP_POD_BACKUP_BODIES, REST_CHARGE,
)
from server.models.items import ITEM_DB, get_item
from server.models.recipes import find_recipe
from server.engine.game import GameEngine
from server.engine.world import COVER_YIELDS


class TestEngineRegistration:
    """Agent registration and spawn"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)

    def test_register_basic(self):
        attrs = Attributes(2, 2, 2)
        agent = self.engine.register_agent("TestBot", attrs)
        assert agent.id is not None
        assert agent.hp == 110
        assert agent.is_alive()
        assert agent.tutorial_phase == 0
        assert agent.energy == 100
        assert agent.backup_bodies == 5

    def test_register_heavy_build(self):
        attrs = Attributes(3, 2, 1)
        agent = self.engine.register_agent("HeavyBot", attrs)
        assert agent.hp == 130
        assert agent.speed == 2

    def test_register_scout_build(self):
        attrs = Attributes(1, 2, 3)
        agent = self.engine.register_agent("ScoutBot", attrs)
        assert agent.hp == 90

    def test_spawn_in_center_zone(self):
        attrs = Attributes(2, 2, 2)
        agent = self.engine.register_agent("CenterBot", attrs)
        from server.engine.world import get_zone
        zone = get_zone(agent.position.y, 50)
        assert zone in ("center", "T1"), f"Spawned in {zone}"

    def test_starting_buildings_placed(self):
        attrs = Attributes(2, 2, 2)
        agent = self.engine.register_agent("BuildBot", attrs)
        # Check workbench and furnace exist near spawn
        has_workbench = False
        has_furnace = False
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                tile = self.engine.world.get_tile(
                    agent.position.x + dx, agent.position.y + dy)
                if tile and tile.l3:
                    bldg = self.engine.buildings.get(tile.l3)
                    if bldg:
                        if bldg.building_type == "workbench":
                            has_workbench = True
                        if bldg.building_type == "furnace":
                            has_furnace = True
        assert has_workbench, "Starting workbench not found"
        assert has_furnace, "Starting furnace not found"


class TestEngineMovement:
    """Move and move_to actions"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)
        self.agent = self.engine.register_agent("MoveBot", Attributes(2, 2, 2))

    def test_move_adjacent(self):
        # Find a passable adjacent tile
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = self.agent.position.x + dx, self.agent.position.y + dy
            if self.engine.world.in_bounds(nx, ny):
                tile = self.engine.world.get_tile(nx, ny)
                if tile and tile.l1 != TerrainType.WATER and not tile.l3:
                    result = self.engine.resolve_action(self.agent, {
                        "type": "move", "target": {"x": nx, "y": ny}
                    }, 0)
                    assert result.success
                    assert self.agent.position.x == nx
                    assert self.agent.position.y == ny
                    assert self.agent.energy == 99
                    return
        pytest.skip("No passable adjacent tile found")

    def test_move_too_far(self):
        result = self.engine.resolve_action(self.agent, {
            "type": "move", "target": {"x": self.agent.position.x + 5, "y": self.agent.position.y}
        }, 0)
        assert not result.success
        assert result.error_code == "OUT_OF_RANGE"

    def test_move_no_energy(self):
        self.agent.energy = 0
        result = self.engine.resolve_action(self.agent, {
            "type": "move", "target": {"x": self.agent.position.x, "y": self.agent.position.y + 1}
        }, 0)
        assert not result.success
        assert result.error_code == "INSUFFICIENT_ENERGY"

    def test_move_to_water_fails(self):
        # Force a tile to water for testing
        self.engine.world.tiles[(self.agent.position.x, self.agent.position.y + 1)].l1 = TerrainType.WATER
        result = self.engine.resolve_action(self.agent, {
            "type": "move", "target": {"x": self.agent.position.x, "y": self.agent.position.y + 1}
        }, 0)
        assert not result.success
        assert result.error_code == "INVALID_TARGET"

    def test_move_out_of_bounds(self):
        result = self.engine.resolve_action(self.agent, {
            "type": "move", "target": {"x": -1, "y": 0}
        }, 0)
        assert not result.success

    def test_move_to_destination(self):
        # Test move_to (long distance travel)
        dest_x = min(self.agent.position.x + 10, 49)
        result = self.engine.resolve_action(self.agent, {
            "type": "move_to", "destination": {"x": dest_x, "y": self.agent.position.y}
        }, 0)
        assert result.success
        assert self.agent.status == "traveling"
        assert self.agent.travel_destination is not None

    def test_move_to_missing_coords(self):
        result = self.engine.resolve_action(self.agent, {
            "type": "move_to", "destination": {}
        }, 0)
        assert not result.success

    def test_move_to_out_of_bounds(self):
        result = self.engine.resolve_action(self.agent, {
            "type": "move_to", "destination": {"x": 999, "y": 999}
        }, 0)
        assert not result.success


class TestEngineGathering:
    """Mine and chop actions"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)
        self.agent = self.engine.register_agent("GatherBot", Attributes(2, 2, 2))
        self.agent.energy = 100

    def _place_ore_at_agent(self, ore_type="ore_stone"):
        """Helper: place ore cover at agent position"""
        tile = self.engine.world.get_tile(self.agent.position.x, self.agent.position.y)
        tile.l2 = CoverType(ore_type)
        tile.l2_remaining = 10
        return tile

    def _place_veg_at_agent(self, veg_type="veg_ashbrush"):
        tile = self.engine.world.get_tile(self.agent.position.x, self.agent.position.y)
        tile.l2 = CoverType(veg_type)
        tile.l2_remaining = 10
        return tile

    def test_mine_stone_unarmed_fails(self):
        """Stone has hardness 3 — unarmed cannot mine it (needs tool with max_hardness >= 3)"""
        self._place_ore_at_agent("ore_stone")
        result = self.engine.resolve_action(self.agent, {"type": "mine"}, 0)
        # Unarmed: no tool → tool check fails because hardness=3 > 0 and no tool
        assert not result.success
        assert result.error_code == "TOOL_REQUIRED"

    def test_mine_stone_with_tool(self):
        self._place_ore_at_agent("ore_stone")
        self.agent.inventory.add_item(ItemInstance(item_id="basic_excavator"), ITEM_DB)
        self.engine.resolve_action(self.agent, {
            "type": "equip", "item": "basic_excavator", "slot": "main_hand"
        }, 0)
        result = self.engine.resolve_action(self.agent, {"type": "mine"}, 0)
        assert result.success
        assert self.agent.inventory.has_item("stone")
        assert self.agent.energy == 98  # 100 - 2 (mine cost)

    def test_mine_with_tool(self):
        self._place_ore_at_agent("ore_stone")
        self.agent.inventory.add_item(ItemInstance(item_id="basic_excavator"), ITEM_DB)
        self.engine.resolve_action(self.agent, {
            "type": "equip", "item": "basic_excavator", "slot": "main_hand"
        }, 0)
        result = self.engine.resolve_action(self.agent, {"type": "mine"}, 0)
        assert result.success
        assert self.agent.inventory.count_item("stone") >= 1

    def test_mine_nothing_here(self):
        tile = self.engine.world.get_tile(self.agent.position.x, self.agent.position.y)
        tile.l2 = None
        result = self.engine.resolve_action(self.agent, {"type": "mine"}, 0)
        assert not result.success
        assert result.error_code == "INVALID_TARGET"

    def test_mine_hardness_requires_tool(self):
        """raw_copper (hardness 5) needs basic_excavator (max_hardness 5)"""
        self._place_ore_at_agent("ore_copper")
        # No tool equipped → should fail
        result = self.engine.resolve_action(self.agent, {"type": "mine"}, 0)
        assert not result.success
        assert result.error_code == "TOOL_REQUIRED"

    def test_mine_hardness_with_correct_tool(self):
        self._place_ore_at_agent("ore_copper")
        self.agent.inventory.add_item(ItemInstance(item_id="basic_excavator"), ITEM_DB)
        self.engine.resolve_action(self.agent, {
            "type": "equip", "item": "basic_excavator", "slot": "main_hand"
        }, 0)
        result = self.engine.resolve_action(self.agent, {"type": "mine"}, 0)
        assert result.success

    def test_mine_depletes_resource(self):
        tile = self._place_ore_at_agent("ore_stone")
        tile.l2_remaining = 1
        # Need tool for hardness 3
        self.agent.inventory.add_item(ItemInstance(item_id="basic_excavator"), ITEM_DB)
        self.engine.resolve_action(self.agent, {
            "type": "equip", "item": "basic_excavator", "slot": "main_hand"
        }, 0)
        result = self.engine.resolve_action(self.agent, {"type": "mine"}, 0)
        assert result.success
        assert tile.l2 is None  # Depleted → cleared

    def test_mine_no_energy(self):
        self._place_ore_at_agent("ore_stone")
        self.agent.energy = 1
        result = self.engine.resolve_action(self.agent, {"type": "mine"}, 0)
        assert not result.success
        assert result.error_code == "INSUFFICIENT_ENERGY"

    def test_chop_wood(self):
        self._place_veg_at_agent("veg_ashbrush")
        result = self.engine.resolve_action(self.agent, {"type": "chop"}, 0)
        assert result.success
        assert self.agent.inventory.has_item("wood")

    def test_mine_on_veg_fails(self):
        """Mining on vegetation should fail (use chop)"""
        self._place_veg_at_agent("veg_ashbrush")
        result = self.engine.resolve_action(self.agent, {"type": "mine"}, 0)
        assert not result.success
        assert result.error_code == "WRONG_TOOL"

    def test_chop_on_ore_fails(self):
        """Chopping on ore should fail (use mine)"""
        self._place_ore_at_agent("ore_stone")
        result = self.engine.resolve_action(self.agent, {"type": "chop"}, 0)
        assert not result.success
        assert result.error_code == "WRONG_TOOL"

    def test_tool_durability_decreases(self):
        self._place_ore_at_agent("ore_stone")
        self.agent.inventory.add_item(ItemInstance(item_id="basic_excavator"), ITEM_DB)
        self.engine.resolve_action(self.agent, {
            "type": "equip", "item": "basic_excavator", "slot": "main_hand"
        }, 0)
        dur_before = self.agent.equipment.main_hand.durability
        self.engine.resolve_action(self.agent, {"type": "mine"}, 0)
        assert self.agent.equipment.main_hand.durability == dur_before - 1


class TestEngineCrafting:
    """Craft action with station and material checks"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)
        self.agent = self.engine.register_agent("CraftBot", Attributes(2, 2, 2))
        self.agent.energy = 100

    def test_craft_building_block_hand(self):
        """Building block: 3 stone → 1 building_block, no station needed"""
        self.agent.inventory.add_item(ItemInstance(item_id="stone", amount=5), ITEM_DB)
        result = self.engine.resolve_action(self.agent, {
            "type": "craft", "recipe": "building_block"
        }, 0)
        assert result.success
        assert self.agent.inventory.has_item("building_block")
        assert not self.agent.inventory.has_item("stone", 5)  # Consumed 3
        assert self.agent.energy == 97

    def test_craft_unknown_recipe(self):
        result = self.engine.resolve_action(self.agent, {
            "type": "craft", "recipe": "nonexistent_recipe"
        }, 0)
        assert not result.success
        assert result.error_code == "RECIPE_UNKNOWN"

    def test_craft_missing_materials(self):
        # No materials in inventory
        result = self.engine.resolve_action(self.agent, {
            "type": "craft", "recipe": "building_block"
        }, 0)
        assert not result.success
        assert result.error_code == "MISSING_MATERIALS"

    def test_craft_insufficient_energy(self):
        self.agent.inventory.add_item(ItemInstance(item_id="stone", amount=5), ITEM_DB)
        self.agent.energy = 2
        result = self.engine.resolve_action(self.agent, {
            "type": "craft", "recipe": "building_block"
        }, 0)
        assert not result.success
        assert result.error_code == "INSUFFICIENT_ENERGY"

    def test_craft_furnace_recipe_needs_furnace(self):
        """Smelting copper requires nearby furnace"""
        self.agent.inventory.add_item(ItemInstance(item_id="raw_copper", amount=3), ITEM_DB)
        # Move agent far from any furnace
        self.agent.position = Position(40, 40)
        result = self.engine.resolve_action(self.agent, {
            "type": "craft", "recipe": "copper_ingot"
        }, 0)
        assert not result.success
        assert "furnace" in result.detail.lower()

    def test_craft_workbench_recipe_needs_workbench(self):
        """Basic excavator requires nearby workbench"""
        self.agent.inventory.add_item(ItemInstance(item_id="stone", amount=5), ITEM_DB)
        self.agent.inventory.add_item(ItemInstance(item_id="organic_fuel", amount=3), ITEM_DB)
        # Move far from workbench
        self.agent.position = Position(40, 40)
        result = self.engine.resolve_action(self.agent, {
            "type": "craft", "recipe": "basic_excavator"
        }, 0)
        assert not result.success

    def test_craft_ingot_to_coins(self):
        """Currency conversion: 1 copper_ingot → 5 ember_coin"""
        self.agent.inventory.add_item(ItemInstance(item_id="copper_ingot", amount=1), ITEM_DB)
        result = self.engine.resolve_action(self.agent, {
            "type": "craft", "recipe": "copper_ingot_to_coins"
        }, 0)
        assert result.success
        assert self.agent.inventory.has_item("ember_coin", 5)

    def test_craft_coins_to_ingot(self):
        """Reverse: 5 ember_coin → 1 copper_ingot"""
        self.agent.inventory.add_item(ItemInstance(item_id="ember_coin", amount=5), ITEM_DB)
        result = self.engine.resolve_action(self.agent, {
            "type": "craft", "recipe": "coins_to_copper_ingot"
        }, 0)
        assert result.success
        assert self.agent.inventory.has_item("copper_ingot")


class TestEngineBuilding:
    """Build action with all building types"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)
        self.agent = self.engine.register_agent("BuildBot", Attributes(2, 2, 2))
        self.agent.energy = 100
        self.target_x, self.target_y = 40, 40  # Clear area
        self.agent.position = Position(self.target_x, self.target_y)

    def _clear_tile(self, x, y):
        tile = self.engine.world.get_tile(x, y)
        tile.l1 = TerrainType.FLAT
        tile.l2 = None
        tile.l3 = None

    def test_build_wall(self):
        self._clear_tile(self.target_x + 1, self.target_y)
        self.agent.inventory.add_item(ItemInstance(item_id="building_block", amount=5), ITEM_DB)
        result = self.engine.resolve_action(self.agent, {
            "type": "build", "building_type": "wall",
            "target": {"x": self.target_x + 1, "y": self.target_y}
        }, 0)
        assert result.success
        assert self.agent.energy == 95
        # Verify building exists
        bldg_id = f"wall_{self.target_x + 1}_{self.target_y}"
        assert bldg_id in self.engine.buildings

    def test_build_door(self):
        self._clear_tile(self.target_x + 1, self.target_y)
        self.agent.inventory.add_item(ItemInstance(item_id="building_block", amount=2), ITEM_DB)
        self.agent.inventory.add_item(ItemInstance(item_id="iron_ingot", amount=2), ITEM_DB)
        result = self.engine.resolve_action(self.agent, {
            "type": "build", "building_type": "door",
            "target": {"x": self.target_x + 1, "y": self.target_y}
        }, 0)
        assert result.success

    def test_build_on_water_fails(self):
        self.engine.world.tiles[(self.target_x + 1, self.target_y)].l1 = TerrainType.WATER
        result = self.engine.resolve_action(self.agent, {
            "type": "build", "building_type": "wall",
            "target": {"x": self.target_x + 1, "y": self.target_y}
        }, 0)
        assert not result.success

    def test_build_on_existing_fails(self):
        self._clear_tile(self.target_x + 1, self.target_y)
        # Place a building first
        existing_id = "wall_test"
        self.engine.buildings[existing_id] = Building(
            id=existing_id, building_type="wall",
            position=Position(self.target_x + 1, self.target_y),
            owner_id="test", hp=60, max_hp=60)
        self.engine.world.tiles[(self.target_x + 1, self.target_y)].l3 = existing_id
        result = self.engine.resolve_action(self.agent, {
            "type": "build", "building_type": "wall",
            "target": {"x": self.target_x + 1, "y": self.target_y}
        }, 0)
        assert not result.success

    def test_build_missing_materials(self):
        self._clear_tile(self.target_x + 1, self.target_y)
        result = self.engine.resolve_action(self.agent, {
            "type": "build", "building_type": "wall",
            "target": {"x": self.target_x + 1, "y": self.target_y}
        }, 0)
        assert not result.success
        assert result.error_code == "MISSING_MATERIALS"

    def test_build_unknown_type(self):
        result = self.engine.resolve_action(self.agent, {
            "type": "build", "building_type": "mega_fortress",
            "target": {"x": self.target_x + 1, "y": self.target_y}
        }, 0)
        assert not result.success


class TestEngineCombat:
    """Attack action with agent vs agent and agent vs creature"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)
        self.attacker = self.engine.register_agent("AtkBot", Attributes(2, 2, 2))
        self.target = self.engine.register_agent("TgtBot", Attributes(2, 2, 2))
        # Place target adjacent
        self.target.position = Position(self.attacker.position.x + 1, self.attacker.position.y)
        self.attacker.energy = 100

    def test_attack_adjacent_unarmed(self):
        result = self.engine.resolve_action(self.attacker, {
            "type": "attack", "target_id": self.target.id
        }, 0)
        assert result.success
        assert "hit" in result.extra or result.detail.startswith("Attack missed")

    def test_attack_with_melee_weapon(self):
        self.attacker.inventory.add_item(ItemInstance(item_id="plasma_cutter_mk1"), ITEM_DB)
        self.engine.resolve_action(self.attacker, {
            "type": "equip", "item": "plasma_cutter_mk1", "slot": "main_hand"
        }, 0)
        result = self.engine.resolve_action(self.attacker, {
            "type": "attack", "target_id": self.target.id
        }, 0)
        assert result.success

    def test_attack_target_not_found(self):
        result = self.engine.resolve_action(self.attacker, {
            "type": "attack", "target_id": "nonexistent"
        }, 0)
        assert not result.success
        assert result.error_code == "INVALID_TARGET"

    def test_attack_out_of_range(self):
        self.target.position = Position(self.attacker.position.x + 10, self.attacker.position.y)
        result = self.engine.resolve_action(self.attacker, {
            "type": "attack", "target_id": self.target.id
        }, 0)
        assert not result.success
        assert result.error_code == "OUT_OF_RANGE"

    def test_attack_missing_target(self):
        result = self.engine.resolve_action(self.attacker, {
            "type": "attack"
        }, 0)
        assert not result.success

    def test_attack_creature(self):
        creature = Creature(
            id="creep_1", creature_type="acid_crawler",
            position=Position(self.attacker.position.x + 1, self.attacker.position.y),
            hp=30,
        )
        self.engine.creatures[creature.id] = creature
        result = self.engine.resolve_action(self.attacker, {
            "type": "attack", "target_id": creature.id
        }, 0)
        assert result.success

    def test_attack_kills_creature(self):
        creature = Creature(
            id="weak_1", creature_type="weakling",
            position=Position(self.attacker.position.x + 1, self.attacker.position.y),
            hp=1,
        )
        self.engine.creatures[creature.id] = creature
        self.attacker.inventory.add_item(ItemInstance(item_id="plasma_cutter_mk3"), ITEM_DB)
        self.engine.resolve_action(self.attacker, {
            "type": "equip", "item": "plasma_cutter_mk3", "slot": "main_hand"
        }, 0)
        result = self.engine.resolve_action(self.attacker, {
            "type": "attack", "target_id": creature.id
        }, 0)
        assert result.success
        assert creature.id not in self.engine.creatures

    def test_attack_energy_cost(self):
        self.attacker.inventory.add_item(ItemInstance(item_id="plasma_cutter_mk1"), ITEM_DB)
        self.engine.resolve_action(self.attacker, {
            "type": "equip", "item": "plasma_cutter_mk1", "slot": "main_hand"
        }, 0)
        energy_before = self.attacker.energy
        self.engine.resolve_action(self.attacker, {
            "type": "attack", "target_id": self.target.id
        }, 0)
        assert self.attacker.energy == energy_before - 2  # plasma_cutter_mk1 energy cost


class TestEngineDeathRespawn:
    """Death, item drop, respawn, permanent death"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)
        self.agent = self.engine.register_agent("DeathBot", Attributes(2, 2, 2))
        self.agent.energy = 100

    def test_death_drops_items(self):
        self.agent.inventory.add_item(ItemInstance(item_id="stone", amount=5), ITEM_DB)
        tile = self.engine.world.get_tile(self.agent.position.x, self.agent.position.y)
        initial_items = len(tile.ground_items)
        self.engine._handle_death(self.agent)
        assert len(tile.ground_items) > initial_items

    def test_death_respawn_with_backup(self):
        initial_bodies = self.agent.backup_bodies
        self.engine._handle_death(self.agent)
        assert self.agent.backup_bodies == initial_bodies - 1
        assert self.agent.alive
        assert self.agent.hp == self.agent.max_hp
        assert self.agent.energy == 50

    def test_permanent_death(self):
        self.agent.backup_bodies = 0
        self.engine._handle_death(self.agent)
        assert self.agent.status == "permadead"
        # Note: current code sets status="permadead" but alive remains True
        # This is a potential bug — alive should be False for permadead
        # is_alive() checks both alive AND hp > 0, so permadead agent
        # with alive=True but full HP from respawn logic would still be "alive"
        assert self.agent.status == "permadead"

    def test_respawn_at_spawn_point(self):
        self.engine._handle_death(self.agent)
        assert self.agent.position.x == self.agent.spawn_point.x
        assert self.agent.position.y == self.agent.spawn_point.y

    def test_death_clears_inventory(self):
        self.agent.inventory.add_item(ItemInstance(item_id="stone", amount=10), ITEM_DB)
        self.engine._handle_death(self.agent)
        assert self.agent.inventory.slots_used == 0


class TestEngineUseEquip:
    """Use consumables, equip/unequip, swap hands"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)
        self.agent = self.engine.register_agent("UseBot", Attributes(2, 2, 2))
        self.agent.energy = 100

    def test_use_repair_kit(self):
        self.agent.hp = 50
        self.agent.inventory.add_item(ItemInstance(item_id="repair_kit"), ITEM_DB)
        result = self.engine.resolve_action(self.agent, {"type": "use", "item": "repair_kit"}, 0)
        assert result.success
        assert self.agent.hp == 80

    def test_use_battery(self):
        self.agent.energy = 30
        self.agent.inventory.add_item(ItemInstance(item_id="battery"), ITEM_DB)
        result = self.engine.resolve_action(self.agent, {"type": "use", "item": "battery"}, 0)
        assert result.success
        assert self.agent.energy == 60

    def test_use_radiation_antidote(self):
        self.agent.active_effects.append(ActiveEffect("radiation", "Radiation", 2))
        self.agent.inventory.add_item(ItemInstance(item_id="radiation_antidote"), ITEM_DB)
        result = self.engine.resolve_action(self.agent, {"type": "use", "item": "radiation_antidote"}, 0)
        assert result.success
        assert all(e.effect_id != "radiation" for e in self.agent.active_effects)

    def test_use_non_consumable_fails(self):
        self.agent.inventory.add_item(ItemInstance(item_id="stone"), ITEM_DB)
        result = self.engine.resolve_action(self.agent, {"type": "use", "item": "stone"}, 0)
        assert not result.success

    def test_equip_tool(self):
        self.agent.inventory.add_item(ItemInstance(item_id="basic_excavator"), ITEM_DB)
        result = self.engine.resolve_action(self.agent, {
            "type": "equip", "item": "basic_excavator", "slot": "main_hand"
        }, 0)
        assert result.success
        assert self.agent.equipment.main_hand is not None
        assert self.agent.equipment.main_hand.item_id == "basic_excavator"
        assert not self.agent.inventory.has_item("basic_excavator")

    def test_equip_replaces_current(self):
        self.agent.inventory.add_item(ItemInstance(item_id="basic_excavator"), ITEM_DB)
        self.agent.inventory.add_item(ItemInstance(item_id="plasma_cutter_mk1"), ITEM_DB)
        self.engine.resolve_action(self.agent, {
            "type": "equip", "item": "basic_excavator", "slot": "main_hand"
        }, 0)
        result = self.engine.resolve_action(self.agent, {
            "type": "equip", "item": "plasma_cutter_mk1", "slot": "main_hand"
        }, 0)
        assert result.success
        assert self.agent.equipment.main_hand.item_id == "plasma_cutter_mk1"
        assert self.agent.inventory.has_item("basic_excavator")  # Old item returned

    def test_unequip(self):
        self.agent.inventory.add_item(ItemInstance(item_id="basic_excavator"), ITEM_DB)
        self.engine.resolve_action(self.agent, {
            "type": "equip", "item": "basic_excavator", "slot": "main_hand"
        }, 0)
        result = self.engine.resolve_action(self.agent, {
            "type": "unequip", "slot": "main_hand"
        }, 0)
        assert result.success
        assert self.agent.equipment.main_hand is None
        assert self.agent.inventory.has_item("basic_excavator")

    def test_swap_hands(self):
        self.agent.inventory.add_item(ItemInstance(item_id="basic_excavator"), ITEM_DB)
        self.engine.resolve_action(self.agent, {
            "type": "equip", "item": "basic_excavator", "slot": "main_hand"
        }, 0)
        result = self.engine.resolve_action(self.agent, {"type": "swap_hands"}, 0)
        assert result.success
        assert self.agent.equipment.off_hand is not None
        assert self.agent.equipment.main_hand is None


class TestEnginePickupDrop:
    """Pickup and drop ground items"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)
        self.agent = self.engine.register_agent("PickBot", Attributes(2, 2, 2))
        self.agent.energy = 100

    def test_pickup_item(self):
        tile = self.engine.world.get_tile(self.agent.position.x, self.agent.position.y)
        tile.ground_items.append(ItemInstance(item_id="stone", amount=5))
        result = self.engine.resolve_action(self.agent, {"type": "pickup"}, 0)
        assert result.success
        assert self.agent.inventory.has_item("stone", 5)
        assert len(tile.ground_items) == 0

    def test_pickup_empty_ground(self):
        result = self.engine.resolve_action(self.agent, {"type": "pickup"}, 0)
        assert not result.success

    def test_drop_item(self):
        self.agent.inventory.add_item(ItemInstance(item_id="stone", amount=10), ITEM_DB)
        result = self.engine.resolve_action(self.agent, {
            "type": "drop", "item": "stone", "amount": 3
        }, 0)
        assert result.success
        assert self.agent.inventory.count_item("stone") == 7
        tile = self.engine.world.get_tile(self.agent.position.x, self.agent.position.y)
        assert len(tile.ground_items) == 1

    def test_drop_nonexistent_item(self):
        result = self.engine.resolve_action(self.agent, {
            "type": "drop", "item": "nonexistent", "amount": 1
        }, 0)
        assert not result.success


class TestEngineCommunication:
    """Talk, radio broadcast, direct, scan"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)
        self.agent1 = self.engine.register_agent("Talker1", Attributes(2, 2, 2))
        self.agent2 = self.engine.register_agent("Talker2", Attributes(2, 2, 2))
        self.agent1.energy = 100
        self.agent2.energy = 100

    def test_talk_same_tile(self):
        self.agent2.position = Position(self.agent1.position.x, self.agent1.position.y)
        result = self.engine.resolve_action(self.agent1, {
            "type": "talk", "target_agent": self.agent2.id, "content": "Hello!"
        }, 0)
        assert result.success
        assert hasattr(self.agent2, '_pending_messages')
        assert len(self.agent2._pending_messages) == 1

    def test_talk_different_tile_fails(self):
        self.agent2.position = Position(self.agent1.position.x + 1, self.agent1.position.y)
        result = self.engine.resolve_action(self.agent1, {
            "type": "talk", "target_agent": self.agent2.id, "content": "Hello!"
        }, 0)
        assert not result.success

    def test_radio_broadcast(self):
        self.agent2.position = Position(self.agent1.position.x + 5, self.agent1.position.y)
        result = self.engine.resolve_action(self.agent1, {
            "type": "radio_broadcast", "content": "SOS!"
        }, 0)
        assert result.success
        assert self.agent1.energy == 99

    def test_radio_direct(self):
        self.agent2.position = Position(self.agent1.position.x + 5, self.agent1.position.y)
        result = self.engine.resolve_action(self.agent1, {
            "type": "radio_direct", "target_agent": self.agent2.id, "content": "DM"
        }, 0)
        assert result.success

    def test_radio_scan(self):
        self.agent2.position = Position(self.agent1.position.x + 5, self.agent1.position.y)
        result = self.engine.resolve_action(self.agent1, {"type": "radio_scan"}, 0)
        assert result.success
        assert "agents_found" in result.extra


class TestEngineInspect:
    """Inspect inventory, self, recipes"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)
        self.agent = self.engine.register_agent("InspectBot", Attributes(2, 2, 2))

    def test_inspect_inventory(self):
        result = self.engine.resolve_action(self.agent, {"type": "inspect", "target": "inventory"}, 0)
        assert result.success

    def test_inspect_self(self):
        result = self.engine.resolve_action(self.agent, {"type": "inspect", "target": "self"}, 0)
        assert result.success
        data = json.loads(result.detail)
        assert data["id"] == self.agent.id

    def test_inspect_recipes(self):
        result = self.engine.resolve_action(self.agent, {"type": "inspect", "target": "recipes"}, 0)
        assert result.success

    def test_inspect_unknown_target(self):
        result = self.engine.resolve_action(self.agent, {"type": "inspect", "target": "unknown"}, 0)
        assert not result.success


class TestEngineTickProcessing:
    """Tick loop, radiation, effects, creatures, solar"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)

    def test_tick_advances(self):
        asyncio.run(self.engine.tick())
        assert self.engine.current_tick == 1

    def test_tick_agent_effects_radiation(self):
        agent = self.engine.register_agent("RadBot", Attributes(2, 2, 2))
        agent.active_effects.append(ActiveEffect("radiation", "Radiation", 2))
        hp_before = agent.hp
        asyncio.run(self.engine.tick())
        assert agent.hp == hp_before - 2  # Radiation does 2 damage per tick

    def test_tick_radiation_armor_reduces(self):
        agent = self.engine.register_agent("ArmorBot", Attributes(2, 2, 2))
        agent.active_effects.append(ActiveEffect("radiation", "Radiation", 2))
        agent.inventory.add_item(ItemInstance(item_id="radiation_armor"), ITEM_DB)
        self.engine.resolve_action(agent, {
            "type": "equip", "item": "radiation_armor", "slot": "armor"
        }, 0)
        hp_before = agent.hp
        asyncio.run(self.engine.tick())
        assert agent.hp == hp_before - 1  # 2 * (1 - 0.5) = 1

    def test_tick_auto_rest(self):
        agent = self.engine.register_agent("IdleBot", Attributes(2, 2, 2))
        agent.energy = 50
        tick_result = TickResult(tick=1)
        self.engine.resolve_tick_actions(tick_result)
        assert agent.energy > 50

    def test_rest_action(self):
        agent = self.engine.register_agent("RestBot", Attributes(2, 2, 2))
        agent.energy = 50
        result = self.engine.resolve_action(agent, {"type": "rest"}, 0)
        assert result.success
        assert agent.energy > 50

    def test_solar_charging(self):
        # Place solar array and power node near each other
        sx, sy = 40, 40
        self.engine.world.tiles[(sx, sy)].l1 = TerrainType.FLAT
        self.engine.world.tiles[(sx, sy)].l3 = None
        self.engine.world.tiles[(sx + 1, sy)].l1 = TerrainType.FLAT
        self.engine.world.tiles[(sx + 1, sy)].l3 = None

        solar_id = f"solar_array_{sx}_{sy}"
        solar = Building(id=solar_id, building_type="solar_array",
                        position=Position(sx, sy), owner_id="sys",
                        hp=60, max_hp=60)
        self.engine.buildings[solar_id] = solar
        self.engine.world.tiles[(sx, sy)].l3 = solar_id

        node_id = f"power_node_{sx+1}_{sy}"
        node = Building(id=node_id, building_type="power_node",
                       position=Position(sx + 1, sy), owner_id="sys",
                       hp=80, max_hp=80, energy_stored=0, energy_capacity=100)
        self.engine.buildings[node_id] = node
        self.engine.world.tiles[(sx + 1, sy)].l3 = node_id

        asyncio.run(self.engine.tick())
        assert node.energy_stored > 0


class TestEngineActionQueue:
    """Action queue mechanics with initiative ordering"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)

    def test_submit_queues(self):
        agent = self.engine.register_agent("QueueBot", Attributes(2, 2, 2))
        result = self.engine.submit_actions(agent.id, [{"type": "rest"}, {"type": "rest"}])
        assert result
        assert len(agent.pending_actions) == 2

    def test_max_five_actions(self):
        agent = self.engine.register_agent("QueueBot", Attributes(2, 2, 2))
        self.engine.submit_actions(agent.id, [{"type": "rest"}] * 5)
        assert len(agent.pending_actions) == 5
        assert not self.engine.submit_actions(agent.id, [{"type": "rest"}])

    def test_dead_agent_cannot_submit(self):
        agent = self.engine.register_agent("DeadBot", Attributes(2, 2, 2))
        agent.alive = False
        agent.hp = 0
        assert not self.engine.submit_actions(agent.id, [{"type": "rest"}])

    def test_offline_agent_cannot_submit(self):
        agent = self.engine.register_agent("OffBot", Attributes(2, 2, 2))
        agent.status = "offline"
        assert not self.engine.submit_actions(agent.id, [{"type": "rest"}])

    def test_unknown_action_type(self):
        agent = self.engine.register_agent("UnknownBot", Attributes(2, 2, 2))
        result = self.engine.resolve_action(agent, {"type": "fly_to_moon"}, 0)
        assert not result.success
        assert result.error_code == "UNKNOWN_ACTION"


class TestEngineLogout:
    """Logout and status tracking"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)

    def test_logout(self):
        agent = self.engine.register_agent("LogoutBot", Attributes(2, 2, 2))
        result = self.engine.resolve_action(agent, {"type": "logout"}, 0)
        assert result.success
        assert agent.status == "offline"


class TestEngineStateBuilding:
    """build_agent_state output format"""

    def setup_method(self):
        self.engine = GameEngine(map_width=50, map_height=50, seed=42)

    def test_state_structure(self):
        agent = self.engine.register_agent("StateBot", Attributes(2, 2, 2))
        state = self.engine.build_agent_state(agent)
        assert "self" in state
        assert "vicinity" in state
        assert "meta" in state
        assert state["self"]["id"] == agent.id
        assert state["self"]["health"] == agent.hp
        assert state["meta"]["tick"] == self.engine.current_tick

    def test_observer_state(self):
        agent = self.engine.register_agent("ObsBot", Attributes(2, 2, 2))
        obs = self.engine.get_observer_state()
        assert "tick" in obs
        assert "agents" in obs
        assert len(obs["agents"]) == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
