import { useState } from 'react'
import { GameProvider, useGame, loadSave, clearSave } from '@/game/state'
import { DIFFICULTIES } from '@/game/data'
import { dowryTarget, forgeLevel, repLevel, haggleLevel, stageRevenue, fmt } from '@/game/engine'
import type { Difficulty } from '@/game/types'
import { Btn } from '@/components/pixel'
import SceneModal from '@/components/SceneModal'
import Ending from '@/components/Ending'
import Forge from '@/sections/Forge'
import Shop from '@/sections/Shop'
import Market from '@/sections/Market'
import Upgrade from '@/sections/Upgrade'
import Social from '@/sections/Social'
import Log from '@/sections/Log'

type Tab = 'forge' | 'shop' | 'market' | 'upgrade' | 'social' | 'log'
const TABS: { key: Tab; name: string }[] = [
  { key: 'forge', name: '锻造' },
  { key: 'shop', name: '店铺' },
  { key: 'market', name: '市场' },
  { key: 'upgrade', name: '升级' },
  { key: 'social', name: '社交' },
  { key: 'log', name: '日志' },
]

function TitleScreen() {
  const { dispatch } = useGame()
  const [diff, setDiff] = useState<Difficulty>('normal')
  const save = loadSave()
  return (
    <div className="min-h-full flex items-center justify-center p-4">
      <div className="w-full max-w-3xl">
        <div className="px-panel overflow-hidden">
          <img src="/assets/banner.png" alt="铁匠铺" className="w-full block" style={{ borderBottom: '3px solid #141312' }} />
          <div className="p-6 text-center">
            <div className="font-pixel text-5xl mb-1" style={{ color: '#b3341f', textShadow: '2px 2px 0 #f7ecc9' }}>铁匠恋歌</div>
            <div className="text-lg font-bold mb-1" style={{ color: '#6b6a3f' }}>~ 真心之锤 ~</div>
            <p className="text-sm mb-4 opacity-80">锻造经营 × 恋爱养成 × 剧情抉择 —— 真正的彩礼不是钱，而是珍惜眼前人。</p>
            <div className="flex justify-center gap-2 mb-4 flex-wrap">
              {(Object.keys(DIFFICULTIES) as Difficulty[]).map((d) => (
                <button key={d} className={`px-btn ${diff === d ? 'px-btn-primary' : ''}`} onClick={() => setDiff(d)}>
                  {DIFFICULTIES[d].name}
                </button>
              ))}
            </div>
            <div className="text-xs mb-4 opacity-70">
              {diff === 'easy' && '材料便宜、售价更高、彩礼要求降低，小铃更容易亲近。'}
              {diff === 'normal' && '标准体验：按设计数值经营与抉择。'}
              {diff === 'hard' && '材料更贵、售价更低、彩礼 ×1.5，强化成功率 -10%。'}
              {diff === 'brutal' && '地狱难度：彩礼 ×2，售价 ×0.6，每一锤都沉重。'}
            </div>
            <div className="flex justify-center gap-3">
              <Btn variant="primary" className="text-lg px-8" onClick={() => { if (save) clearSave(); dispatch({ type: 'NEW_GAME', difficulty: diff }) }}>
                新游戏
              </Btn>
              {save && (
                <Btn variant="green" className="text-lg px-8" onClick={() => dispatch({ type: 'LOAD', state: save })}>
                  继续游戏（{DIFFICULTIES[save.difficulty].name} · {save.ngPlus + 1} 周目）
                </Btn>
              )}
            </div>
          </div>
        </div>
        <div className="text-center text-xs mt-3 opacity-60">进度自动保存在本浏览器中（localStorage），清除浏览器数据会丢失存档。</div>
      </div>
    </div>
  )
}

function HUD() {
  const { state } = useGame()
  const target = dowryTarget(state)
  return (
    <div className="px-panel mb-0">
      <div className="px-titlebar">
        <span>铁匠恋歌：真心之锤 {state.ngPlus > 0 && <span className="font-pixel text-sm">（{state.ngPlus + 1} 周目）</span>}</span>
        <span className="font-pixel text-sm">{DIFFICULTIES[state.difficulty].name}难度</span>
      </div>
      <div className="p-2 flex flex-wrap gap-x-4 gap-y-1 text-sm items-center">
        <span>金币 <b className="font-pixel text-lg" style={{ color: '#b8860b' }}>{fmt(state.gold)}</b>G</span>
        <span>总营收 <b className="font-pixel text-lg">{fmt(state.totalRevenue)}</b>G</span>
        <span>声誉 <b className="font-pixel text-lg">Lv{repLevel(state.rep)}</b></span>
        <span>锻造 <b className="font-pixel text-lg">Lv{forgeLevel(state.forgeExp)}</b></span>
        <span>议价 <b className="font-pixel text-lg">Lv{haggleLevel(state.salesCount)}</b></span>
        <span style={{ color: '#b3341f' }}>阿梅 <b className="font-pixel text-lg">{state.amei.affection}</b></span>
        <span style={{ color: '#6b6a3f' }}>小铃 <b className="font-pixel text-lg">{state.xiaoling.affection}</b></span>
        {state.fatigue.active && <span className="blink font-bold" style={{ color: '#b3341f' }}>【心累中】</span>}
        {target && !state.ending && state.amei.stage > 0 && (
          <span className="px-1 font-bold" style={{ background: '#141312', color: '#fff1be' }}>
            彩礼目标：{target.label}（总营收 {fmt(state.totalRevenue)} / {fmt(stageRevenue(state.amei.stage, state.difficulty))}G）
          </span>
        )}
      </div>
    </div>
  )
}

function Shell() {
  const { state } = useGame()
  const [tab, setTab] = useState<Tab>('forge')
  if (!state || !state.started) return <TitleScreen />
  return (
    <div className="min-h-full pb-10">
      <div className="max-w-6xl mx-auto p-3">
        <div className="px-panel mb-3 overflow-hidden">
          <img src="/assets/banner.png" alt="" className="w-full block" style={{ height: 110, objectFit: 'cover', objectPosition: 'center 40%' }} />
        </div>
        <HUD />
        <div className="flex gap-1 mt-4 flex-wrap">
          {TABS.map((t) => (
            <button key={t.key} className={`px-tab ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
              {t.name}
              {t.key === 'social' && (state.pendingHint || (state.xiaoling.affection >= 80 && !state.xiaoling.evConfess)) && (
                <span className="blink ml-1" style={{ color: '#b3341f' }}>❗</span>
              )}
            </button>
          ))}
        </div>
        <div className="mt-0">
          {tab === 'forge' && <Forge />}
          {tab === 'shop' && <Shop />}
          {tab === 'market' && <Market />}
          {tab === 'upgrade' && <Upgrade />}
          {tab === 'social' && <Social />}
          {tab === 'log' && <Log />}
        </div>
      </div>
      <SceneModal />
      <Ending />
    </div>
  )
}

export default function App() {
  return (
    <GameProvider>
      <Shell />
    </GameProvider>
  )
}
