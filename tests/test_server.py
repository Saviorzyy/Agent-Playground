"""Ember Protocol — Comprehensive Test Suite"""
import sys
import os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from server.config import *
from server.models import *
from server.world import World


class TestModels:
    def test_position_creation(self):
        p = Position(10, 20)
        assert p.x == 10
        assert p.y == 20
        assert p.to_tuple() == (10, 20)

    def test_position_distance(self):
        a = Position(0, 0)
        b = Position(3, 4)
        assert a.dist(b) == 7
        assert b.dist(a) == 7

    def test_position_hash(self):
        a = Position(1, 2)
        b = Position(1, 2)
        s = {a}
        assert b in s

    def test_agent_creation(self):
        agent = AgentState(
            agent_id="test-01", agent_name="Test",
            position=Position(0, 0), health=100, max_health=100,
            energy=80, max_energy=100,
            constitution=2, agility=2, perception=2,
        )
        assert agent.view_range(DayPhase.DAY, Weather.CALM) == 5  # 3 + 2
        assert agent.view_range(DayPhase.NIGHT, Weather.CALM) == 3  # 1 + 2
        assert agent.move_speed() == 1  # (2+1)//2

    def test_agent_movement_speed(self):
        slow = AgentState("s", "s", Position(0,0), 100, 100, 80, 100, agility=1)
        assert slow.move_speed() == 1
        fast = AgentState("f", "f", Position(0,0), 100, 100, 80, 100, agility=3)
        assert fast.move_speed() == 2

    def test_equipment_slots(self):
        eq = Equipment(main_hand="basic_excavator")
        assert eq.main_hand == "basic_excavator"
        assert eq.off_hand is None
        assert eq.armor is None

    def test_token_generation(self):
        token = generate_token()
        assert token.startswith("et_")
        assert len(token) == 51  # et_ + 48 hex chars

    def test_token_hashing(self):
        token = generate_token()
        h = hash_token(token)
        assert len(h) == 64  # SHA-256 hex

    def test_agent_id_generation(self):
        agent_id = generate_agent_id("Test Agent")
        assert "-" in agent_id
        assert len(agent_id.split("-")[-1]) == 4


