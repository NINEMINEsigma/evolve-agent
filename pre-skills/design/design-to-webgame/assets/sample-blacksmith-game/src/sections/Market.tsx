import { useState } from 'react'
import { useGame } from '@/game/state'
import { SHOP_STOCK, MATERIAL_NAMES } from '@/game/data'
import { materialPrice, merchantPrice, storageCap, materialCount, repLevel, fmt } from '@/game/engine'
import type { MaterialId } from '@/game/types'
import { Panel, Btn, Bar } from '@/components/pixel'

function BuyRow({ mat, price, stock }: { mat: MaterialId; price: number; stock: number }) {
  const { state, dispatch } = useGame()
  const [qty, setQty] = useState(1)
  const bargain = !state.bargainUsed && state.xiaoling.helpUnlocked && state.xiaoling.affection >= 30
  const finalPrice = Math.round(price * (bargain ? 0.8 : 1))
  const total = finalPrice * qty
  return (
    <div className="flex items-center gap-2 py-1 border-b border-dashed border-[#b2a574] text-sm flex-wrap">
      <span className="w-24 font-bold">{MATERIAL_NAMES[mat]}</span>
      <span className="text-xs opacity-70">持有 {state.materials[mat]}</span>
      <span className="font-pixel">{fmt(finalPrice)}G{bargain && <span className="text-xs" style={{ color: '#6b6a3f' }}>（-20%）</span>}</span>
      <input type="range" min={1} max={Math.max(1, Math.min(stock, 20))} value={qty} onChange={(e) => setQty(Number(e.target.value))} className="w-20" />
      <span className="font-pixel">×{qty}</span>
      <Btn
        className="text-xs px-2 py-1"
        disabled={total > state.gold || qty > stock || materialCount(state) + qty > storageCap(state)}
        onClick={() => dispatch({ type: 'BUY', mat, qty, source: stock === 999 ? 'shop' : 'merchant' })}
      >
        买（{fmt(total)}G）
      </Btn>
    </div>
  )
}

export default function Market() {
  const { state, dispatch } = useGame()
  const used = materialCount(state)
  const cap = storageCap(state)
  const canBargain = state.xiaoling.helpUnlocked && state.xiaoling.affection >= 30
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel
        title="村口杂货铺"
        right={canBargain && !state.bargainUsed ? <span className="text-xs blink" style={{ color: '#ffd27d' }}>小铃砍价可用！</span> : undefined}
      >
        <div className="text-xs mb-2 opacity-70">
          {canBargain
            ? state.bargainUsed ? '本次砍价已用掉啦，下次开门再来。' : '小铃在店里帮忙：本批采购首单自动 -20%！'
            : '小铃好感 ≥30 且解锁帮忙后，可在采购时砍价 -20%。'}
        </div>
        {SHOP_STOCK.map((m) => (
          <BuyRow key={m} mat={m} price={materialPrice(m, state)} stock={999} />
        ))}
        <div className="mt-3">
          <div className="text-xs mb-1">仓库占用 {used} / {cap}</div>
          <Bar pct={(used / cap) * 100} color={used / cap > 0.9 ? '#b3341f' : '#6b6a3f'} />
        </div>
      </Panel>

      <div className="space-y-4">
        <Panel title="流动行商" right={state.merchantStock ? <span className="font-pixel">今日价 ×{state.merchantPriceMult.toFixed(2)}</span> : undefined}>
          {state.merchantStock && Object.values(state.merchantStock).some((v) => (v ?? 0) > 0) ? (
            <>
              <div className="text-xs mb-2 opacity-70">稀有材料，价格波动大。换一批客人后行商可能离开。</div>
              {(Object.entries(state.merchantStock) as [MaterialId, number][])
                .filter(([, v]) => v > 0)
                .map(([m, v]) => (
                  <BuyRow key={m} mat={m} price={merchantPrice(m, state)} stock={v} />
                ))}
            </>
          ) : (
            <div className="text-sm opacity-60">行商今天不在村里。开门迎客时他偶尔会带来秘银、魔矿石、魔核等稀有货。</div>
          )}
        </Panel>

        <Panel title="铁匠行会供应商">
          {state.guildMember ? (
            <div className="text-sm">已是行会会员：所有材料采购永久 <b style={{ color: '#b3341f' }}>-10%</b>。</div>
          ) : (
            <>
              <div className="text-sm mb-2">缴纳 2,000G 押金成为会员，材料采购永久 -10%。（需声誉等级 4）</div>
              <Btn disabled={repLevel(state.rep) < 4 || state.gold < 2000} onClick={() => dispatch({ type: 'GUILD_JOIN' })}>
                缴纳押金入会（2,000G）
              </Btn>
            </>
          )}
        </Panel>
      </div>
    </div>
  )
}
