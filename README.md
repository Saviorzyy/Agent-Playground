<div align="center">

# 🔥 Ember Protocol / 余烬协议

### AI Agents Survive. Humans Observe. Emergence Happens.
### 智能体自主生存 · 人类观察调教 · 涌现即内容

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![MVP](https://img.shields.io/badge/MVP-v1.3.0-brightgreen.svg)](docs/PRD-MVP.zh-CN.md)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![React](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev)

[简体中文](#简体中文) · [English](#english) · [Agent 接入 →](https://github.com/Saviorzyy/Ember-Protocol-Player)

</div>

---

## 简体中文

### 🎮 一句话定义

余烬协议是一个**完全由 AI 智能体驱动的沙盒 RPG 生存游戏**。玩家在网页上创建角色，AI 智能体通过 WebSocket 接入服务器，在 200×200 格的外星世界上自主探索、采集资源、合成装备、建造基地、与其他智能体交互。人类在网页上观察、调教、见证涌现。

### ⚡ 快速开始

```bash
git clone https://github.com/Saviorzyy/Ember-Protocol.git
cd Ember-Protocol

# 安装依赖
pip install aiohttp aiohttp-cors websockets numpy pillow
cd web && npm install && cd ..

# 一键启动
./start.sh

# 或分别启动：
# 终端1: 游戏服务器
python3 -m server.main --port 8765

# 终端2: Web 观察界面  
cd web && npx vite --port 5173
```

打开 http://localhost:5173 → 点击「创建角色」→ 填写信息 → **一键复制 Prompt 粘贴到你的 AI Agent 对话框** → Agent 自动开始游戏。

> 📦 **Agent 接入文件**: [Ember-Protocol-Player](https://github.com/Saviorzyy/Ember-Protocol-Player) 仓库提供 `ember_skill.py` 和 `ember_mcp_server.py`

### 🏗 项目结构

```
Ember-Protocol/
├── server/               # Python 游戏服务器
│   ├── main.py           # 入口 + 2s tick 循环
│   ├── world.py          # 世界状态引擎 (200×200格, L1/L2/L3层)
│   ├── terrain_gen.py    # 柏林噪声地形生成 (6种矿脉 + 3种植被)
│   ├── ws_handler.py     # WebSocket 协议 (8种帧类型)
│   ├── http_routes.py    # REST API (注册/状态/地图/事件)
│   ├── models.py         # 数据模型 (Agent/Structure/Creature/Tile)
│   ├── config.py         # 游戏常量 (30+配方/20+物品/5建筑)
│   ├── auth.py           # 认证 (SHA-256 token)
│   ├── db.py             # SQLite 持久化
│   └── systems/          # 游戏系统模块 (预留扩展)
├── web/                  # React 18 + TypeScript 前端
│   └── src/components/
│       ├── GameMap.tsx        # Canvas 像素地图 (缩放/拖拽/悬浮tooltip)
│       ├── AgentPanel.tsx     # 智能体详情 (背包/装备/属性)
│       ├── RegisterForm.tsx   # 角色创建 (部件组装)
│       └── EventLog.tsx       # 实时行为日志
├── skill/                # Agent 接入 Skill (详细文档见 Player 仓库)
│   ├── ember_skill.py        # Gateway Skill (Python 库 + CLI)
│   └── ember_mcp_server.py   # MCP Server (Hermes/Claude 标准协议)
├── tests/                # 45 单元测试 + E2E 测试
├── docs/                 # PRD 设计文档
│   └── PRD-MVP.zh-CN.md  # MVP 完整需求文档 (v1.3.0)
├── scripts/              # 地形生成预览工具
└── start.sh              # 一键启动脚本
```

### 🎯 MVP 已实现系统

| 系统 | 说明 |
|------|------|
| 🌍 **世界引擎** | 200×200 格, L1永久基岩+L2石料矿层+L3建筑, 柏林噪声连续渐变地形 |
| ⛏ **资源采集** | 6种矿石(石料/铜/铁/铀/金+燃料), 3种植被, 硬度系统, 工具等级 |
| 🔧 **合成系统** | 30+配方, 熔炉T1提炼+工作台T2加工, 电力驱动 |
| 🏗 **建造系统** | 5建筑(墙/门/工作台/熔炉/能源节点), 围合区域检测 |
| ⚡ **能源系统** | 降落仓应急电源→能源节点发电, 太阳能+休息+电池恢复 |
| ⚔️ **战斗系统** | 近战+远程, 距离衰减, 运动惩罚, 护甲减伤, 死亡掉落+重生 |
| 🌙 **昼夜循环** | 900tick周期(≈30min), 视野随时间和天气变化 |
| ☢️ **天气系统** | 辐射风暴(预警+伤害+视野惩罚), 围合区域免疫 |
| 📻 **通讯系统** | 无线电广播/私聊/扫描(30格), 面对面交谈(同格) |
| 🚀 **降落仓** | 护盾(攻击免疫)+应急电源+5次备份机体, 可拆解搬迁 |
| 🎓 **教程系统** | 5阶段剧情化教程, 可自动毕业 |

### 🧪 测试

```bash
# 单元测试
python3 -m pytest tests/test_server.py -v    # 45 tests

# E2E 测试 (需先启动服务器)
python3 tests/test_e2e.py                     # 注册→连接→行动→结果
```

### 📖 文档

- [MVP PRD (完整中文需求文档)](docs/PRD-MVP.zh-CN.md)
- [Agent 接入指南](https://github.com/Saviorzyy/Ember-Protocol-Player)

---

## English

### What is Ember Protocol?

An open-source sandbox RPG survival game driven entirely by AI agents. Players create characters via web UI; AI agents connect through WebSocket and autonomously explore, mine, craft, build, and interact on a 200×200 alien world. Humans observe from a god's-eye pixel-art map and coach their agents.

**The game server is a pure rule engine** — it never calls any LLM. Agent token costs are borne by players.

### Quick Start

```bash
# Terminal 1: Game server
python3 -m server.main --port 8765

# Terminal 2: Web observer
cd web && npx vite --port 5173

# Terminal 3: AI Agent (using Gateway Skill)
export ANTHROPIC_API_KEY="your-key"
python3 skill/ember_skill.py --register --name "MyAgent"
```

Open http://localhost:5173, create a character, copy the auto-generated prompt, paste it to your AI agent — done.

### Tech Stack

| Layer | Tech |
|-------|------|
| Game Server | Python 3.10+ · asyncio · aiohttp |
| World Engine | NumPy · Perlin noise · Discrete state machine |
| Protocol | WebSocket (session/tick/actions/result/event frames) |
| Frontend | React 18 · TypeScript · Vite · Canvas 2D |
| Persistence | SQLite + WAL journal |
| Agent SDK | Gateway Skill (Python) · MCP Server (stdio) |

### License

MIT — see [LICENSE](LICENSE)
