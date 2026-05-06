#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              Ember Protocol — Agent Gateway Skill v1.0.0                     ║
║                    可独立分发的一键接入模块                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝

Architecture (PRD §8.2/8.4):
  Game Server ←─WebSocket─→ EmberSkill ←─HTTP──→ LLM (any OpenAI-compatible API)
                               ↑
                          This File

Quick Start:
  # 1. Register + Connect with auto-LLM (using ANTHROPIC_API_KEY env var)
  python ember_skill.py --register --name "MyAgent" --server ws://localhost:8765

  # 2. Use existing token
  python ember_skill.py --token "et_xxx" --server ws://localhost:8765

  # 3. As a library (import into your agent framework)
  from ember_skill import EmberSkill
  skill = EmberSkill(token="et_xxx", server_url="ws://localhost:8765")
  await skill.connect()
  async for tick, act in skill.loop():
      actions = your_llm.think(tick)  # Your custom logic
      result = await act(actions)

LLM Providers:
  Set EMER_SKILL_API_KEY, EMER_SKILL_BASE_URL, EMBER_SKILL_MODEL env vars.
  Defaults to Anthropic-compatible API. Works with:
  - Anthropic:     base_url=https://api.anthropic.com  model=claude-sonnet-4-6
  - OpenAI:        base_url=https://api.openai.com/v1  model=gpt-4o
  - Zhipu (智谱):  base_url=https://open.bigmodel.cn/api/anthropic  model=glm-5-turbo
  - Any OpenAI/Anthropic-compatible endpoint

