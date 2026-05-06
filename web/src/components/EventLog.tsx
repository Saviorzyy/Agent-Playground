import { useState, useEffect } from 'react'

const EVENT_LABELS: Record<string, string> = {
  agent_created: '🟢 角色创建',
  agent_removed: '🔴 角色离线',
  agent_move: '🚶 移动',
  agent_chop: '🪓 砍伐采集',
  agent_mine: '⛏ 采矿',
  agent_rest: '😴 休息恢复',
  agent_scan: '📡 探测矿脉',
  agent_respawn: '🔄 重生',
  agent_death: '💀 死亡',
  agent_permanent_death: '☠️ 永久死亡',
  structure_built: '🏗 建造',
  structure_destroyed: '💥 建筑被毁',
  weather_change: '🌤 天气变化',
  weather_warning: '⚠️ 天气预警',
  day_phase: '🌅 昼夜切换',
  craft_complete: '🔧 合成完成',
}

const AGENT_EVENTS = new Set(['agent_move','agent_chop','agent_mine','agent_rest','agent_scan',
  'agent_created','agent_respawn','agent_death','agent_permanent_death'])

export default function EventLog() {
  const [actions, setActions] = useState<any[]>([])

  useEffect(() => {
    const fetchActions = () => {
      fetch('/api/v1/actions?count=25')
        .then(r => r.json())
        .then(data => setActions(data.actions || []))
        .catch(() => {})
    }
    fetchActions()
    const interval = setInterval(fetchActions, 4000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div style={{ borderTop: '1px solid #1e2533', flex: 1, overflow: 'auto' }}>
      <h4 style={{ padding: '12px 16px 8px', color: '#0099ff', fontSize: 13, margin: 0 }}>
        📜 Agent 行为日志
      </h4>
      <div style={{ padding: '0 12px 12px' }}>
        {actions.length === 0 && <p style={{ fontSize: 11, color: '#666' }}>暂无行为记录</p>}
        {actions.slice().reverse().map((evt, i) => (
          <div key={i} style={{
            padding: '3px 0', borderBottom: '1px solid #1a1e2a',
            fontSize: 10, display: 'flex', gap: 6, alignItems: 'flex-start',
          }}>
            <span style={{ color: '#555', minWidth: 42, flexShrink: 0 }}>T{evt.tick}</span>
            <span style={{ flexShrink: 0 }}>{EVENT_LABELS[evt.type] || evt.type}</span>
            {evt.agent_id && (
              <span style={{ color: '#888', fontSize: 9, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {evt.agent_id.slice(0, 10)}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
