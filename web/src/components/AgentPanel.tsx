import { useState, useEffect } from 'react'

interface Agent {
  agent_id: string; name: string; position: [number, number]
  health: number; max_health: number; energy: number
  online: boolean; held: string; tutorial_phase: number | null
}

interface AgentDetail {
  agent_id: string; name: string; position: [number, number]
  health: number; max_health: number; energy: number; max_energy: number
  online: boolean; held: string; off_hand: string | null; armor: string | null
  backup_count: number; tutorial_phase: number | null
  drop_pod_pos: [number, number] | null; drop_pod_deployed: boolean
  attributes: { PER: number; CON: number; AGI: number }
  inventory: Array<{ item_id: string; amount: number; durability?: number | null }>
  status: string
}

const ITEM_NAMES: Record<string, string> = {
  workbench: '工作台', furnace: '熔炉', organic_fuel: '有机燃料',
  stone: '石料', wood: '木质', building_block: '建材方块',
  raw_copper: '铜矿', raw_iron: '铁矿', raw_gold: '金矿', uranium_ore: '铀矿',
  copper_ingot: '铜碇', iron_ingot: '铁碇', gold_ingot: '金碇',
  carbon: '碳', silicon: '硅', wire: '电线', carbon_fiber: '碳纤维',
  basic_excavator: '基础采掘器', standard_excavator: '标准采掘器', heavy_excavator: '重型采掘器',
  cutter: '切割器',
  plasma_cutter_mk1: '等离子刀Mk.I', plasma_cutter_mk2: '等离子刀Mk.II', plasma_cutter_mk3: '等离子刀Mk.III',
  pulse_emitter_mk1: '脉冲发射器Mk.I', pulse_emitter_mk2: '脉冲发射器Mk.II', pulse_emitter_mk3: '脉冲发射器Mk.III',
  radiation_armor: '辐射防护服', searchlight: '探照灯', signal_amplifier: '信号放大器',
  repair_kit: '修理包', battery: '电池', radiation_antidote: '辐射药剂',
  copper_coin: '铜币', iron_coin: '铁币', gold_coin: '金币',
  acid_blood: '酸性血液', organic_toxin: '有机毒物', organic_fiber: '有机纤维',
}

interface AgentPanelProps { agent: Agent | null }

export default function AgentPanel({ agent }: AgentPanelProps) {
  const [detail, setDetail] = useState<AgentDetail | null>(null)

  useEffect(() => {
    if (!agent) { setDetail(null); return }
    fetch(`/api/v1/agents/${agent.agent_id}`)
      .then(r => r.json())
      .then(data => setDetail(data))
      .catch(() => setDetail(null))
    const interval = setInterval(() => {
      fetch(`/api/v1/agents/${agent.agent_id}`)
        .then(r => r.json())
        .then(data => setDetail(data))
        .catch(() => {})
    }, 3000)
    return () => clearInterval(interval)
  }, [agent?.agent_id])

  if (!agent) {
    return (
      <div style={{ padding: 16, flex: 1, overflow: 'auto' }}>
        <h3 style={{ color: '#0099ff', fontSize: 14, marginBottom: 8 }}>👤 智能体详情</h3>
        <p style={{ fontSize: 12, color: '#666' }}>点击地图上的 Agent 查看详情</p>
      </div>
    )
  }

  const d = detail
  const hpPct = agent.max_health > 0 ? (agent.health / agent.max_health) * 100 : 0
  const energyPct = (agent.energy / 100) * 100

  return (
    <div style={{ padding: 16, flex: 1, overflow: 'auto' }}>
      <h3 style={{ color: '#0099ff', fontSize: 14, marginBottom: 10 }}>
        👤 {agent.name}
        <span style={{ marginLeft: 8, fontSize: 10, padding: '2px 6px', borderRadius: 3,
          background: agent.online ? '#0a3' : '#333', color: '#fff' }}>
          {agent.online ? '在线' : '离线'}
        </span>
      </h3>

      <div style={{ fontSize: 12, lineHeight: '18px' }}>
        {/* Bars */}
        <div style={{ marginBottom: 6 }}>
          <span style={{ color: '#888' }}>HP </span>
          <span style={{ fontSize: 10 }}>{agent.health}/{agent.max_health}</span>
          <div style={{ background: '#1a1e2a', height: 8, borderRadius: 3, overflow: 'hidden', marginTop: 1 }}>
            <div style={{ width: `${hpPct}%`, height: '100%', background: hpPct > 50 ? '#0f0' : hpPct > 25 ? '#ff0' : '#f00' }} />
          </div>
        </div>
        <div style={{ marginBottom: 8 }}>
          <span style={{ color: '#888' }}>⚡ 能量 </span>
          <span style={{ fontSize: 10 }}>{agent.energy}/100</span>
          <div style={{ background: '#1a1e2a', height: 8, borderRadius: 3, overflow: 'hidden', marginTop: 1 }}>
            <div style={{ width: `${energyPct}%`, height: '100%', background: '#00d4aa' }} />
          </div>
        </div>

        {/* Stats */}
        <div style={{ marginBottom: 4 }}>📍 ({agent.position[0]}, {agent.position[1]})</div>
        <div style={{ marginBottom: 4 }}>🎯 {agent.held || '空手'}</div>

        {d && (
          <>
            <div style={{ marginBottom: 4, color: '#aaa' }}>
              PER:{d.attributes.PER} CON:{d.attributes.CON} AGI:{d.attributes.AGI}
            </div>
            <div style={{ marginBottom: 4 }}>
              🛡 {d.armor || '无护甲'} | 🔧 {d.off_hand || '副手空'}
            </div>
            <div style={{ marginBottom: 4 }}>
              💾 备份机体: {d.backup_count} | 🚀 降落仓: {d.drop_pod_deployed ? '已部署' : '已打包'}
              {d.drop_pod_pos && ` (${d.drop_pod_pos[0]},${d.drop_pod_pos[1]})`}
            </div>
            {d.tutorial_phase !== null && d.tutorial_phase !== undefined && (
              <div style={{ marginBottom: 4, color: '#ffd700' }}>📖 教程 Phase {d.tutorial_phase}</div>
            )}
          </>
        )}

        {/* Inventory */}
        {d && d.inventory && (
          <div style={{ marginTop: 10 }}>
            <div style={{ color: '#0099ff', fontSize: 12, marginBottom: 6, borderBottom: '1px solid #1e2533', paddingBottom: 4 }}>
              📦 背包 ({d.inventory.length}/20)
            </div>
            {d.inventory.length === 0 ? (
              <div style={{ fontSize: 10, color: '#666' }}>空</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {d.inventory.map((item, i) => (
                  <div key={i} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    fontSize: 10, padding: '2px 6px', background: '#1a1e2a', borderRadius: 3,
                  }}>
                    <span style={{ color: '#ccc' }}>
                      {ITEM_NAMES[item.item_id] || item.item_id}
                    </span>
                    <span style={{ color: '#888' }}>
                      ×{item.amount}
                      {item.durability != null && <span style={{ color: '#666' }}> 🔧{item.durability}</span>}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Energy explanation */}
        <div style={{ marginTop: 10, padding: 6, background: '#1a1e2a', borderRadius: 4, fontSize: 9, color: '#666', lineHeight: '14px' }}>
          ⚡ 行动消耗: 移动-1 采集-2 合成-3 建造-5<br />
          🔋 恢复: 太阳能+1/tick 休息+3/tick
        </div>
      </div>
    </div>
  )
}
