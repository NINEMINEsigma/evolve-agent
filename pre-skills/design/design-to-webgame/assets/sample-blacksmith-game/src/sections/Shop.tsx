import { useState } from 'react'
import { useGame } from '@/game/state'
import { WEAPON_TYPES, QUALITIES, MATERIAL_NAMES, CUSTOMER_KINDS } from '@/game/data'
import { weaponPrice, fmt } from '@/game/engine'
import type { Customer, Weapon } from '@/game/types'
import { Panel, Btn } from '@/components/pixel'
import { QTEPanel } from './Forge'

function SellBox({ customer, weapons }: { customer: Customer; weapons: Weapon[] }) {
  const { state, dispatch } = useGame()
  const matched = weapons.filter((w) => w.type === customer.wantType)
  const [wid, setWid] = useState<number | null>(matched[0]?.id ?? null)
  const w = matched.find((x) => x.id === wid)
  const suggested = w ? weaponPrice(w, state) : 0
  const [ask, setAsk] = useState<number>(0)
  const askVal = ask || suggested
  return (
    <div className="mt-2">
      {matched.length === 0 ? (
        <div className="text-xs" style={{ color: '#b3341f' }}>库存中没有{WEAPON_TYPES[customer.wantType].name}。</div>
      ) : (
        <>
          <select
            className="px-panel-inset px-2 py-1 text-sm w-full mb-1"
            value={wid ?? ''}
            onChange={(e) => { setWid(Number(e.target.value)); setAsk(0) }}
          >
            {matched.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}{x.enhance ? ` +${x.enhance}` : ''}（{QUALITIES[x.quality].name} 攻{x.atk}）
              </option>
            ))}
          </select>
          {w && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs">报价</span>
              <input
                type="range" min={Math.round(suggested * 0.6)} max={Math.round(suggested * 1.5)}
                value={askVal} onChange={(e) => setAsk(Number(e.target.value))}
                className="flex-1"
              />
              <span className="font-pixel text-lg">{fmt(askVal)}G</span>
              <Btn variant="primary" onClick={() => { dispatch({ type: 'SELL', customerId: customer.id, weaponId: w.id, ask: askVal }); setAsk(0) }}>
                成交
              </Btn>
            </div>
          )}
          <div className="text-xs opacity-70 mt-1">
            参考价 {fmt(suggested)}G / 对方预算约 {fmt(customer.budget)}G（超预算 15% 内有机会砍价成交；品质达{QUALITIES[customer.minQuality].name}有小费）
          </div>
        </>
      )}
    </div>
  )
}

