import { useGame } from '@/game/state'
import { ENDINGS } from '@/game/data'
import { fmt } from '@/game/engine'
import { Btn } from './pixel'
import { clearSave } from '@/game/state'

export default function Ending() {
  const { state, dispatch } = useGame()
  if (!state.ending) return null
  const e = ENDINGS[state.ending]
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ background: 'rgba(20,19,18,0.82)' }}>
      <div className="px-panel w-full max-w-2xl">
        <div className="px-titlebar"><span>结局</span><span className="font-pixel">第 {state.ngPlus + 1} 周目</span></div>
        <div className="p-6 text-center">
          <div className="font-pixel text-4xl mb-1" style={{ color: '#b3341f' }}>{e.title}</div>
          <div className="text-sm mb-4" style={{ color: '#6b6a3f' }}>—— {e.subtitle} ——</div>
          <p className="leading-loose text-left mb-4" style={{ textIndent: '2em' }}>{e.desc}</p>
          <div className="px-panel-inset p-3 text-sm grid grid-cols-2 gap-1 text-left mb-4">
            <span>总营收：<b className="font-pixel">{fmt(state.totalRevenue)}G</b></span>
            <span>剩余金币：<b className="font-pixel">{fmt(state.gold)}G</b></span>
            <span>阿梅好感：<b className="font-pixel">{state.amei.affection}</b></span>
            <span>小铃好感：<b className="font-pixel">{state.xiaoling.affection}</b></span>
            <span>声誉：<b className="font-pixel">{state.rep}</b></span>
            <span>锻造等级：<b className="font-pixel">Lv{Math.min(7, 1 + [0, 100, 300, 800, 1500, 2500, 4000].filter((x) => state.forgeExp >= x).length - 1)}</b></span>
          </div>
          <div className="flex gap-2 justify-center flex-wrap">
            <Btn variant="primary" onClick={() => dispatch({ type: 'NG_PLUS' })}>
              进入二周目（继承部分积累）
            </Btn>
            <Btn onClick={() => { clearSave(); window.location.reload() }}>回到标题</Btn>
          </div>
          <div className="text-xs mt-3 opacity-60">二周目将继承：锻造等级、已领悟配方、部分金币、部分店铺升级，小铃的初始好感也会更高。</div>
        </div>
      </div>
    </div>
  )
}