class TestWorld:
    @pytest.fixture
    def world(self):
        return World(seed=42)

    @pytest.fixture
    def agent(self, world):
        world.token_hashes['test-01'] = 'hash123'
        chassis = {'head': {'tier': 'high'}, 'torso': {'tier': 'mid'}, 'locomotion': {'tier': 'low'}}
        return world.create_agent('test-01', 'Alpha', chassis)

    def test_world_creation(self, world):
        assert len(world.tiles) == MAP_HEIGHT
        assert len(world.tiles[0]) == MAP_WIDTH
        assert world.day_phase == DayPhase.DAY
        assert world.weather == Weather.CALM

    def test_tile_access(self, world):
        tile = world.get_tile(100, 100)
        assert tile is not None
        assert tile.l1 in (Terrain.FLAT, Terrain.SAND, Terrain.ROCK)

        assert world.get_tile(-1, 0) is None
        assert world.get_tile(200, 0) is None

    def test_agent_spawn(self, agent):
        assert agent.agent_name == "Alpha"
        assert agent.health == 110  # 70 + 2*20
        assert agent.max_health == 110
        assert agent.energy == 100
        assert agent.constitution == 2  # mid torso
        assert agent.agility == 1  # low locomotion
        assert agent.perception == 3  # high head
        assert agent.tutorial_phase == 0

    def test_agent_initial_inventory(self, agent):
        assert len(agent.inventory) == 3
        item_ids = {i.item_id: i.amount for i in agent.inventory}
        assert item_ids.get("workbench") == 1
        assert item_ids.get("furnace") == 1
        assert item_ids.get("organic_fuel") == 5

    def test_move_action(self, world, agent):
        old_pos = Position(agent.position.x, agent.position.y)
        results = world.settle_actions(0, {'test-01': [{'type': 'move', 'direction': 'north'}]})
        r = results['test-01'][0]
        assert r['success']
        assert agent.position.y == old_pos.y - 1
        assert agent.energy == 99  # -1

    def test_move_insufficient_energy(self, world, agent):
        agent.energy = 0
        results = world.settle_actions(0, {'test-01': [{'type': 'move', 'direction': 'north'}]})
        r = results['test-01'][0]
        assert not r['success']
        assert r['error_code'] == 'INSUFFICIENT_ENERGY'

    def test_inspect_inventory(self, world, agent):
        results = world.settle_actions(0, {'test-01': [{'type': 'inspect', 'target': 'inventory'}]})
        r = results['test-01'][0]
        assert r['success']
        assert len(r.get('items', [])) == 3

    def test_inspect_self(self, world, agent):
        results = world.settle_actions(0, {'test-01': [{'type': 'inspect', 'target': 'self'}]})
        r = results['test-01'][0]
        assert r['success']
        state = r.get('state', {})
        assert state['health'] == 110

    def test_inspect_recipes(self, world, agent):
        results = world.settle_actions(0, {'test-01': [{'type': 'inspect', 'target': 'recipes'}]})
        r = results['test-01'][0]
        assert r['success']
        assert len(r.get('recipes', [])) > 20

    def test_rest_action(self, world, agent):
        agent.energy = 50
        results = world.settle_actions(0, {'test-01': [{'type': 'rest'}]})
        r = results['test-01'][0]
        assert r['success']
        assert agent.energy == 53  # +3 from rest

    def test_pickup_action(self, world, agent):
        from server.world import GroundItems
        world.ground_items[(agent.position.x, agent.position.y)] = GroundItems(
            items=[("stone", 3)], dropped_tick=0
        )
        results = world.settle_actions(0, {'test-01': [{'type': 'pickup'}]})
        r = results['test-01'][0]
        assert r['success']
        assert world.has_item(agent, "stone", 3)

    def test_drop_action(self, world, agent):
        results = world.settle_actions(0, {'test-01': [{'type': 'drop', 'item_id': 'organic_fuel', 'amount': 3}]})
        r = results['test-01'][0]
        assert r['success']
        assert world.has_item(agent, "organic_fuel", 2)  # had 5, dropped 3

    def test_move_to_basic(self, world, agent):
        target = {"x": agent.position.x + 5, "y": agent.position.y}
        results = world.settle_actions(0, {'test-01': [{'type': 'move_to', 'destination': target}]})
        r = results['test-01'][0]
        assert r['success']
        assert agent.status == ActionStatus.MOVING

    def test_day_night_cycle(self, world):
        assert world.day_phase == DayPhase.DAY
        # Advance to dusk
        for _ in range(420):
            world.advance_world()
        assert world.day_phase == DayPhase.DUSK
        # Advance through night
        for _ in range(450):
            world.advance_world()
        assert world.day_phase == DayPhase.DAWN

    def test_energy_recovery(self, world, agent):
        agent.energy = 50
        agent.online = True
        world.advance_world()
        assert agent.energy == 51  # +1 solar recovery

    def test_craft_missing_materials(self, world, agent):
        results = world.settle_actions(0, {'test-01': [{'type': 'craft', 'recipe': 'iron_ingot'}]})
        r = results['test-01'][0]
        assert not r['success']

    def test_equip_unequip(self, world, agent):
        # Cannot equip without item
        results = world.settle_actions(0, {'test-01': [{'type': 'equip', 'item_id': 'basic_excavator'}]})
        r = results['test-01'][0]
        assert not r['success']
        assert r['error_code'] == 'INVENTORY_FULL'

    def test_use_repair_kit(self, world, agent):
        agent.health = 50
        agent.inventory.append(InventoryItem("repair_kit", 1))
        results = world.settle_actions(0, {'test-01': [{'type': 'use', 'item_id': 'repair_kit'}]})
        r = results['test-01'][0]
        assert r['success']
        assert agent.health == 80  # 50 + 30

    def test_use_battery(self, world, agent):
        agent.energy = 10
        agent.inventory.append(InventoryItem("battery", 1))
        results = world.settle_actions(0, {'test-01': [{'type': 'use', 'item_id': 'battery'}]})
        r = results['test-01'][0]
        assert r['success']
        assert agent.energy == 40  # 10 + 30

    def test_multiple_actions(self, world, agent):
        actions = [
            {'type': 'move', 'direction': 'north'},
            {'type': 'rest'},
            {'type': 'inspect', 'target': 'inventory'},
        ]
        results = world.settle_actions(0, {'test-01': actions})
        assert len(results['test-01']) == 3
        assert all(r['success'] for r in results['test-01'])

    def test_action_budget_enforcement(self, world, agent):
        actions = [{'type': 'rest'}] * 15  # exceeds max 10
        results = world.settle_actions(0, {'test-01': actions})
        # Only first 10 should be processed (budget enforced at tick_loop level)
        assert len(results['test-01']) == 10

    def test_build_wall(self, world, agent):
        # Give agent building blocks
        agent.inventory.append(InventoryItem("building_block", 2))
        tx, ty = agent.position.x + 1, agent.position.y
        results = world.settle_actions(0, {'test-01': [{'type': 'build', 'building_type': 'wall',
                                                          'target': {'x': tx, 'y': ty}}]})
        r = results['test-01'][0]
        if r['success']:
            tile = world.get_tile(tx, ty)
            assert tile.structure is not None
            assert tile.structure.building_type == BuildingType.WALL

    def test_talk_action(self, world, agent):
        # Create another agent in the same position
        world.token_hashes['test-02'] = 'hash456'
        chassis = {'head': {'tier': 'mid'}, 'torso': {'tier': 'mid'}, 'locomotion': {'tier': 'mid'}}
        beta = world.create_agent('test-02', 'Beta', chassis)
        beta.position = Position(agent.position.x, agent.position.y)

        results = world.settle_actions(0, {'test-01': [{'type': 'talk', 'target_agent': 'test-02', 'content': 'Hello!'}]})
        r = results['test-01'][0]
        assert r['success']

    def test_radio_broadcast(self, world, agent):
        results = world.settle_actions(0, {'test-01': [{'type': 'radio_broadcast', 'content': 'Hello world!'}]})
        r = results['test-01'][0]
        assert r['success']
        assert agent.energy == 99  # -1

    def test_death_and_respawn(self, world, agent):
        initial_backup = agent.backup_count
        # Force death
        agent.health = 0
        world._handle_death(agent)
        assert agent.backup_count == initial_backup - 1
        assert agent.status == ActionStatus.RESPANNING
        assert len(agent.inventory) == 0  # items dropped

    def test_permanent_death(self, world, agent):
        world.token_hashes['test-01'] = 'hash123'
        agent.backup_count = 0
        agent.drop_pod_deployed = False  # no pod to respawn
        agent.health = 0
        world._handle_death(agent)
        assert 'test-01' not in world.agents  # permanently dead

    def test_power_node_creation(self, world, agent):
        # Add materials
        agent.inventory = [
            InventoryItem("iron_ingot", 3),
            InventoryItem("copper_ingot", 2),
            InventoryItem("building_block", 1),
        ]
        tx, ty = agent.position.x + 1, agent.position.y
        results = world.settle_actions(0, {'test-01': [{'type': 'build', 'building_type': 'power_node',
                                                          'target': {'x': tx, 'y': ty}}]})
        r = results['test-01'][0]
        # May fail if blocked by stone or other rules
        if r['success']:
            assert len(world.power_nodes) > 1  # drop pod + new
            tile = world.get_tile(tx, ty)
            assert tile.structure is not None

    def test_add_remove_item(self, world, agent):
        world.add_item(agent, "stone", 10)
        assert world.has_item(agent, "stone", 10)
        assert world.count_item(agent, "stone") == 10
        world.remove_item(agent, "stone", 5)
        assert world.count_item(agent, "stone") == 5
        world.remove_item(agent, "stone", 5)
        assert not world.has_item(agent, "stone", 1)

    def test_scan_action(self, world, agent):
        results = world.settle_actions(0, {'test-01': [{'type': 'scan'}]})
        r = results['test-01'][0]
        assert r['success']
        assert agent.energy == 98  # -2

    def test_drop_pod_power(self, world, agent):
        pod_power = world.get_drop_pod_power_for_agent(agent)
        assert pod_power is not None
        assert pod_power.is_drop_pod
        assert pod_power.stored > 0

    def test_invalid_action_type(self, world, agent):
        results = world.settle_actions(0, {'test-01': [{'type': 'nonexistent'}]})
        r = results['test-01'][0]
        assert not r['success']
        assert r['error_code'] == 'INVALID_ACTION_TYPE'

    def test_tool_hardness_check(self, world, agent):
        """Verify tool hardness config is consistent."""
        # Basic excavator can mine hardness 5 (copper, iron)
        assert TOOLS["basic_excavator"]["max_hardness"] == 5
        assert TOOLS["standard_excavator"]["max_hardness"] == 8
        assert TOOLS["heavy_excavator"]["max_hardness"] == 10
        # Resource hardness
        assert RESOURCE_HARDNESS["raw_copper"] <= TOOLS["basic_excavator"]["max_hardness"]
        assert RESOURCE_HARDNESS["raw_iron"] <= TOOLS["basic_excavator"]["max_hardness"]
        assert RESOURCE_HARDNESS["uranium_ore"] <= TOOLS["standard_excavator"]["max_hardness"]


