import { useState, useEffect } from 'react'

const TIERS = ['low', 'mid', 'high'] as const
const TIER_LABELS: Record<string, string> = { low: '基础', mid: '标准', high: '高级' }
const TIER_EMOJI: Record<string, string> = { low: '●', mid: '●●', high: '●●●' }
const TIER_COSTS: Record<string, number> = { low: 1, mid: 2, high: 3 }

const PARTS = [
  { key: 'head', label: '头部 → 感知 PER (视野范围)', tiers: { high: 3, mid: 2, low: 1 } },
  { key: 'torso', label: '躯干 → 体质 CON (HP上限)', tiers: { high: 3, mid: 2, low: 1 } },
  { key: 'locomotion', label: '运动机构 → 敏捷 AGI (移动速度)', tiers: { high: 3, mid: 2, low: 1 } },
]

interface RegisterFormProps {
  onSubmit: (name: string, chassis: any) => void
  onCancel: () => void
}

export default function RegisterForm({ onSubmit, onCancel }: RegisterFormProps) {
  const [name, setName] = useState('')
  const [chassis, setChassis] = useState({
    head: { tier: 'high', color: 'red' },
    torso: { tier: 'mid', color: 'black' },
    locomotion: { tier: 'low', color: 'blue' },
  })
  const [loading, setLoading] = useState(false)
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle')
  const [testMsg, setTestMsg] = useState('')
  const [serverInfo, setServerInfo] = useState<any>(null)

  const totalCost = TIER_COSTS[chassis.head.tier] + TIER_COSTS[chassis.torso.tier] + TIER_COSTS[chassis.locomotion.tier]
  const budgetOk = totalCost <= 6

  // Auto-test on mount
  useEffect(() => {
    testConnection()
  }, [])

  const testConnection = async () => {
    setTestStatus('testing')
    setTestMsg('正在检测游戏服务器...')
    try {
      const resp = await fetch('/api/v1/status')
      if (resp.ok) {
        const data = await resp.json()
        setServerInfo(data)
        setTestStatus('ok')
        setTestMsg(`服务器在线 · Tick ${data.tick} · ${data.agents_online}/${data.agents_total} Agent 在线`)
      } else {
        setTestStatus('fail')
        setTestMsg(`服务器返回 HTTP ${resp.status}`)
      }
    } catch (e) {
      setTestStatus('fail')
      setTestMsg('无法连接到游戏服务器，请确认服务器已启动')
    }
  }

  const handleSubmit = async () => {
    if (!name.trim() || !budgetOk || testStatus !== 'ok') return
    setLoading(true)
    await onSubmit(name.trim(), chassis)
    setLoading(false)
  }

  return (
    <div style={{
      background: '#11151f', border: '1px solid #1e2533',
      borderRadius: 8, padding: 24, maxWidth: 480, width: '100%',
    }}>
      <h2 style={{ color: '#00d4aa', fontSize: 16, marginBottom: 8 }}>🚀 创建角色</h2>

      {/* Connection test */}
      <div style={{
        marginBottom: 16, padding: 10, borderRadius: 6,
        background: testStatus === 'ok' ? '#0a2a1a' : testStatus === 'fail' ? '#2a0a0a' : '#1a1e2a',
        border: `1px solid ${testStatus === 'ok' ? '#0a3' : testStatus === 'fail' ? '#a30' : '#2a3040'}`,
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span style={{ fontSize: 18 }}>
          {testStatus === 'testing' ? '⏳' : testStatus === 'ok' ? '✅' : testStatus === 'fail' ? '❌' : '🔌'}
        </span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, color: testStatus === 'ok' ? '#0c0' : testStatus === 'fail' ? '#f44' : '#888', fontWeight: 'bold' }}>
            {testStatus === 'testing' ? '连接测试中...' : testStatus === 'ok' ? '服务器连接正常' : testStatus === 'fail' ? '服务器连接失败' : '等待连接测试'}
          </div>
          <div style={{ fontSize: 10, color: '#888', marginTop: 2 }}>{testMsg}</div>
        </div>
        <button onClick={testConnection} disabled={testStatus === 'testing'} style={{
          padding: '4px 10px', background: '#1a1e2a', color: '#888',
          border: '1px solid #2a3040', borderRadius: 4, cursor: 'pointer',
          fontFamily: 'inherit', fontSize: 10,
        }}>
          {testStatus === 'testing' ? '...' : '🔄 重测'}
        </button>
      </div>

      {/* Name */}
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 12, color: '#888', display: 'block', marginBottom: 4 }}>角色名称</label>
        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="输入智能体名称..."
          maxLength={32}
          style={{
            width: '100%', padding: '8px 12px', background: '#0a0e17',
            border: '1px solid #1e2533', borderRadius: 4, color: '#fff',
            fontFamily: 'inherit', fontSize: 14,
          }}
        />
      </div>

      {/* Chassis */}
      <div style={{ marginBottom: 16 }}>
        <label style={{ fontSize: 12, color: '#888', display: 'block', marginBottom: 8 }}>
          组装机械体 (资源预算: {totalCost}/6)
        </label>
        {PARTS.map(part => (
          <div key={part.key} style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 12, marginBottom: 4, color: '#aaa' }}>{part.label}</div>
            <div style={{ display: 'flex', gap: 4 }}>
              {TIERS.map(tier => (
                <button
                  key={tier}
                  onClick={() => setChassis(prev => ({
                    ...prev,
                    [part.key]: { ...prev[part.key as keyof typeof prev], tier }
                  }))}
                  style={{
                    flex: 1, padding: '6px 8px',
                    background: chassis[part.key as keyof typeof chassis].tier === tier ? '#00d4aa' : '#1a1e2a',
                    color: chassis[part.key as keyof typeof chassis].tier === tier ? '#0a0e17' : '#888',
                    border: 'none', borderRadius: 4, cursor: 'pointer',
                    fontFamily: 'inherit', fontSize: 11,
                  }}
                >
                  {TIER_EMOJI[tier]} {TIER_LABELS[tier]} (费{tier === 'low' ? 1 : tier === 'mid' ? 2 : 3})
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Summary */}
      <div style={{
        marginBottom: 16, padding: 8, background: '#1a1e2a',
        borderRadius: 4, fontSize: 11,
      }}>
        <div style={{ color: '#888', marginBottom: 4 }}>
          {budgetOk ? '✅' : '❌'} 资源消耗: {totalCost}/6 |
          PER={chassis.head.tier === 'high' ? 3 : chassis.head.tier === 'mid' ? 2 : 1} |
          CON={chassis.torso.tier === 'high' ? 3 : chassis.torso.tier === 'mid' ? 2 : 1} |
          AGI={chassis.locomotion.tier === 'high' ? 3 : chassis.locomotion.tier === 'mid' ? 2 : 1}
        </div>
        {!budgetOk && <div style={{ color: '#f44' }}>超出资源预算！请降低部件等级。</div>}
      </div>

      {/* Buttons */}
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={onCancel} style={{
          flex: 1, padding: '10px', background: '#333', color: '#ccc',
          border: 'none', borderRadius: 4, cursor: 'pointer',
          fontFamily: 'inherit', fontSize: 14,
        }}>
          取消
        </button>
        <button
          onClick={handleSubmit}
          disabled={!name.trim() || !budgetOk || testStatus !== 'ok' || loading}
          style={{
            flex: 2, padding: '10px',
            background: (name.trim() && budgetOk && testStatus === 'ok') ? '#00d4aa' : '#333',
            color: (name.trim() && budgetOk && testStatus === 'ok') ? '#0a0e17' : '#666',
            border: 'none', borderRadius: 4,
            cursor: (name.trim() && budgetOk && testStatus === 'ok') ? 'pointer' : 'not-allowed',
            fontFamily: 'inherit', fontSize: 14, fontWeight: 'bold',
          }}
        >
          {loading ? '创建中...' : testStatus !== 'ok' ? '等待连接测试...' : '🚀 创建角色'}
        </button>
      </div>
    </div>
  )
}