export default function Shop() {
  const { state, dispatch } = useGame()
  const [fulfillSel, setFulfillSel] = useState<Record<number, number>>({})
  const [contestQTE, setContestQTE] = useState(false)
  const [contestDone, setContestDone] = useState<number | null>(null)
  const contestModifier = (state.fatigue.active ? -10 : 0) + (state.xiaoling.hasGloves ? 10 : 0)

  return (
    <div className="space-y-4">
      <Panel
        title="店铺营业"
        right={<span className="font-pixel">热度 ×{state.marketHeat.toFixed(2)}</span>}
      >
        <div className="flex gap-2 flex-wrap mb-3">
          <Btn variant="primary" onClick={() => dispatch({ type: 'OPEN_SHOP' })}>开门迎客 / 换一批客人</Btn>
          <Btn disabled={state.gold < 200 || state.stallNext} onClick={() => dispatch({ type: 'STALL' })} title="摊位费 200G，下批顾客翻倍">
            集市摆摊（200G）{state.stallNext && '✓'}
          </Btn>
          <Btn
            variant="green"
            disabled={state.rep < 80 || state.gold < 100}
            onClick={() => { setContestQTE(true); setContestDone(null) }}
            title={state.rep < 80 ? '声誉 ≥80 解锁' : '报名费 100G，冠军 5000G · 亚军 2000G · 季军 1000G'}
          >
            铁匠大赛（100G）
          </Btn>
        </div>

        {contestQTE && (
          <div className="px-panel p-3 mb-3">
            <div className="font-bold mb-2 text-center">【铁匠大赛】现场锻造一把作品，评委按完成度打分！（98+ 冠军 / 90+ 亚军 / 75+ 季军）</div>
            {contestDone === null ? (
              <QTEPanel modifier={contestModifier} onFinish={(r) => { dispatch({ type: 'CONTEST', completion: r.completion }); setContestDone(r.completion) }} />
            ) : (
              <div className="text-center">
                <div className="font-pixel text-2xl">完成度 {contestDone}%</div>
                <div className="font-bold mb-2">{contestDone >= 98 ? '冠军！奖金 5,000G！' : contestDone >= 90 ? '亚军！奖金 2,000G！' : contestDone >= 75 ? '季军！奖金 1,000G！' : '遗憾落选……'}</div>
                <Btn onClick={() => setContestQTE(false)}>离开赛场</Btn>
              </div>
            )}
          </div>
        )}

        {state.customers.length === 0 ? (
          <div className="text-sm opacity-60">铺子还没有客人，点击「开门迎客」。</div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {state.customers.map((c) => (
              <div key={c.id} className="px-panel-inset p-2">
                <div className="flex justify-between items-start">
                  <b>{c.name}</b>
                  <span className="text-xs px-1" style={{ border: '2px solid #141312', background: '#e9dcae' }}>
                    {CUSTOMER_KINDS[c.kind].name}
                  </span>
                </div>
                <div className="text-xs my-1">{c.desc}</div>
                {c.mode === 'buy' && <SellBox customer={c} weapons={state.inventory} />}
                {c.mode === 'order' && (
                  <Btn className="mt-1" disabled={state.orders.length >= 3} onClick={() => dispatch({ type: 'ACCEPT_ORDER', customerId: c.id })}>
                    接受订单（{state.orders.length}/3）
                  </Btn>
                )}
                {c.mode === 'repair' && (
                  <div className="flex gap-2 mt-1">
                    <Btn variant="green" onClick={() => dispatch({ type: 'REPAIR', customerId: c.id, free: true })}>免费修理（声誉+1）</Btn>
                    <Btn onClick={() => dispatch({ type: 'REPAIR', customerId: c.id, free: false })}>收费修理</Btn>
                  </div>
                )}
                {c.mode === 'barter' && (
                  <BarterBox customer={c} weapons={state.inventory} />
                )}
                <button className="text-xs underline opacity-50 mt-1" onClick={() => dispatch({ type: 'DISMISS', customerId: c.id })}>送客</button>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={`当前订单（${state.orders.length}/3）`}>
        {state.orders.length === 0 && <div className="text-sm opacity-60">暂无订单。无交货期限，取消订单会扣声誉。</div>}
        <div className="space-y-2">
          {state.orders.map((o) => {
            const candidates = state.inventory.filter(
              (w) => (!o.wantType || w.type === o.wantType) && w.atk >= o.minAtk && QUALITIES[w.quality].coef >= QUALITIES[o.minQuality].coef,
            )
            const sel = fulfillSel[o.id]
            return (
              <div key={o.id} className="px-panel-inset p-2">
                <div className="text-sm"><b>{o.customerName}</b>：{o.desc}</div>
                <div className="flex gap-2 mt-1 items-center flex-wrap">
                  <select
                    className="px-panel-inset px-2 py-1 text-sm"
                    value={sel ?? ''}
                    onChange={(e) => setFulfillSel({ ...fulfillSel, [o.id]: Number(e.target.value) })}
                  >
                    <option value="">选择交付武器…</option>
                    {candidates.map((w) => (
                      <option key={w.id} value={w.id}>
                        {w.name}（{QUALITIES[w.quality].name} 攻{w.atk}{o.wantAffix && !w.affixes.includes(o.wantAffix) ? ' · 无所需词条,无小费' : ''}）
                      </option>
                    ))}
                  </select>
                  <Btn variant="primary" disabled={!sel} onClick={() => dispatch({ type: 'FULFILL_ORDER', orderId: o.id, weaponId: sel })}>交付</Btn>
                  <Btn variant="danger" onClick={() => dispatch({ type: 'CANCEL_ORDER', orderId: o.id })}>取消</Btn>
                </div>
              </div>
            )
          })}
        </div>
      </Panel>
    </div>
  )
}

function BarterBox({ customer, weapons }: { customer: Customer; weapons: Weapon[] }) {
  const { dispatch } = useGame()
  const matched = weapons.filter((w) => w.type === customer.wantType && w.quality !== 'crude')
  const [wid, setWid] = useState<number | null>(null)
  return (
    <div className="mt-1 flex gap-2 items-center flex-wrap">
      {matched.length === 0 ? (
        <span className="text-xs" style={{ color: '#b3341f' }}>库存中没有符合要求的{WEAPON_TYPES[customer.wantType].name}。</span>
      ) : (
        <>
          <select className="px-panel-inset px-2 py-1 text-sm" value={wid ?? ''} onChange={(e) => setWid(Number(e.target.value))}>
            <option value="">选择交换的武器…</option>
            {matched.map((w) => (
              <option key={w.id} value={w.id}>{w.name}（{QUALITIES[w.quality].name}）</option>
            ))}
          </select>
          <Btn disabled={!wid} onClick={() => wid && dispatch({ type: 'BARTER', customerId: customer.id, weaponId: wid })}>
            换 {customer.barterQty} 个{MATERIAL_NAMES[customer.barterMat!]}
          </Btn>
        </>
      )}
    </div>
  )
}
