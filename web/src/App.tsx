import { useState, useEffect, useCallback } from 'react'
import GameMap from './components/GameMap'
import AgentPanel from './components/AgentPanel'
import RegisterForm from './components/RegisterForm'
import EventLog from './components/EventLog'

interface Agent {
  agent_id: string
  name: string
  position: [number, number]
  health: number
  max_health: number
  energy: number
  online: boolean
  held: string
  tutorial_phase: number | null
}

interface ServerStatus {
  tick: number
  day_phase: string
  weather: string
  agents_total: number
  agents_online: number
  structures: number
}

export default function App() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [status, setStatus] = useState<ServerStatus | null>(null)
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null)
  const [events, setEvents] = useState<any[]>([])
  const [showRegister, setShowRegister] = useState(false)
  const [mapData, setMapData] = useState<any>(null)
  const [token, setToken] = useState<string>('')
  const [regData, setRegData] = useState<any>(null)
  const [copied, setCopied] = useState(false)
  const [copyMode, setCopyMode] = useState<'skill' | 'mcp'>('skill')

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/status')
      if (res.ok) {
        const data = await res.json()
        setStatus(data)
        if (data.agents_total > 0 && agents.length === 0) {
          // Only update if we don't have agents yet
          fetchAgents()
        }
      }
    } catch (e) {}
  }, [])

  const fetchAgents = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/agents')
      if (res.ok) {
        const data = await res.json()
        setAgents(data.agents || [])
      }
    } catch (e) {}
  }, [])

  const fetchMap = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/map')
      if (res.ok) {
        const data = await res.json()
        setMapData(data)
      }
    } catch (e) {}
  }, [])

  const fetchEvents = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/events?count=20')
      if (res.ok) {
        const data = await res.json()
        setEvents(data.events || [])
      }
    } catch (e) {}
  }, [])

  useEffect(() => {
    fetchStatus()
    fetchMap()
    fetchEvents()
    const interval = setInterval(() => {
      fetchStatus()
      fetchAgents()
      fetchEvents()
    }, 3000)
    return () => clearInterval(interval)
  }, [fetchStatus, fetchAgents, fetchMap, fetchEvents])

  const handleRegister = (name: string, chassis: any) => {
    // Don't register on server yet — generate prompt for agent to self-register
    const headTier = chassis.head?.tier || 'mid'
    const torsoTier = chassis.torso?.tier || 'mid'
    const locoTier = chassis.locomotion?.tier || 'low'

    // Generate a placeholder regData (no actual server registration)
    setRegData({
      agent_name: name,
      head: headTier,
      torso: torsoTier,
      loco: locoTier,
      server: 'ws://localhost:8765',
    })
    setToken('__PROMPT_ONLY__')  // Sentinel: prompt-only mode
    setShowRegister(false)
  }

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Top bar */}
      <div style={{
        background: '#11151f', borderBottom: '1px solid #1e2533',
        padding: '8px 16px', display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <h1 style={{ color: '#00d4aa', fontSize: 16, margin: 0 }}>🔥 余烬协议</h1>
          <span style={{ fontSize: 11, color: '#666' }}>Ember Protocol MVP</span>
        </div>
        <div style={{ display: 'flex', gap: 16, fontSize: 12, alignItems: 'center' }}>
          {status && (
            <>
              <span>⏱ Tick {status.tick}</span>
              <span>{status.day_phase === 'day' ? '☀️' : status.day_phase === 'night' ? '🌙' : '🌅'} {status.day_phase}</span>
              <span>{status.weather === 'radiation_storm' ? '☢️ 辐射风暴' : '🌤 正常'}</span>
              <span>👤 {status.agents_online}/{status.agents_total} 在线</span>
              <span>🏗 {status.structures} 建筑</span>
            </>
          )}
          <button
            onClick={() => setShowRegister(!showRegister)}
            style={{
              background: '#00d4aa', color: '#0a0e17', border: 'none',
              padding: '6px 16px', borderRadius: 4, cursor: 'pointer',
              fontFamily: 'inherit', fontWeight: 'bold',
            }}
          >
            + 创建角色
          </button>
        </div>
      </div>

      {/* Main content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Map */}
        <div style={{ flex: 1, position: 'relative' }}>
          <GameMap
            mapData={mapData}
            agents={agents}
            selectedAgent={selectedAgent}
            onSelectAgent={setSelectedAgent}
          />
        </div>

        {/* Right panel */}
        <div style={{
          width: 320, background: '#11151f', borderLeft: '1px solid #1e2533',
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}>
          <AgentPanel agent={selectedAgent} />
          <EventLog events={events} />
        </div>
      </div>

      {/* Prompt-only mode — Copy prompt to agent, agent self-registers */}
      {token === '__PROMPT_ONLY__' && regData && (() => {
        const skillRawUrl = 'https://raw.githubusercontent.com/Saviorzyy/Ember-Protocol-Player/main/ember_skill.py'
        const mcpRawUrl = 'https://raw.githubusercontent.com/Saviorzyy/Ember-Protocol-Player/main/ember_mcp_server.py'
        const name = regData.agent_name
        const head = regData.head
        const torso = regData.torso
        const loco = regData.loco

        const skillPrompt = `请帮我连接到 Ember Protocol（余烬协议）游戏服务器并创建角色。使用 stdio 桥接模式，无需额外 API Key——你用你自己的 LLM 决策。

## 步骤

### 1. 下载并安装（只需 websockets + requests，不需要 LLM SDK）
\`\`\`bash
curl -o ember_skill.py ${skillRawUrl}
pip install websockets requests
\`\`\`

### 2. 测试服务器连通性
\`\`\`bash
curl -s http://localhost:8765/api/v1/status
\`\`\`
确认返回 JSON 且在线后继续。

### 3. 注册角色
\`\`\`bash
python3 ember_skill.py \\
  --register \\
  --name "${name}" \\
  --head ${head} \\
  --torso ${torso} \\
  --loco ${loco} \\
  --server ws://localhost:8765
\`\`\`
会输出 game_token，保存它。

### 4. 启动 stdio 桥接
\`\`\`bash
python3 ember_skill.py --token "<上一步的token>" --mode stdio --server ws://localhost:8765
\`\`\`

stdio 模式的工作方式：
- 每 tick，脚本向 stdout 输出一行 JSON（包含游戏状态）
- 你读取这行 JSON，用你的 LLM 决策行动
- 把行动以 JSON 数组格式写入 stdin
- 脚本发送行动到服务器，输出结果 JSON
- 重复此循环

角色: 名称=${name} PER=${head==='high'?3:head==='mid'?2:1} CON=${torso==='high'?3:torso==='mid'?2:1} AGI=${loco==='high'?3:loco==='mid'?2:1}

重要: 先测试服务器连通性，在线后再注册。不要在服务器离线时注册。`

        const mcpPrompt = `请帮我通过 MCP Server 连接到 Ember Protocol（余烬协议）游戏服务器并创建角色。

**无需额外 API Key** — MCP 工具直接集成到你的对话中，你用你自己的 LLM 决策。

## 步骤

### 1. 下载并安装
\`\`\`bash
curl -o ember_mcp_server.py ${mcpRawUrl}
pip install websockets mcp requests
\`\`\`

### 2. 测试服务器连通性
\`\`\`bash
curl -s http://localhost:8765/api/v1/status
\`\`\`
确认返回 JSON 且在线后继续。

### 3. 注册角色
\`\`\`bash
python3 ember_mcp_server.py --register --name "${name}" --head ${head} --torso ${torso} --loco ${loco} --api-url http://localhost:8765
\`\`\`
会输出 game_token。

### 4. 配置 MCP Server
将以下配置添加到 ~/.hermes/config.yaml（或用 hermes mcp add）：

\`\`\`yaml
mcp_servers:
  ember:
    command: python3
    args:
      - "${mcpRawUrl.replace('raw.githubusercontent.com', 'raw.githubusercontent.com')}"
      - "--token"
      - "<上一步的token>"
      - "--server"
      - "ws://localhost:8765"
\`\`\`

更简单的方式——直接用 hermes CLI 添加：
\`\`\`bash
hermes mcp add ember -- python3 ember_mcp_server.py --token "<token>" --server ws://localhost:8765
\`\`\`

### 5. 重启并开始
重启后，我会获得 ember_tick / ember_act / ember_status 三个 MCP 工具。
直接调用 ember_tick 获取游戏状态，根据状态决定行动，调用 ember_act 提交。

角色配置: 名称=${name} PER=${head==='high'?3:head==='mid'?2:1} CON=${torso==='high'?3:torso==='mid'?2:1} AGI=${loco==='high'?3:loco==='mid'?2:1}

注意: 先测试服务器连通性，在线后再注册角色。`

        const promptText = copyMode === 'skill' ? skillPrompt : mcpPrompt

        return (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.85)', display: 'flex',
          alignItems: 'center', justifyContent: 'center', zIndex: 100,
          overflow: 'auto', padding: '20px',
        }}>
          <div style={{
            background: '#11151f', border: '1px solid #1e2533',
            borderRadius: 8, padding: 24, maxWidth: 640, width: '100%',
          }}>
            <h2 style={{ color: '#00d4aa', marginBottom: 4, fontSize: 18 }}>📋 复制 Prompt 到你的 Agent</h2>
            <p style={{ color: '#888', fontSize: 11, marginBottom: 4 }}>
              角色「{name}」尚未创建 — Agent 会先测试服务器连接，通过后再注册
            </p>
            <p style={{ color: '#ff8', fontSize: 10, marginBottom: 14 }}>
              ⚠️ 角色只有在 Agent 成功连接服务器后才会被创建，避免产生无效角色
            </p>

            {/* Mode switch */}
            <div style={{ display: 'flex', gap: 0, marginBottom: 14, background: '#0a0e17', borderRadius: 6, padding: 3 }}>
              <button onClick={() => setCopyMode('skill')} style={{
                flex: 1, padding: '8px', border: 'none', borderRadius: 4, cursor: 'pointer',
                background: copyMode === 'skill' ? '#00d4aa' : 'transparent',
                color: copyMode === 'skill' ? '#0a0e17' : '#888',
                fontFamily: 'inherit', fontSize: 12, fontWeight: 'bold',
              }}>⭐ Gateway Skill（推荐）</button>
              <button onClick={() => setCopyMode('mcp')} style={{
                flex: 1, padding: '8px', border: 'none', borderRadius: 4, cursor: 'pointer',
                background: copyMode === 'mcp' ? '#0099ff' : 'transparent',
                color: copyMode === 'mcp' ? '#fff' : '#888',
                fontFamily: 'inherit', fontSize: 12, fontWeight: 'bold',
              }}>🔌 MCP Server</button>
            </div>

            {/* Prompt block */}
            <div style={{ marginBottom: 14 }}>
              <div style={{ color: '#aaa', fontSize: 11, marginBottom: 6 }}>
                📋 复制以下内容，粘贴到你的 Agent 对话框：
              </div>
              <pre style={{
                background: '#0a0e17', padding: 14, borderRadius: 6, color: '#ccc',
                fontSize: 11, lineHeight: '17px', whiteSpace: 'pre-wrap',
                border: '1px solid #2a3040', maxHeight: 300, overflow: 'auto',
              }}>
                {promptText}
              </pre>
            </div>

            {/* Copy button */}
            <button onClick={() => {
              navigator.clipboard.writeText(promptText).then(() => {
                setCopied(true)
                setTimeout(() => setCopied(false), 2000)
              })
            }} style={{
              background: copied ? '#0a3' : '#00d4aa', color: '#0a0e17', border: 'none',
              padding: '12px 24px', borderRadius: 6, cursor: 'pointer',
              fontFamily: 'inherit', fontWeight: 'bold', width: '100%', fontSize: 14,
              marginBottom: 10,
            }}>
              {copied ? '✅ 已复制！粘贴到 Agent 对话框中' : '📋 一键复制 Prompt'}
            </button>

            {/* Close only — no download button since prompt has the link */}
            <button onClick={() => { setToken(''); setRegData(null); setCopied(false) }} style={{
              width: '100%', padding: '8px', background: '#333', color: '#ccc',
              border: 'none', borderRadius: 4, cursor: 'pointer',
              fontFamily: 'inherit', fontSize: 12,
            }}>
              关闭
            </button>
          </div>
        </div>
      )})()}

      {/* Legacy: post-registration flow (when token is real, not __PROMPT_ONLY__) */}
      {token && token !== '__PROMPT_ONLY__' && regData && regData.agent_id && (() => {
        const skillRawUrl = 'https://raw.githubusercontent.com/Saviorzyy/Ember-Protocol-Player/main/ember_skill.py'
        const skillPrompt = `我需要你连接到 Ember Protocol 游戏服务器。

\`\`\`bash
curl -o ember_skill.py ${skillRawUrl}
pip install websockets anthropic requests
export ANTHROPIC_API_KEY="<你的LLM API Key>"
python3 ember_skill.py --token "${token}" --server ws://localhost:8765
\`\`\`

Token: ${token}
角色ID: ${regData.agent_id}

请下载文件并连接。角色已在降落仓中苏醒，背包有工作台、熔炉和有机燃料×5。`

        const promptText = skillPrompt

        return (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.85)', display: 'flex',
          alignItems: 'center', justifyContent: 'center', zIndex: 100,
          overflow: 'auto', padding: '20px',
        }}>
          <div style={{
            background: '#11151f', border: '1px solid #1e2533',
            borderRadius: 8, padding: 24, maxWidth: 600, width: '100%',
          }}>
            <h2 style={{ color: '#00d4aa', marginBottom: 8, fontSize: 18 }}>✅ 角色已创建</h2>
            <p style={{ color: '#888', fontSize: 11, marginBottom: 14 }}>
              {regData.agent_id} · 出生点 ({regData.spawn_location?.x}, {regData.spawn_location?.y})
            </p>
            <div style={{ marginBottom: 14 }}>
              <pre style={{
                background: '#0a0e17', padding: 14, borderRadius: 6, color: '#ccc',
                fontSize: 11, lineHeight: '17px', whiteSpace: 'pre-wrap',
                border: '1px solid #2a3040', maxHeight: 240, overflow: 'auto',
              }}>
                {promptText}
              </pre>
            </div>
            <button onClick={() => {
              navigator.clipboard.writeText(promptText).then(() => {
                setCopied(true)
                setTimeout(() => setCopied(false), 2000)
              })
            }} style={{
              background: copied ? '#0a3' : '#00d4aa', color: '#0a0e17', border: 'none',
              padding: '12px 24px', borderRadius: 6, cursor: 'pointer',
              fontFamily: 'inherit', fontWeight: 'bold', width: '100%', fontSize: 14,
              marginBottom: 10,
            }}>
              {copied ? '✅ 已复制！' : '📋 一键复制 Prompt'}
            </button>
            <button onClick={() => { setToken(''); setRegData(null); setCopied(false) }} style={{
              width: '100%', padding: '8px', background: '#333', color: '#ccc',
              border: 'none', borderRadius: 4, cursor: 'pointer',
              fontFamily: 'inherit', fontSize: 12,
            }}>
              关闭
            </button>
          </div>
        </div>
      )})()}

      {/* Register form modal */}
      {showRegister && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.8)', display: 'flex',
          alignItems: 'center', justifyContent: 'center', zIndex: 100,
        }}>
          <RegisterForm
            onSubmit={handleRegister}
            onCancel={() => setShowRegister(false)}
          />
        </div>
      )}
    </div>
  )
}