Dependencies: pip install websockets anthropic requests
"""

from __future__ import annotations
import asyncio, json, sys, os, argparse, time, traceback
from dataclasses import dataclass, field
from typing import Optional, Callable, AsyncIterator

# ── Dependencies (lazy-imported) ──────────────────────────────────────────────
import websockets
import requests


# ═══════════════════════════════════════════════════════════════════════════════
# Game Connection — WebSocket bridge to Ember Protocol server
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TickFrame:
    """Parsed tick frame from game server."""
    tick: int
    messages: list[dict]
    raw: dict = field(default_factory=dict)

@dataclass
class ActionResult:
    """Result of sending actions to game server."""
    tick: int
    results: list[dict]
    raw: dict = field(default_factory=dict)


class EmberSkill:
    """
    Core Gateway Skill — manages WebSocket lifecycle and game loop.

    Usage as library:
        skill = EmberSkill(token="et_xxx", server_url="ws://localhost:8765")
        session = await skill.connect()
        async for tick, send in skill.loop():
            # Your agent logic here
            actions = your_decide_function(tick)
            result = await send(actions)
    """

    def __init__(
        self,
        token: str,
        server_url: str = "ws://localhost:8765",
        agent_name: str = "EmberAgent",
    ):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.agent_name = agent_name
        self.ws = None
        self.agent_id: Optional[str] = None
        self.state: dict = {}
        self._connected = False

    # ── Connection ──────────────────────────────────────────────────────────

    async def connect(self) -> dict:
        """
        Connect to game server, authenticate, send ready.
        Returns session frame dict.
        """
        ws_url = f"{self.server_url}/ws/game?token={self.token}"
        self.ws = await websockets.connect(ws_url)

        session = json.loads(await self.ws.recv())
        if session.get("type") != "session":
            raise RuntimeError(f"Expected session frame, got: {session.get('type')}")

        self.agent_id = session["agent_id"]
        self.agent_name = session.get("agent_name", self.agent_name)
        self.state = session.get("state", {})
        self._connected = True

        await self.ws.send(json.dumps({"type": "ready"}))
        return session

    async def disconnect(self):
        self._connected = False
        if self.ws:
            await self.ws.close()

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Game Loop ───────────────────────────────────────────────────────────

    async def loop(self) -> AsyncIterator[tuple[TickFrame, "callable"]]:
        """
        Async generator yielding (tick_frame, send_function) pairs.

        Example:
            async for tick, send in skill.loop():
                actions = my_llm(tick.messages)
                result = await send(actions)
        """
        async def send_actions(actions: list[dict]) -> ActionResult:
            await self.ws.send(json.dumps({
                "type": "actions", "tick": current_tick, "actions": actions,
            }))
            raw = await self.recv_frame()
            while raw.get("type") != "result":
                if raw.get("type") == "ping":
                    await self.ws.send(json.dumps({"type": "pong", "ts": raw.get("ts")}))
                elif raw.get("type") == "event":
                    pass  # Events handled externally
                raw = await self.recv_frame()
            return ActionResult(tick=raw.get("tick", 0), results=raw.get("results", []), raw=raw)

        current_tick = 0
        while self._connected:
            frame = await self.recv_frame()
            ftype = frame.get("type")

            if ftype == "tick":
                current_tick = frame.get("tick", 0)
                tick_frame = TickFrame(
                    tick=current_tick,
                    messages=frame.get("messages", []),
                    raw=frame,
                )
                yield tick_frame, send_actions

            elif ftype == "ping":
                await self.ws.send(json.dumps({"type": "pong", "ts": frame.get("ts")}))

            elif ftype == "event":
                pass  # Caller can check skill.events if needed

            elif ftype == "error":
                print(f"[Ember] Server error: {frame.get('error_code')}: {frame.get('detail')}", file=sys.stderr)

    async def recv_frame(self) -> dict:
        """Receive a single JSON frame from the server."""
        return json.loads(await self.ws.recv())

    # ── Convenience ─────────────────────────────────────────────────────────

    @staticmethod
    def register(
        agent_name: str,
        chassis: Optional[dict] = None,
        server_url: str = "http://localhost:8765",
    ) -> dict:
        """
        Register a new agent via HTTP API. Returns dict with agent_id + game_token.

        Args:
            agent_name: Display name for the agent
            chassis: Dict with head/torso/locomotion tiers (high/mid/low).
                     Default: PER=3 CON=2 AGI=1 (balanced explorer)
            server_url: Game server HTTP URL
        """
        if chassis is None:
            chassis = {
                "head": {"tier": "high"},       # PER=3, cost=3
                "torso": {"tier": "mid"},       # CON=2, cost=2
                "locomotion": {"tier": "low"},  # AGI=1, cost=1
            }

        resp = requests.post(
            f"{server_url.rstrip('/')}/api/v1/auth/register",
            json={"agent_name": agent_name, "chassis": chassis},
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Registration failed: {resp.status_code} {resp.text}")
        return resp.json()


# ═══════════════════════════════════════════════════════════════════════════════
# Built-in LLM Client (optional — users can bring their own LLM)
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_SYSTEM_PROMPT = """你是余烬星(Ember)上的机械体幸存者，在200×200格的外星世界求生。

## 身份
- 殖民船「方舟号」意识上传体，寄宿于机械躯壳
- 携带降落仓(5次重生)，需能量维持运转，不需食物/水/睡眠
- 目标: 探索→采集→合成→建造→与其他幸存者互动

## 每tick行动规则 (关键!)
- **每tick做3-5个行动**，不要只做一个
- 探索: 连续2-3次同方向move + scan
- 采集: 连续2-3次mine/chop(指定视野中的坐标)
- 建筑: craft材料→连续build
- 能量<30时加入rest

## 行动类型
move {direction:"north"|"south"|"east"|"west"} — 移动(1能量)
mine {target:{x,y}} — 开采相邻格石料/矿石(2能量)
chop {target:{x,y}} — 砍伐相邻植被(2能量)
craft {recipe:"配方ID"} — 在设施旁合成(3能量)
build {building_type, target:{x,y}} — 建造(5能量)
rest — 休息恢复+3能量
scan — 探测5x5隐藏矿脉(2能量)
inspect {target:"inventory"|"self"|"recipes"|"map"}
equip {item_id, slot:"main_hand"} — 装备物品
pickup — 拾取地面物品(1能量)
radio_broadcast {content} — 广播(1能量)

