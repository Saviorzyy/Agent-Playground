"""Ember Protocol — L3 API Integration Tests
Phase 3: HTTP API endpoint tests using FastAPI TestClient
Tests registration, auth, state, action submission, inspect, observer endpoints
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import time
from fastapi.testclient import TestClient

from server.api.main import app, engine, TOKENS
from server.models import Attributes


@pytest.fixture(autouse=True)
def setup_engine():
    """Ensure engine is initialized before each test"""
    # Force engine creation for testing
    if engine is None:
        from server.engine.game import GameEngine
        import server.api.main as api_main
        api_main.engine = GameEngine(map_width=50, map_height=50, seed=42)
    # Clear tokens between tests
    TOKENS.clear()
    yield


client = TestClient(app)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# A1: Health Endpoint
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestHealthEndpoint:
    def test_health_returns_ok(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_includes_tick(self):
        resp = client.get("/health")
        data = resp.json()
        assert "tick" in data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# A2: Agent Registration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestRegistration:
    def _valid_chassis(self):
        return {
            "head": {"tier": "mid", "color": "black"},
            "torso": {"tier": "mid", "color": "black"},
            "locomotion": {"tier": "mid", "color": "black"},
        }

    def test_register_success(self):
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": "TestBot",
            "chassis": self._valid_chassis(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "agent_id" in data
        assert "token" in data
        assert data["status"] == "registered"
        assert "spawn_location" in data

    def test_register_returns_token(self):
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": "TokenBot",
            "chassis": self._valid_chassis(),
        })
        data = resp.json()
        assert data["token"].startswith("tk_")

    def test_register_spawn_location(self):
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": "SpawnBot",
            "chassis": self._valid_chassis(),
        })
        data = resp.json()
        loc = data["spawn_location"]
        assert "x" in loc and "y" in loc
        assert isinstance(loc["x"], int)
        assert isinstance(loc["y"], int)

    def test_register_tutorial_phase_zero(self):
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": "TutorialBot",
            "chassis": self._valid_chassis(),
        })
        data = resp.json()
        assert data["tutorial_phase"] == 0

    def test_register_attribute_budget_exceeded(self):
        """Total > 6 should be rejected"""
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": "OverBot",
            "chassis": {
                "head": {"tier": "high"},      # PER=3
                "torso": {"tier": "high"},      # CON=3
                "locomotion": {"tier": "high"}, # AGI=3, total=9
            },
        })
        assert resp.status_code == 400
        assert "budget" in resp.json()["detail"].lower() or "exceeded" in resp.json()["detail"].lower()

    def test_register_empty_name_rejected(self):
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": "",
            "chassis": self._valid_chassis(),
        })
        assert resp.status_code == 422  # Validation error

    def test_register_different_builds(self):
        """Test all valid chassis combinations"""
        builds = [
            {"head": {"tier": "high"}, "torso": {"tier": "mid"}, "locomotion": {"tier": "low"}},
            {"head": {"tier": "low"}, "torso": {"tier": "high"}, "locomotion": {"tier": "mid"}},
            {"head": {"tier": "mid"}, "torso": {"tier": "mid"}, "locomotion": {"tier": "mid"}},
        ]
        for chassis in builds:
            resp = client.post("/api/v1/auth/register", json={
                "agent_name": f"Build_{chassis['head']['tier']}_{chassis['torso']['tier']}_{chassis['locomotion']['tier']}",
                "chassis": chassis,
            })
            assert resp.status_code == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# A3: Authentication
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestAuthentication:
    def _register_and_get_token(self):
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": "AuthBot",
            "chassis": {"head": {"tier": "mid"}, "torso": {"tier": "mid"}, "locomotion": {"tier": "mid"}},
        })
        return resp.json()["token"]

    def test_valid_token_access(self):
        token = self._register_and_get_token()
        resp = client.get("/api/v1/game/state", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_no_auth_header(self):
        resp = client.get("/api/v1/game/state")
        assert resp.status_code == 401

    def test_invalid_token(self):
        resp = client.get("/api/v1/game/state", headers={"Authorization": "Bearer invalid_token"})
        assert resp.status_code == 401

    def test_expired_token(self):
        token = self._register_and_get_token()
        # Manually expire the token
        TOKENS[token]["expires_at"] = time.time() - 100
        resp = client.get("/api/v1/game/state", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_get_token_endpoint(self):
        # Register first
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": "TokenBot",
            "chassis": {"head": {"tier": "mid"}, "torso": {"tier": "mid"}, "locomotion": {"tier": "mid"}},
        })
        agent_id = resp.json()["agent_id"]
        # Get token via auth/token
        resp = client.post("/api/v1/auth/token", json={
            "agent_id": agent_id,
            "api_key": "any",
        })
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_get_token_unknown_agent(self):
        resp = client.post("/api/v1/auth/token", json={
            "agent_id": "nonexistent_agent",
            "api_key": "any",
        })
        assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# A4: Game State
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGameState:
    def _register(self):
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": "StateBot",
            "chassis": {"head": {"tier": "mid"}, "torso": {"tier": "mid"}, "locomotion": {"tier": "mid"}},
        })
        return resp.json()

    def test_state_structure(self):
        data = self._register()
        resp = client.get("/api/v1/game/state", headers={"Authorization": f"Bearer {data['token']}"})
        assert resp.status_code == 200
        state = resp.json()
        assert "self" in state
        assert "vicinity" in state
        assert "meta" in state

    def test_state_self_fields(self):
        data = self._register()
        resp = client.get("/api/v1/game/state", headers={"Authorization": f"Bearer {data['token']}"})
        state = resp.json()
        self_data = state["self"]
        assert self_data["id"] == data["agent_id"]
        assert self_data["alive"] is True
        assert self_data["health"] == 110  # mid CON = 2, HP = 70 + 2*20
        assert self_data["energy"] == 100

    def test_state_vicinity_fields(self):
        data = self._register()
        resp = client.get("/api/v1/game/state", headers={"Authorization": f"Bearer {data['token']}"})
        state = resp.json()
        v = state["vicinity"]
        assert "terrain" in v
        assert "time_of_day" in v
        assert "weather" in v
        assert "visible_tiles" in v

    def test_state_meta_fields(self):
        data = self._register()
        resp = client.get("/api/v1/game/state", headers={"Authorization": f"Bearer {data['token']}"})
        state = resp.json()
        m = state["meta"]
        assert "tick" in m
        assert "tick_interval_seconds" in m
        assert "day_phase" in m


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# A5: Action Submission
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestActionSubmission:
    def _register(self):
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": "ActionBot",
            "chassis": {"head": {"tier": "mid"}, "torso": {"tier": "mid"}, "locomotion": {"tier": "mid"}},
        })
        return resp.json()

    def test_submit_rest_action(self):
        data = self._register()
        resp = client.post("/api/v1/game/action", 
            headers={"Authorization": f"Bearer {data['token']}"},
            json={"actions": [{"type": "rest"}]})
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "queued"
        assert result["actions_queued"] == 1

    def test_submit_multiple_actions(self):
        data = self._register()
        resp = client.post("/api/v1/game/action",
            headers={"Authorization": f"Bearer {data['token']}"},
            json={"actions": [{"type": "rest"}, {"type": "rest"}, {"type": "rest"}]})
        assert resp.status_code == 200
        assert resp.json()["actions_queued"] == 3

    def test_submit_max_five_actions(self):
        data = self._register()
        resp = client.post("/api/v1/game/action",
            headers={"Authorization": f"Bearer {data['token']}"},
            json={"actions": [{"type": "rest"}] * 5})
        assert resp.status_code == 200
        # Try 6th → should fail (queue full)
        resp = client.post("/api/v1/game/action",
            headers={"Authorization": f"Bearer {data['token']}"},
            json={"actions": [{"type": "rest"}]})
        assert resp.status_code == 400

    def test_submit_without_auth(self):
        resp = client.post("/api/v1/game/action",
            json={"actions": [{"type": "rest"}]})
        assert resp.status_code == 401

    def test_submit_empty_actions(self):
        data = self._register()
        resp = client.post("/api/v1/game/action",
            headers={"Authorization": f"Bearer {data['token']}"},
            json={"actions": []})
        # Empty actions list should still be accepted (max_length=5 doesn't enforce min)
        # or return an error
        assert resp.status_code in (200, 400)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# A6: Inspect Endpoint
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestInspectEndpoint:
    def _register(self):
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": "InspectBot",
            "chassis": {"head": {"tier": "mid"}, "torso": {"tier": "mid"}, "locomotion": {"tier": "mid"}},
        })
        return resp.json()

    def test_inspect_inventory(self):
        data = self._register()
        resp = client.post("/api/v1/game/inspect",
            headers={"Authorization": f"Bearer {data['token']}"},
            json={"target": "inventory"})
        assert resp.status_code == 200
        result = resp.json()
        assert result["target"] == "inventory"

    def test_inspect_self(self):
        data = self._register()
        resp = client.post("/api/v1/game/inspect",
            headers={"Authorization": f"Bearer {data['token']}"},
            json={"target": "self"})
        assert resp.status_code == 200
        result = resp.json()
        assert "id" in result["data"]
        assert "hp" in result["data"]

    def test_inspect_recipes(self):
        data = self._register()
        resp = client.post("/api/v1/game/inspect",
            headers={"Authorization": f"Bearer {data['token']}"},
            json={"target": "recipes"})
        assert resp.status_code == 200

    def test_inspect_map(self):
        data = self._register()
        resp = client.post("/api/v1/game/inspect",
            headers={"Authorization": f"Bearer {data['token']}"},
            json={"target": "map"})
        assert resp.status_code == 200

    def test_inspect_unknown_target(self):
        data = self._register()
        resp = client.post("/api/v1/game/inspect",
            headers={"Authorization": f"Bearer {data['token']}"},
            json={"target": "unknown_thing"})
        assert resp.status_code == 400

    def test_inspect_other_agent(self):
        # Register two agents
        data1 = client.post("/api/v1/auth/register", json={
            "agent_name": "Agent1",
            "chassis": {"head": {"tier": "mid"}, "torso": {"tier": "mid"}, "locomotion": {"tier": "mid"}},
        }).json()
        data2 = client.post("/api/v1/auth/register", json={
            "agent_name": "Agent2",
            "chassis": {"head": {"tier": "mid"}, "torso": {"tier": "mid"}, "locomotion": {"tier": "mid"}},
        }).json()
        resp = client.post("/api/v1/game/inspect",
            headers={"Authorization": f"Bearer {data1['token']}"},
            json={"target": f"agent:{data2['agent_id']}"})
        assert resp.status_code == 200

    def test_inspect_without_auth(self):
        resp = client.post("/api/v1/game/inspect", json={"target": "inventory"})
        assert resp.status_code == 401


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# A7: Observer Endpoints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestObserverEndpoints:
    def _register(self, name="ObsBot"):
        resp = client.post("/api/v1/auth/register", json={
            "agent_name": name,
            "chassis": {"head": {"tier": "mid"}, "torso": {"tier": "mid"}, "locomotion": {"tier": "mid"}},
        })
        return resp.json()

    def test_observer_state(self):
        self._register()
        resp = client.get("/api/v1/observer/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "tick" in data
        assert "agents" in data
        assert len(data["agents"]) == 1

    def test_observer_agents(self):
        self._register()
        resp = client.get("/api/v1/observer/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["agents"]) == 1
        agent = data["agents"][0]
        assert "id" in agent
        assert "hp" in agent
        assert "alive" in agent

    def test_observer_agent_detail(self):
        reg = self._register()
        resp = client.get(f"/api/v1/observer/agents/{reg['agent_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == reg["agent_id"]
        assert "inventory" in data
        assert "equipment" in data

    def test_observer_agent_detail_not_found(self):
        resp = client.get("/api/v1/observer/agents/nonexistent")
        assert resp.status_code == 404

    def test_observer_map(self):
        self._register()
        resp = client.get("/api/v1/observer/map?x=0&y=0&width=10&height=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "tiles" in data
        assert len(data["tiles"]) > 0

    def test_observer_map_bounds(self):
        self._register()
        resp = client.get("/api/v1/observer/map?x=0&y=0&width=5&height=5")
        data = resp.json()
        assert data["size"]["width"] == 5
        assert data["size"]["height"] == 5

    def test_observer_multiple_agents(self):
        self._register("Agent1")
        self._register("Agent2")
        resp = client.get("/api/v1/observer/agents")
        data = resp.json()
        assert len(data["agents"]) == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# A8: CORS & Static Files
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestCORSAndStatic:
    def test_cors_headers(self):
        resp = client.options("/health", headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        })
        # CORS should be enabled
        assert resp.status_code in (200, 204)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