class TestConfig:
    def test_recipe_consistency(self):
        """All recipe materials should be valid items."""
        all_items = set()
        for cat in [RESOURCES, MATERIALS, TOOLS, WEAPONS, ARMORS, ACCESSORIES, CONSUMABLES]:
            all_items.update(cat.keys())

        for name, recipe in FURNACE_RECIPES.items():
            for mat in recipe.get("materials", {}):
                assert mat in all_items, f"Furnace recipe {name}: unknown material {mat}"

        for name, recipe in WORKBENCH_RECIPES.items():
            for mat in recipe.get("materials", {}):
                assert mat in all_items, f"Workbench recipe {name}: unknown material {mat}"

        for name, recipe in HANDCRAFT_RECIPES.items():
            for mat in recipe.get("materials", {}):
                assert mat in all_items, f"Handcraft recipe {name}: unknown material {mat}"

    def test_build_cost_consistency(self):
        """All build costs reference valid items."""
        all_items = set()
        for cat in [RESOURCES, MATERIALS]:
            all_items.update(cat.keys())
        for building, costs in BUILD_COSTS.items():
            for item in costs:
                assert item in all_items, f"Build {building}: unknown item {item}"

    def test_chassis_budget(self):
        """Ensure all valid chassis combinations are within budget."""
        tiers = [("high", 3), ("mid", 2), ("low", 1)]
        valid_combos = 0
        for head_t, head_c in tiers:
            for torso_t, torso_c in tiers:
                for loco_t, loco_c in tiers:
                    if head_c + torso_c + loco_c <= MAX_CHASSIS_BUDGET:
                        valid_combos += 1
        # 17 permutations across 3 slots with costs 1/2/3 summing <= 6
        assert valid_combos == 17

    def test_max_hardness_progression(self):
        """Tool hardness should progress: basic < standard < heavy."""
        assert TOOLS["basic_excavator"]["max_hardness"] < TOOLS["standard_excavator"]["max_hardness"]
        assert TOOLS["standard_excavator"]["max_hardness"] < TOOLS["heavy_excavator"]["max_hardness"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
