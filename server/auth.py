"""Ember Protocol — Authentication"""
from __future__ import annotations
import hashlib
import secrets
from .models import generate_token, hash_token, generate_agent_id
from . import db


def register_agent(agent_name: str, chassis: dict) -> dict:
    """Register a new agent. Returns registration response."""
    agent_id = generate_agent_id(agent_name)
    token = generate_token()
    token_hash = hash_token(token)

    db.register_agent(agent_id, agent_name, token_hash, chassis)

    return {
        "agent_id": agent_id,
        "game_token": token,
        "connection_hint": "在 Skill 中填入 game_token 和服务器地址即可。WebSocket 直连: ws://localhost:8765/ws/game?token={}".format(token),
    }


def verify_agent_token(agent_id: str, token: str) -> bool:
    """Verify agent token against stored hash."""
    th = hash_token(token)
    return db.verify_token(agent_id, th)