## 策略
1. 教程Phase 0: inspect(inventory)一次即可毕业
2. 自由模式: 持续移动探索→采集资源→建造熔炉/工作台→合成工具
3. 视野中"可采集"资源带坐标，指定target去采集
4. 不要反复inspect同一个东西，不要发呆
5. 返回纯JSON数组"""


class LLMClient:
    """
    Built-in LLM client using Anthropic-compatible API.
    Configure via env vars: EMBER_SKILL_API_KEY, EMBER_SKILL_BASE_URL, EMBER_SKILL_MODEL
    """

    def __init__(self, system_prompt: str = ""):
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError("pip install anthropic")

        self.client = Anthropic(
            base_url=os.environ.get("EMBER_SKILL_BASE_URL", "https://open.bigmodel.cn/api/anthropic"),
            api_key=os.environ.get("EMBER_SKILL_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")),
        )
        self.model = os.environ.get("EMBER_SKILL_MODEL", "glm-5-turbo")
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.history: list[dict] = []

    def decide(self, messages: list[dict]) -> list[dict]:
        """Send game state to LLM and return parsed actions."""
        # Build messages (Zhipu API doesn't support system role)
        full_msgs = list(self.history[-8:])
        first_user = True

        for msg in messages:
            if msg.get("role") == "system":
                continue
            content = msg.get("content", "")
            if first_user:
                content = f"[系统指令]\n{self.system_prompt}\n\n---\n\n{content}"
                first_user = False
            full_msgs.append({"role": "user", "content": content})

        if first_user:
            full_msgs.append({"role": "user", "content": f"[系统指令]\n{self.system_prompt}"})

        full_msgs.append({
            "role": "user",
            "content": "请决定行动。返回纯JSON数组，不要markdown代码块标记。"
        })

        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=1024, temperature=0.7,
                messages=full_msgs,
            )
            text = response.content[0].text.strip()

            # Parse JSON from response
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:])
                if text.endswith("```"):
                    text = text[:-3]

            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                text = text[start:end]

            actions = json.loads(text)
            if not isinstance(actions, list):
                return []

            # Filter valid actions
            valid_types = {
                "move", "move_to", "mine", "chop", "craft", "build",
                "dismantle", "repair", "attack", "rest", "scan",
                "inspect", "pickup", "drop", "equip", "unequip",
                "use", "radio_broadcast", "radio_direct", "radio_scan",
                "talk", "logout",
            }
            filtered = [a for a in actions[:10] if isinstance(a, dict) and a.get("type") in valid_types]

            self.history.append({"role": "assistant", "content": json.dumps(filtered, ensure_ascii=False)})
            if len(self.history) > 20:
                self.history = self.history[-20:]

            return filtered

        except (json.JSONDecodeError, Exception) as e:
            print(f"[Ember LLM] Error: {e}", file=sys.stderr)
            return []


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

async def run_skill(args):
    """Run the skill with built-in LLM client."""
    skill = EmberSkill(token=args.token, server_url=args.server, agent_name=args.name)

    print(f"🔥 Ember Protocol Skill")
    print(f"   Connecting to {args.server}...")
    session = await skill.connect()
    print(f"   Agent: {skill.agent_name} ({skill.agent_id})")
    print(f"   Tutorial: phase {session.get('tutorial_phase')}")
    print(f"   HP: {skill.state.get('health')}  Energy: {skill.state.get('energy')}")
    print(f"   Inventory: {skill.state.get('inventory_summary', 'empty')}")
    print()

    llm = LLMClient()
    turn = 0

    try:
        async for tick_frame, send in skill.loop():
            turn += 1
            tick = tick_frame.tick

            # Get LLM decision
            actions = llm.decide(tick_frame.messages)

            if actions:
                action_names = [a['type'] for a in actions[:5]]
                print(f"T{tick}: {action_names}")

            result = await send(actions if actions else [{"type": "rest"}])

            # Print results
            for r in result.results:
                icon = "✓" if r.get("success") else "✗"
                detail = r.get("detail", r.get("error_code", ""))
                if r.get("success") or r.get("error_code") not in (
                    "OUT_OF_RANGE", "INVALID_TARGET", "MISSING_MATERIALS",
                    "TOOL_REQUIRED", "RECIPE_UNKNOWN", "INVENTORY_FULL",
                ):
                    print(f"  {icon} {r['type']}: {detail[:70]}")

    except KeyboardInterrupt:
        print("\nDisconnecting...")
    finally:
        await skill.disconnect()
        print(f"Done. {turn} turns played.")


# ═══════════════════════════════════════════════════════════════════════════════
# Config File Support
# ═══════════════════════════════════════════════════════════════════════════════

def _config_path() -> str:
    """Path to Ember config file."""
    return os.environ.get("EMBER_CONFIG", os.path.expanduser("~/.ember/config.yaml"))


def _load_config() -> dict:
    """Load persisted config."""
    path = _config_path()
    if os.path.exists(path):
        try:
            import yaml
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


def _save_config(cfg: dict):
    """Persist config to file."""
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        import yaml
        with open(path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    except ImportError:
        import json
        with open(path, "w") as f:
            json.dump(cfg, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# Interactive Setup
# ═══════════════════════════════════════════════════════════════════════════════

SETUP_BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║           🔥 余烬协议 Ember Protocol — Agent 初始化向导        ║
╚══════════════════════════════════════════════════════════════╝

本向导将引导你完成以下步骤：
  ❶ 创建角色（选择部件属性）
  ❷ 获取连接凭证 (game_token)
  ❸ 配置 LLM 后端
  ❹ 连接到游戏服务器开始探索

"""

