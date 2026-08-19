import { useGame } from '@/game/state'
import { AMEI_STAGES, DIFFICULTIES } from '@/game/data'
import { dowryTarget, stageAmount, stageRevenue, fmt } from '@/game/engine'
import { Panel, Btn, Bar } from '@/components/pixel'

function HeartBar({ value, color }: { value: number; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <Bar pct={Math.min(100, value)} color={color} />
      <span className="font-pixel text-lg w-10 text-right">{value}</span>
    </div>
  )
}

export default function Social() {
  const { state, dispatch } = useGame()
  const target = dowryTarget(state)
  const x = state.xiaoling
  const events = [
    x.evHelp && '小铃开始来店里帮忙',
    x.evAnvil && '小铃替你护住了祖传铁砧',
    x.evSick && '探望生病的小铃，获得护手',
    x.evDowry && '小铃想卖掉嫁妆帮你',
    x.evConfess && '小铃的心意',
  ].filter(Boolean) as string[]

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* 阿梅 */}
      <Panel title="阿梅 · 青梅竹马" right={state.pendingHint ? <span className="blink font-pixel" style={{ color: '#ffd27d' }}>❗ 她有话要说</span> : undefined}>
        <div className="flex gap-3">
          <img src="/assets/amei.png" alt="阿梅" className="w-28 h-28 object-cover" style={{ border: '3px solid #141312' }} />
          <div className="flex-1">
            <div className="text-xs mb-1 opacity-70">好感度</div>
            <HeartBar value={state.amei.affection} color="#b3341f" />
            <div className="mt-2 text-sm">
              {state.ending ? '——' : (
                <>
                  <div>已答应的要求：<b>{state.amei.stage}</b> / 5</div>
                  {target && state.amei.stage < 5 && (
                    <div className="mt-1">
                      当前目标：【{target.label}】{state.amei.stage === 0 ? '' : ` +${fmt(stageAmount(state.amei.stage, state.difficulty))}G`}
                      <div className="text-xs opacity-70">
                        总营收达到 {fmt(stageRevenue(state.amei.stage, state.difficulty))}G 后她会来谈这件事
                        {target.met && <span className="blink" style={{ color: '#b3341f' }}>（已达成，去对话！）</span>}
                      </div>
                    </div>
                  )}
                  {state.amei.stage >= 5 && !state.ending && (
                    <div className="mt-1 text-xs" style={{ color: '#b3341f' }}>
                      所有要求都已答应。总营收达到 {fmt(stageRevenue(5, state.difficulty))}G 后，将迎来最终时刻……
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
        {!state.ending && (
          <div className="flex gap-2 mt-3 flex-wrap">
            <Btn variant="danger" disabled={!state.socialCharge && !state.pendingHint} onClick={() => dispatch({ type: 'AMEI_TALK' })}>
              与阿梅交谈
            </Btn>
            <Btn disabled={state.gold < 500} onClick={() => dispatch({ type: 'AMEI_GIFT' })}>送昂贵礼物（500G，好感+5）</Btn>
          </div>
        )}
        <div className="text-xs mt-2 opacity-60">满足她的要求 +10 好感，但每一次加码都会让你【心累】。拒绝则 -15。</div>
      </Panel>

      {/* 小铃 */}
      <Panel title="小铃 · 邻家小妹">
        <div className="flex gap-3">
          <img src="/assets/xiaoling.png" alt="小铃" className="w-28 h-28 object-cover" style={{ border: '3px solid #141312' }} />
          <div className="flex-1">
            <div className="text-xs mb-1 opacity-70">好感度{x.affection >= 80 && !x.evConfess && '（她似乎想对你说什么……）'}</div>
            <HeartBar value={x.affection} color="#6b6a3f" />
            <div className="mt-2 text-sm space-y-1">
              <div>{x.helpUnlocked ? '✓ 市场砍价与委托已解锁' : '好感 ≥10 且声誉 ≥20 后她会来店里帮忙'}</div>
              <div>{x.hasGloves ? '✓ 佩戴着小铃的护手（QTE +10%）' : ''}</div>
            </div>
          </div>
        </div>
        {!state.ending && (
          <div className="flex gap-2 mt-3 flex-wrap">
            <Btn variant="green" disabled={!state.socialCharge} onClick={() => dispatch({ type: 'XIAO_TALK' })}>闲聊（好感+1）</Btn>
            <Btn disabled={!state.socialCharge || state.gold < 100} onClick={() => dispatch({ type: 'XIAO_FLOWER' })}>送花（100G，好感+5）</Btn>
            <Btn disabled={!x.helpUnlocked} onClick={() => dispatch({ type: 'XIAO_QUEST' })} title="送她一件普通品质以上的武器">完成她的委托（好感+8）</Btn>
          </div>
        )}
        <div className="text-xs mt-2 opacity-60">
          交谈/送礼需要精力——每完成一笔交易或一次锻造后可再次互动。
          {DIFFICULTIES[state.difficulty].xiaoMult !== 1 && `（难度修正 ×${DIFFICULTIES[state.difficulty].xiaoMult}）`}
        </div>
        {events.length > 0 && (
          <div className="mt-3 px-panel-inset p-2">
            <div className="text-xs font-bold mb-1">共同经历：</div>
            {events.map((e, i) => <div key={i} className="text-xs">· {e}</div>)}
          </div>
        )}
      </Panel>
    </div>
  )
}

export { AMEI_STAGES }
