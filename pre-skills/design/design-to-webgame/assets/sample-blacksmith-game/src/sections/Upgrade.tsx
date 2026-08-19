import { useGame } from '@/game/state'
import { FACILITY_INFO, FACILITY_MAX, REP_LEVELS, REP_PERKS, FORGE_LEVELS } from '@/game/data'
import { repLevel, forgeLevel, fmt } from '@/game/engine'
import type { FacilityId } from '@/game/types'
import { Panel, Btn, Bar } from '@/components/pixel'

export default function Upgrade() {
  const { state, dispatch } = useGame()
  const rl = repLevel(state.rep)
  const fl = forgeLevel(state.forgeExp)
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="店铺升级">
        <div className="space-y-3">
          {(Object.keys(FACILITY_INFO) as FacilityId[]).map((f) => {
            const lv = state.facilities[f]
            const max = FACILITY_MAX[f]
            const next = lv < max ? FACILITY_INFO[f].levels[lv - 1] : null
            return (
              <div key={f} className="px-panel-inset p-2">
                <div className="flex justify-between items-center">
                  <b>{FACILITY_INFO[f].name} <span className="font-pixel">Lv{lv}</span></b>
                  {next ? (
                    <Btn variant="primary" disabled={state.gold < next.cost} onClick={() => dispatch({ type: 'UPGRADE', facility: f })}>
                      升级（{fmt(next.cost)}G）
                    </Btn>
                  ) : (
                    <span className="text-xs font-bold" style={{ color: '#6b6a3f' }}>已满级</span>
                  )}
                </div>
                {next && <div className="text-xs mt-1 opacity-80">下一级：{next.effect}</div>}
              </div>
            )
          })}
        </div>
      </Panel>

      <div className="space-y-4">
        <Panel title={`声誉等级 Lv${rl}`} right={<span className="font-pixel">{state.rep} 点</span>}>
          {rl < 5 ? (
            <>
              <Bar pct={((state.rep - REP_LEVELS[rl - 1]) / (REP_LEVELS[rl] - REP_LEVELS[rl - 1])) * 100} color="#b8860b" />
              <div className="text-xs mt-1 opacity-70">距 Lv{rl + 1} 还需 {REP_LEVELS[rl] - state.rep} 点声誉</div>
            </>
          ) : (
            <div className="text-xs" style={{ color: '#b8860b' }}>已是声名远播的传奇铁匠！</div>
          )}
          <div className="text-xs mt-2 space-y-1">
            {REP_PERKS.map((p, i) => (
              <div key={i} style={{ opacity: rl >= i + 1 ? 1 : 0.45 }}>
                {rl >= i + 1 ? '✓' : '○'} Lv{i + 1}：{p}
              </div>
            ))}
          </div>
        </Panel>

        <Panel title={`锻造等级 Lv${fl}`} right={<span className="font-pixel">{state.forgeExp} EXP</span>}>
          {fl < 7 ? (
            <>
              <Bar pct={((state.forgeExp - FORGE_LEVELS[fl - 1]) / (FORGE_LEVELS[fl] - FORGE_LEVELS[fl - 1])) * 100} color="#d9622b" />
              <div className="text-xs mt-1 opacity-70">距 Lv{fl + 1} 还需 {FORGE_LEVELS[fl] - state.forgeExp} 经验（锻造按品质 +5~80，强化 +5，分解 +2）</div>
            </>
          ) : (
            <div className="text-xs" style={{ color: '#d9622b' }}>锻造技艺已登峰造极！</div>
          )}
        </Panel>
      </div>
    </div>
  )
}
