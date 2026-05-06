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

  const handleRegister = async (name: string, chassis: any) => {
    try {
      const res = await fetch('/api/v1/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_name: name, chassis }),
      })
      if (res.ok) {
        const data = await res.json()
        setToken(data.game_token)
        setRegData(data)
        setShowRegister(false)
        fetchAgents()
      } else {
        const err = await res.json()
        alert(err.error || '注册失败')
      }
    } catch (e) {
      alert('无法连接到游戏服务器')
    }
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

      {/* Registration success — Copy-Paste Prompt */}
      {token && regData && (() => {
        const skillPrompt = `我需要你连接到 Ember Protocol（余烬协议）游戏服务器。

## 接入方式：Gateway Skill

请使用 ember_skill.py 文件，按以下方式连接：

1. 确保已安装依赖: pip install websockets anthropic requests
2. 设置你的 LLM API Key（如果还没设置）
3. 运行以下命令接入游戏：

\`\`\`bash
export ANTHROPIC_API_KEY="<你的LLM API Key>"
python3 ember_skill.py \\
  --token "${token}" \\
  --server ws://localhost:8765
\`\`\`

游戏服务器地址: ws://localhost:8765
Token: ${token}
角色ID: ${regData.agent_id}
出生点: (${regData.spawn_location.x}, ${regData.spawn_location.y})

请立刻执行连接并开始探索游戏世界。你的角色已经在降落仓中苏醒，初始背包有工作台、熔炉和有机燃料。教程阶段为Phase 0，查看背包(inspect inventory)后即可进入自由探索模式。`

        const mcpPrompt = `我需要你通过 MCP Server 连接到 Ember Protocol（余烬协议）游戏服务器。

## 接入方式：MCP Server

请在你的 MCP 配置中添加以下 ember server：

\`\`\`yaml
mcp_servers:
  ember:
    command: python3
    args:
      - "/path/to/ember_mcp_server.py"
      - "--token"
      - "${token}"
      - "--server"
      - "ws://localhost:8765"
\`\`\`

配置完成后，重启你的 Agent。你将获得以下 MCP 工具：
- ember_tick: 获取游戏状态
- ember_act: 提交行动
- ember_status: 查看自身状态

游戏服务器: ws://localhost:8765
Token: ${token}
角色ID: ${regData.agent_id}

请立刻调用 ember_tick 获取游戏状态，然后根据状态决定行动。你的角色在降落仓中苏醒，初始背包有工作台、熔炉和有机燃料×5。先查看背包，然后走出降落仓探索。`

        const promptText = copyMode === 'skill' ? skillPrompt : mcpPrompt
        const skillUrl = 'https://github.com/Saviorzyy/Ember-Protocol-Player'

        return (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.85)', display: 'flex',
          alignItems: 'center', justifyContent: 'center', zIndex: 100,
          overflow: 'auto', padding: '20px',
        }}>
          <div style={{
            background: '#11151f', border: '1px solid #1e2533',
            borderRadius: 8, padding: 24, maxWidth: 620, width: '100%',
          }}>
            <h2 style={{ color: '#00d4aa', marginBottom: 2, fontSize: 18 }}>✅ 角色创建成功</h2>
            <p style={{ color: '#888', fontSize: 11, marginBottom: 14 }}>
              {regData.agent_id} · 出生点 ({regData.spawn_location.x}, {regData.spawn_location.y}) · HP 110 · 能量 100
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
                📋 复制以下内容，粘贴到你的 Agent 对话框（Hermes / Claude / ChatGPT 等）：
              </div>
              <pre style={{
                background: '#0a0e17', padding: 14, borderRadius: 6, color: '#ccc',
                fontSize: 11, lineHeight: '17px', whiteSpace: 'pre-wrap',
                border: '1px solid #2a3040', maxHeight: 280, overflow: 'auto',
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

            {/* Links + close */}
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => { setToken(''); setRegData(null); setCopied(false) }} style={{
                flex: 1, padding: '8px', background: '#333', color: '#ccc',
                border: 'none', borderRadius: 4, cursor: 'pointer',
                fontFamily: 'inherit', fontSize: 12,
              }}>
                关闭
              </button>
              <a href={skillUrl} target="_blank" rel="noopener" style={{
                flex: 1, padding: '8px', background: '#1a1f2a', color: '#0099ff',
                border: '1px solid #2a3040', borderRadius: 4, cursor: 'pointer',
                fontFamily: 'inherit', fontSize: 12, textAlign: 'center', textDecoration: 'none',
              }}>
                📦 下载 Skill 文件
              </a>
            </div>
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
