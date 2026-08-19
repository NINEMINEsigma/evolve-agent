import { useEffect, useRef, useState } from 'react'
import { useGame } from '@/game/state'
import { MAIN_MATS, SUB_MATS, WEAPON_TYPES, QUALITIES } from '@/game/data'
import { unlockedRecipes, fuelNeeded, qualityOf, capQuality, anvilQualityCap, fmt } from '@/game/engine'
import type { Recipe, SubMat } from '@/game/types'
import { Panel, Btn, QualityTag } from '@/components/pixel'

type Phase = 'idle' | 'heat' | 'hammer' | 'quench' | 'done'

interface QTEResult {
  completion: number
  allPerfect: boolean
  scores: number[]
}

// 三阶段 QTE：加热 → 锤打 ×3 → 淬火
export function QTEPanel({ modifier, onFinish }: { modifier: number; onFinish: (r: QTEResult) => void }) {
  const [phase, setPhase] = useState<Phase>('heat')
  const [pos, setPos] = useState(0) // 0~100
  const [dir, setDir] = useState(1)
  const [strike, setStrike] = useState(0)
  const [scores, setScores] = useState<number[]>([])
  const [flash, setFlash] = useState<string | null>(null)
  const posRef = useRef(0)
  posRef.current = pos

  const speed = phase === 'heat' ? 1.6 : phase === 'hammer' ? 3.2 : 2.0

  useEffect(() => {
    if (phase === 'done' || phase === 'idle') return
    const t = setInterval(() => {
      setPos((p) => {
        let np = p + speed * dir
        let nd = dir
        if (np >= 100) { np = 100; nd = -1 }
        if (np <= 0) { np = 0; nd = 1 }
        if (nd !== dir) setDir(nd)
        return np
      })
    }, 16)
    return () => clearInterval(t)
  }, [phase, dir, speed])

  const judge = (p: number): number => {
    const raw = Math.max(0, 100 - Math.abs(p - 50) * 2.4)
    return Math.min(100, Math.max(0, Math.round(raw + modifier)))
  }

  const hit = () => {
    const acc = judge(posRef.current)
    setFlash(acc >= 98 ? '完美！' : acc >= 80 ? '很好' : acc >= 55 ? '一般' : '失手…')
    setTimeout(() => setFlash(null), 500)
    if (phase === 'heat') {
      setScores([acc]); setPhase('hammer'); setStrike(0); setPos(0)
    } else if (phase === 'hammer') {
      const ns = [...scores, acc]
      setScores(ns)
      if (strike >= 2) { setPhase('quench'); setPos(0) }
      else { setStrike(strike + 1); setPos(0) }
    } else if (phase === 'quench') {
      const final = [...scores, acc]
      const completion = Math.round(final.reduce((a, b) => a + b, 0) / final.length)
      const allPerfect = final.every((x) => x >= 98)
      setPhase('done')
      setTimeout(() => onFinish({ completion, allPerfect, scores: final }), 400)
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Space' || e.code === 'Enter') { e.preventDefault(); hit() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const phaseName = phase === 'heat' ? '① 加热：在针尖落入橙区时按下！' : phase === 'hammer' ? `② 锤打（第 ${strike + 1}/3 锤）` : '③ 淬火：看准时机！'

  return (
    <div className="px-panel-inset p-4">
      <div className="text-center font-bold mb-2">{phaseName}</div>
      <div className="qte-track mb-1">
        <div className="qte-zone-good" style={{ left: '29%', width: '42%' }} />
        <div className="qte-zone-perfect" style={{ left: '45.5%', width: '9%' }} />
        <div className="qte-needle" style={{ left: `${pos}%` }} />
      </div>
      <div className="flex justify-between text-xs opacity-70 mb-3">
        <span>0</span><span>黄区=良好 · 橙区=完美</span><span>100</span>
      </div>
      <div className="text-center">
        <Btn variant="primary" className="text-lg px-10" onClick={hit}>锻 打！（空格）</Btn>
      </div>
      {flash && <div className="text-center mt-2 font-bold" style={{ color: '#b3341f' }}>{flash}</div>}
      <div className="text-center text-xs mt-2 opacity-70">
        已完成阶段评分：{scores.join(' / ') || '—'}{modifier !== 0 && `（修正 ${modifier > 0 ? '+' : ''}${modifier}）`}
      </div>
    </div>
  )
}

export default function Forge() {
  const { state, dispatch } = useGame()
  const recipes = unlockedRecipes(state)
  const [recipeId, setRecipeId] = useState<string | null>(null)
  const [sub, setSub] = useState<SubMat>('wood')
  const [forging, setForging] = useState(false)
  const [result, setResult] = useState<QTEResult | null>(null)
  const [selWeapon, setSelWeapon] = useState<number | null>(null)

  const recipe: Recipe | null = recipes.find((r) => r.id === recipeId) ?? recipes[0] ?? null
  const modifier = (state.fatigue.active ? -10 : 0) + (state.xiaoling.hasGloves ? 10 : 0)

  if (!recipe) {
    return <Panel title="锻造台"><div>暂无可用配方。</div></Panel>
  }

  const fuel = fuelNeeded(recipe.main, state)
  const canForge = state.materials[recipe.main] >= 1 && state.materials[sub] >= 1 && state.materials.coal >= fuel
  const cap = capQuality('legend', anvilQualityCap(state.facilities.anvil))

  const startForge = () => { setForging(true); setResult(null) }
  const finish = (r: QTEResult) => {
    dispatch({ type: 'FORGE', recipe, sub, completion: r.completion, allPerfect: r.allPerfect })
    setResult(r); setForging(false)
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="锻造台" right={<span className="font-pixel">铁砧 Lv{state.facilities.anvil} · 品质上限：{QUALITIES[cap].name}</span>}>
        {state.fatigue.active && (
          <div className="mb-2 px-2 py-1 text-sm font-bold" style={{ background: '#b3341f', color: '#fff7e0', border: '2px solid #141312' }}>
            【心累】QTE 判定 -10%（再锻造 {state.fatigue.forgeLeft} 次或与小铃交谈 {state.fatigue.talkLeft} 次恢复）
          </div>
        )}
        {state.xiaoling.hasGloves && (
          <div className="mb-2 px-2 py-1 text-sm" style={{ background: '#6b6a3f', color: '#fff7e0', border: '2px solid #141312' }}>
            佩戴着【小铃的护手】：QTE 判定 +10%
          </div>
        )}
        {!forging ? (
          <>
            <div className="mb-2 text-sm font-bold">选择配方：</div>
            <div className="grid grid-cols-3 gap-2 mb-3 max-h-48 overflow-y-auto pr-1">
              {recipes.map((r) => (
                <button
                  key={r.id}
                  className={`px-btn text-sm ${recipe.id === r.id ? 'px-btn-primary' : ''}`}
                  onClick={() => setRecipeId(r.id)}
                >
                  {WEAPON_TYPES[r.type].icon} {r.name}
                </button>
              ))}
            </div>
            <div className="mb-2 text-sm font-bold">选择辅材（决定词条）：</div>
            <div className="grid grid-cols-2 gap-2 mb-3">
              {(Object.keys(SUB_MATS) as SubMat[]).map((m) => (
                <button
                  key={m}
                  className={`px-btn text-sm text-left ${sub === m ? 'px-btn-green' : ''}`}
                  onClick={() => setSub(m)}
                  disabled={state.materials[m] < 1}
                >
                  {SUB_MATS[m].name} ×{state.materials[m]}
                  <div className="text-xs opacity-80">{SUB_MATS[m].affixDesc}</div>
                </button>
              ))}
            </div>
            <div className="px-panel-inset p-2 mb-3 text-sm">
              <div>需求：{MAIN_MATS[recipe.main].name} ×1（有 {state.materials[recipe.main]}）、{SUB_MATS[sub].name} ×1、燃料 ×{fuel}（有 {state.materials.coal}）</div>
              <div>基础属性：攻击 {Math.round(WEAPON_TYPES[recipe.type].atk * MAIN_MATS[recipe.main].atkMult)} / 耐久 {Math.round(WEAPON_TYPES[recipe.type].dur * MAIN_MATS[recipe.main].durMult)} / 基础售价约 {recipe && fmt(Math.round(WEAPON_TYPES[recipe.type].priceBase * MAIN_MATS[recipe.main].priceMult))}G</div>
            </div>
            <Btn variant="primary" className="w-full text-lg" disabled={!canForge} onClick={startForge}>
              {canForge ? '生火开锻！' : '材料不足'}
            </Btn>
            {result && (
              <div className="mt-3 px-panel-inset p-3 text-center relative overflow-hidden">
                {result.completion >= 75 && Array.from({ length: 10 }).map((_, i) => (
                  <div key={i} className="spark" style={{ left: '50%', top: '40%', ['--dx' as string]: `${(i - 5) * 18}px`, ['--dy' as string]: `${-30 - (i % 3) * 25}px` }} />
                ))}
                <div className="font-pixel text-2xl">完成度 {result.completion}%</div>
                <div className="font-bold" style={{ color: QUALITIES[qualityOf(result.completion, result.allPerfect)].color }}>
                  {qualityOf(result.completion, result.allPerfect) !== capQuality(qualityOf(result.completion, result.allPerfect), cap)
                    ? `（受铁砧限制降为${QUALITIES[cap].name}）`
                    : QUALITIES[qualityOf(result.completion, result.allPerfect)].name + '品质！'}
                </div>
                <div className="text-xs opacity-70">阶段评分：{result.scores.join(' / ')}{result.allPerfect && ' · 全完美！'}</div>
              </div>
            )}
          </>
        ) : (
          <QTEPanel modifier={modifier} onFinish={finish} />
        )}
      </Panel>

      <Panel title={`武器库存（${state.inventory.length}）`} right={<span className="font-pixel">心得 ×{state.insight}</span>}>
        <div className="mb-2 flex gap-2">
          <Btn variant="green" disabled={state.insight < 5} onClick={() => dispatch({ type: 'INSIGHT_UNLOCK' })}>
            用 5 心得领悟配方
          </Btn>
        </div>
        <div className="max-h-96 overflow-y-auto space-y-2 pr-1">
          {state.inventory.length === 0 && <div className="text-sm opacity-60">库存空空如也，去锻造吧。</div>}
          {state.inventory.map((w) => (
            <div key={w.id} className={`px-panel-inset p-2 cursor-pointer ${selWeapon === w.id ? 'outline outline-2 outline-[#b3341f]' : ''}`} onClick={() => setSelWeapon(selWeapon === w.id ? null : w.id)}>
              <div className="flex items-center justify-between">
                <span className="font-bold">
                  {WEAPON_TYPES[w.type].icon} {w.name}{w.enhance > 0 && <span className="font-pixel" style={{ color: '#b3341f' }}> +{w.enhance}</span>}
                </span>
                <QualityTag q={w.quality} />
              </div>
              <div className="text-xs mt-1 flex gap-3 flex-wrap">
                <span>攻击 <b className="font-pixel">{w.atk}</b></span>
                <span>耐久 <b className="font-pixel">{w.dur}</b></span>
                <span>词条：{w.affixes.join('、')}</span>
              </div>
              {selWeapon === w.id && (
                <div className="mt-2 flex gap-2 items-center flex-wrap" onClick={(e) => e.stopPropagation()}>
                  <Btn
                    disabled={w.enhance >= 5 || state.materials.enhanceOre < (w.enhance < 2 ? 1 : w.enhance < 4 ? 2 : 3)}
                    onClick={() => dispatch({ type: 'ENHANCE', weaponId: w.id })}
                    title="成功：攻击+5%、售价+15%；失败仅消耗矿石"
                  >
                    强化 +{w.enhance + 1}（矿石×{w.enhance < 2 ? 1 : w.enhance < 4 ? 2 : 3}）
                  </Btn>
                  <Btn variant="danger" onClick={() => { dispatch({ type: 'DECOMPOSE', weaponId: w.id }); setSelWeapon(null) }}>分解</Btn>
                </div>
              )}
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}
