import { useEffect, useRef } from 'react'
import { useGame } from '@/game/state'
import { stageRevenue, repLevel, forgeLevel, fmt } from '@/game/engine'
import { Panel } from '@/components/pixel'

export default function Log() {
  const { state } = useGame()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight })
  }, [state.log.length])

  const nextHints: string[] = []
  if (!state.ending) {
    if (state.amei.stage < 5) {
      const need = stageRevenue(state.amei.stage, state.difficulty)
      nextHints.push(`阿梅的下一步：总营收达到 ${fmt(need)}G 后与她对话（当前 ${fmt(state.totalRevenue)}G）`)
    } else if (!state.amei.finalTriggered) {
      nextHints.push(`最终时刻：总营收达到 ${fmt(stageRevenue(5, state.difficulty))}G（当前 ${fmt(state.totalRevenue)}G）`)
    }
    if (state.xiaoling.affection < 80) nextHints.push(`小铃好感 ${state.xiaoling.affection}/80：好感 80 后她可能会说出心里话`)
    if (repLevel(state.rep) < 5) nextHints.push(`声誉 ${state.rep}：完成订单、卖出高品质武器可提升`)
    if (forgeLevel(state.forgeExp) < 7) nextHints.push(`锻造经验 ${state.forgeExp}：锻造更好的武器来升级`)
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Panel title="剧情日志" className="lg:col-span-2">
        <div ref={ref} className="max-h-[480px] overflow-y-auto space-y-1 pr-2">
          {state.log.map((l, i) => (
            <div
              key={i}
              className="text-sm"
              style={{
                color: l.kind === 'story' ? '#6b3d1a' : l.kind === 'hint' ? '#b3341f' : '#4a4640',
                fontWeight: l.kind === 'story' ? 600 : 400,
              }}
            >
              {l.kind === 'story' ? '❖ ' : l.kind === 'hint' ? '▶ ' : '· '}{l.text}
            </div>
          ))}
        </div>
      </Panel>
      <Panel title="下一步线索">
        {nextHints.length === 0 ? (
          <div className="text-sm opacity-60">故事已抵达终点。</div>
        ) : (
          <div className="space-y-2">
            {nextHints.map((h, i) => <div key={i} className="text-sm">· {h}</div>)}
          </div>
        )}
        <div className="mt-3 text-xs opacity-60">
          提示：剧情由「总营收」（累计获得的金币，花掉也不减少）与对话触发。没有时间限制，按自己的节奏经营就好。
        </div>
      </Panel>
    </div>
  )
}