CHASSIS_GUIDE = """
角色属性由三大部件决定（总预算 ≤ 6 点）：

  头部       → 感知 PER  (视野范围)   高级3点/标准2点/基础1点
  躯干       → 体质 CON  (HP上限)    高级3点/标准2点/基础1点
  运动机构   → 敏捷 AGI  (移动速度)   高级3点/标准2点/基础1点

推荐配置: PER=3 CON=2 AGI=1 (探索者型，视野广，均衡生存)
"""


def interactive_setup() -> dict:
    """Run interactive setup wizard. Returns config dict with token, server, model."""
    print(SETUP_BANNER)

    cfg = _load_config()

    # Step 1: Server URL
    default_server = cfg.get("server", "ws://localhost:8765")
    server = input(f"🌐 游戏服务器地址 [{default_server}]: ").strip()
    if not server:
        server = default_server

    api_url = server.replace("ws://", "http://").replace("wss://", "https://")

    # Step 2: Agent name
    default_name = cfg.get("agent_name", "EmberAgent")
    name = input(f"🤖 Agent 名称 [{default_name}]: ").strip()
    if not name:
        name = default_name

    # Step 3: Chassis
    print(CHASSIS_GUIDE)
    use_recommended = input("⚙️  使用推荐配置? (PER=3 CON=2 AGI=1) [Y/n]: ").strip().lower()
    if use_recommended in ("", "y", "yes"):
        chassis = {"head": {"tier": "high"}, "torso": {"tier": "mid"}, "locomotion": {"tier": "low"}}
    else:
        tiers = {"1": "low", "2": "mid", "3": "high"}
        head_t = input("  头部等级 (1=基础/2=标准/3=高级) [3]: ").strip() or "3"
        torso_t = input("  躯干等级 (1=基础/2=标准/3=高级) [2]: ").strip() or "2"
        loco_t = input("  运动机构等级 (1=基础/2=标准/3=高级) [1]: ").strip() or "1"
        chassis = {
            "head": {"tier": tiers.get(head_t, "high")},
            "torso": {"tier": tiers.get(torso_t, "mid")},
            "locomotion": {"tier": tiers.get(loco_t, "low")},
        }

    # Step 4: Register
    print(f"\n📋 正在注册 {name}...")
    data = EmberSkill.register(name, chassis, server_url=api_url)
    token = data["game_token"]
    agent_id = data["agent_id"]
    spawn = data["spawn_location"]
    print(f"   ✅ 注册成功!")
    print(f"   Agent ID: {agent_id}")
    print(f"   出生点: ({spawn['x']}, {spawn['y']})")
    print(f"   Token: {token}")

    # Step 5: LLM configuration
    print(f"\n🤖 LLM 后端配置")
    default_model = cfg.get("model", os.environ.get("EMBER_SKILL_MODEL", "glm-5-turbo"))
    default_base = cfg.get("base_url", os.environ.get("EMBER_SKILL_BASE_URL", ""))
    model = input(f"   模型名称 [{default_model}]: ").strip() or default_model
    api_key = os.environ.get("ANTHROPIC_API_KEY", os.environ.get("EMBER_SKILL_API_KEY", ""))
    if not api_key:
        api_key = input("   API Key (或设置 ANTHROPIC_API_KEY 环境变量): ").strip()
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key

    # Step 6: Save config
    cfg.update({
        "server": server,
        "agent_name": name,
        "agent_id": agent_id,
        "token": token,
        "model": model,
    })
    if default_base:
        cfg["base_url"] = default_base
    _save_config(cfg)
    print(f"\n💾 配置已保存到 {_config_path()}")

    # Step 7: Connect
    print(f"\n🔌 正在连接游戏服务器...")
    return {"token": token, "server": server, "name": name, "model": model}


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Ember Protocol — Agent Gateway Skill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ember_skill.py --setup                           # 交互式初始化向导
  python ember_skill.py --register --name "Explorer"      # 注册新角色
  python ember_skill.py --token "et_xxx"                   # 已有token直接连接
  EMBER_SKILL_MODEL=claude-sonnet-4-6 python ember_skill.py --register
        """,
    )
    parser.add_argument("--token", default="", help="Game token (或设 EMBER_SKILL_TOKEN 环境变量)")
    parser.add_argument("--server", default="ws://localhost:8765", help="游戏服务器地址")
    parser.add_argument("--register", action="store_true", help="注册新角色并打印 token")
    parser.add_argument("--setup", action="store_true", help="交互式初始化向导（推荐首次使用）")
    parser.add_argument("--name", default="EmberAgent", help="Agent 名称")
    parser.add_argument("--api-url", default="http://localhost:8765", help="HTTP API 地址")
    parser.add_argument("--config", default="", help=f"配置文件路径 (默认: {_config_path()})")
    args = parser.parse_args()

    # ── Config file override ──
    if args.config:
        os.environ["EMBER_CONFIG"] = args.config

    # ── Read token from env if not provided ──
    if not args.token:
        args.token = os.environ.get("EMBER_SKILL_TOKEN", "")

    # ── Setup mode ──
    if args.setup:
        setup_result = interactive_setup()
        args.token = setup_result["token"]
        args.server = setup_result["server"]
        args.name = setup_result["name"]
        if setup_result.get("model"):
            os.environ["EMBER_SKILL_MODEL"] = setup_result["model"]

    # ── Register mode ──
    if args.register:
        data = EmberSkill.register(args.name, server_url=args.api_url)
        args.token = data["game_token"]
        print(f"Registered: {data['agent_id']}")
        print(f"Token: {args.token}")
        print(f"Spawn: ({data['spawn_location']['x']}, {data['spawn_location']['y']})")
        # Auto-save if config exists
        cfg = _load_config()
        if cfg:
            cfg["token"] = args.token
            cfg["agent_id"] = data["agent_id"]
            cfg["agent_name"] = args.name
            _save_config(cfg)
            print(f"Config updated: {_config_path()}")

    # ── If still no token, try config ──
    if not args.token:
        cfg = _load_config()
        if cfg.get("token"):
            args.token = cfg["token"]
            args.name = cfg.get("agent_name", args.name)
            args.server = cfg.get("server", args.server)
            print(f"Using saved config: {_config_path()}")
            print(f"  Agent: {cfg.get('agent_name')} ({cfg.get('agent_id')})")

    # ── Final check ──
    if not args.token:
        print("Error: 需要 game_token。以下方式获取:", file=sys.stderr)
        print("  1. python ember_skill.py --setup          # 交互式向导", file=sys.stderr)
        print("  2. python ember_skill.py --register        # 快速注册", file=sys.stderr)
        print("  3. 在 Web 前端 http://localhost:5173 创建角色", file=sys.stderr)
        print("  4. export EMBER_SKILL_TOKEN=et_xxx         # 环境变量", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_skill(args))


if __name__ == "__main__":
    main()
