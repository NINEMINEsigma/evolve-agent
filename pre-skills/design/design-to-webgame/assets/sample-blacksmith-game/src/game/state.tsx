import React, { createContext, useContext, useEffect, useReducer } from 'react'
import type { GameState, MaterialId, Recipe, Scene, SubMat } from './types'
import {
  DIFFICULTIES, ENHANCE_TABLE, QUALITIES, FACILITY_INFO, FACILITY_MAX, AMEI_STAGES,
  MAIN_MATS,
} from './data'
import {
  forgeLevel, repLevel, generateCustomers, makeOrder, makeWeapon, materialPrice,
  merchantPrice, storageCap, materialCount, fuelNeeded, stageRevenue, contestResult, resolveEnding,
  nextLockedRecipe, rand, randInt, fmt,
} from './engine'
import {
  sceneIntro, sceneAmeiStage, sceneAmeiFinal, sceneXiaolingHelp, sceneXiaolingAnvil,
  sceneXiaolingSick, sceneXiaolingDowry, sceneXiaolingConfess,
  sceneAmeiSmalltalk, sceneXiaoSmalltalk, sceneAmeiGift, sceneXiaoFlower, sceneXiaoQuest,
} from './scenes'

export type Action =
  | { type: 'NEW_GAME'; difficulty: GameState['difficulty']; inherit?: GameState }
  | { type: 'LOAD'; state: GameState }
  | { type: 'OPEN_SHOP' }
  | { type: 'BUY'; mat: MaterialId; qty: number; source: 'shop' | 'merchant' }
  | { type: 'ARM_BARGAIN' }
  | { type: 'FORGE'; recipe: Recipe; sub: SubMat; completion: number; allPerfect: boolean }
  | { type: 'ENHANCE'; weaponId: number }
  | { type: 'DECOMPOSE'; weaponId: number }
  | { type: 'INSIGHT_UNLOCK' }
  | { type: 'SELL'; customerId: number; weaponId: number; ask: number }
  | { type: 'ACCEPT_ORDER'; customerId: number }
  | { type: 'FULFILL_ORDER'; orderId: number; weaponId: number }
  | { type: 'CANCEL_ORDER'; orderId: number }
  | { type: 'REPAIR'; customerId: number; free: boolean }
  | { type: 'BARTER'; customerId: number; weaponId: number }
  | { type: 'DISMISS'; customerId: number }
  | { type: 'UPGRADE'; facility: keyof GameState['facilities'] }
  | { type: 'GUILD_JOIN' }
  | { type: 'STALL' }
  | { type: 'CONTEST'; completion: number }
  | { type: 'AMEI_TALK' }
  | { type: 'AMEI_GIFT' }
  | { type: 'XIAO_TALK' }
  | { type: 'XIAO_FLOWER' }
  | { type: 'XIAO_QUEST' }
  | { type: 'SCENE_CHOICE'; action: import('./types').SceneAction }
  | { type: 'CLOSE_SCENE' }
  | { type: 'NG_PLUS' }

const SAVE_KEY = 'blacksmith_love_save_v1'

export function initialState(difficulty: GameState['difficulty'], ngPlus = 0): GameState {
  return {
    started: true, difficulty, ngPlus,
    gold: 200, totalRevenue: 0, rep: 0, forgeExp: 0, salesCount: 0,
    materials: { copper: 5, iron: 0, silver: 0, mithril: 0, magic: 0, wood: 3, leather: 0, fireCore: 0, iceCore: 0, thunderCore: 0, gem: 0, monster: 0, coal: 10, enhanceOre: 0 },
    inventory: [], nextWeaponId: 1,
    orders: [], nextOrderId: 1,
    customers: [], nextCustomerId: 1,
    marketHeat: 1.0, merchantStock: null, merchantPriceMult: 1, stallNext: false,
    insight: 0, insightUnlocked: [],
    facilities: { anvil: 1, shelf: 1, storage: 1, sign: 1, furnace: 1 },
    amei: { affection: 50, stage: 0, finalTriggered: false, refused: 0 },
    xiaoling: { affection: 5, helpUnlocked: false, hasGloves: false, ordersDone: 0, evHelp: false, evAnvil: false, evSick: false, evDowry: false, evConfess: false, lunchUsed: false },
    fatigue: { active: false, forgeLeft: 0, talkLeft: 0 },
    socialCharge: true, bargainUsed: false, guildMember: false, contestWins: 0,
    log: [{ text: '你继承了家里的铁匠铺。为了和青梅竹马阿梅成亲，开始了打铁攒钱的日子。', kind: 'story' }],
    scene: null, pendingScenes: [], ending: null, pendingHint: false,
  }
}

function pushScene(s: GameState, scene: Scene): GameState {
  if (s.scene) return { ...s, pendingScenes: [...s.pendingScenes, scene] }
  return { ...s, scene }
}
function addLog(s: GameState, text: string, kind: 'story' | 'system' | 'hint' = 'system'): GameState {
  return { ...s, log: [...s.log.slice(-80), { text, kind }] }
}

// 通用营收变更后的剧情检查
function checkTriggers(s0: GameState): GameState {
  let s = s0
  // 阿梅下一阶段要求可触发
  if (!s.ending && s.amei.stage < 5 && !s.amei.finalTriggered) {
    const need = stageRevenue(s.amei.stage, s.difficulty)
    if (s.totalRevenue >= need) {
      if (!s.pendingHint) {
        s = addLog({ ...s, pendingHint: true }, `阿梅似乎有话要说……（前往社交界面与她对话）`, 'hint')
      } else s = { ...s, pendingHint: true }
    }
  }
  // 阿梅最终要求（自动触发）
  if (!s.ending && s.amei.stage >= 5 && !s.amei.finalTriggered && s.totalRevenue >= stageRevenue(5, s.difficulty)) {
    s = { ...s, amei: { ...s.amei, finalTriggered: true } }
    s = pushScene(s, sceneAmeiFinal(s))
  }
  // 小铃事件
  const x = s.xiaoling
  if (!x.evHelp && x.affection >= 10 && s.rep >= 20) {
    s = { ...s, xiaoling: { ...s.xiaoling, evHelp: true, helpUnlocked: true } }
    s = pushScene(s, sceneXiaolingHelp())
    s = addLog(s, '小铃开始来店里帮忙了！', 'story')
  }
  if (!x.evAnvil && x.affection >= 30 && s.totalRevenue >= stageRevenue(1, s.difficulty)) {
    s = { ...s, xiaoling: { ...s.xiaoling, evAnvil: true } }
    s = pushScene(s, sceneXiaolingAnvil())
  }
  if (!x.evSick && x.affection >= 40 && x.ordersDone >= 5) {
    s = { ...s, xiaoling: { ...s.xiaoling, evSick: true } }
    s = pushScene(s, sceneXiaolingSick())
  }
  if (!x.evDowry && x.affection >= 60 && s.totalRevenue >= stageRevenue(3, s.difficulty)) {
    s = { ...s, xiaoling: { ...s.xiaoling, evDowry: true } }
    s = pushScene(s, sceneXiaolingDowry())
  }
  // 二周目小铃主动表白
  if (s.ngPlus >= 1 && !x.evConfess && x.affection >= 60 && s.totalRevenue >= stageRevenue(3, s.difficulty) && !s.ending) {
    s = { ...s, xiaoling: { ...s.xiaoling, evConfess: true } }
    s = pushScene(s, sceneXiaolingConfess(true))
  }
  return s
}

function repGain(s: GameState, base: number): number {
  return Math.round(base * (s.facilities.sign >= 2 ? 1.2 : 1))
}

function applyFatigueForge(s: GameState): GameState {
  if (!s.fatigue.active) return s
  const f = { ...s.fatigue, forgeLeft: s.fatigue.forgeLeft - 1 }
  if (f.forgeLeft <= 0 || f.talkLeft <= 0) {
    return addLog({ ...s, fatigue: { active: false, forgeLeft: 0, talkLeft: 0 } }, '你渐渐从疲惫中缓了过来。【心累】状态解除。', 'hint')
  }
  return { ...s, fatigue: f }
}

function endGame(s: GameState, key: string): GameState {
  const ended = { ...s, ending: key, scene: null, pendingScenes: [] }
  return addLog(ended, `【结局】达成。`, 'story')
}

export function reducer(s: GameState, a: Action): GameState {
  switch (a.type) {
    case 'NEW_GAME': {
      let st = initialState(a.difficulty, a.inherit ? a.inherit.ngPlus + 1 : 0)
      if (a.inherit) {
        const p = a.inherit
        st = {
          ...st,
          forgeExp: p.forgeExp,
          insightUnlocked: p.insightUnlocked,
          gold: Math.round(p.gold * 0.3) + 200,
          xiaoling: { ...st.xiaoling, affection: Math.min(60, 20 + Math.floor(p.xiaoling.affection / 5)) },
          facilities: {
            anvil: Math.max(1, Math.ceil(p.facilities.anvil / 2)),
            shelf: Math.max(1, Math.ceil(p.facilities.shelf / 2)),
            storage: Math.max(1, Math.ceil(p.facilities.storage / 2)),
            sign: Math.max(1, Math.ceil(p.facilities.sign / 2)),
            furnace: Math.max(1, Math.ceil(p.facilities.furnace / 2)),
          },
        }
        st = addLog(st, `【二周目】继承了前世的部分积累：锻造等级 Lv${forgeLevel(st.forgeExp)}、金币 ${fmt(st.gold)}G、部分店铺设施。这一世，小铃似乎更早地下定了决心……`, 'story')
      }
      st = { ...st, scene: sceneIntro() }
      return st
    }
    case 'LOAD':
      return { ...a.state }

    case 'OPEN_SHOP': {
      const g = generateCustomers(s)
      let ns: GameState = {
        ...s,
        customers: g.customers, nextCustomerId: s.nextCustomerId + g.customers.length,
        marketHeat: g.heat, merchantStock: g.merchant, merchantPriceMult: g.merchantMult,
        stallNext: false, socialCharge: true, bargainUsed: false,
      }
      // 小铃便当
      if (s.xiaoling.helpUnlocked && rand() < 0.3) {
        ns = addLog({ ...ns, xiaoling: { ...ns.xiaoling, affection: ns.xiaoling.affection + Math.round(3 * DIFFICULTIES[s.difficulty].xiaoMult) } }, '小铃送来了亲手做的便当。（好感 +3）', 'story')
      }
      ns = addLog(ns, `开门迎客。市场热度 ×${g.heat.toFixed(2)}，来了 ${g.customers.length} 位客人${g.merchant ? '，流动行商也进了村' : ''}。`)
      return checkTriggers(ns)
    }

    case 'BUY': {
      const pricePer = a.source === 'merchant' ? merchantPrice(a.mat, s) : materialPrice(a.mat, s)
      const discount = !s.bargainUsed && s.xiaoling.helpUnlocked && s.xiaoling.affection >= 30 ? 0.8 : 1
      const total = Math.round(pricePer * a.qty * discount)
      const stock = a.source === 'merchant' ? s.merchantStock?.[a.mat] ?? 0 : 999
      if (a.qty <= 0 || total > s.gold || a.qty > stock) return s
      if (materialCount(s) + a.qty > storageCap(s)) return addLog(s, '仓库满了，装不下更多材料。', 'hint')
      let ns: GameState = {
        ...s,
        gold: s.gold - total,
        materials: { ...s.materials, [a.mat]: s.materials[a.mat] + a.qty },
        bargainUsed: discount < 1 ? true : s.bargainUsed,
      }
      if (a.source === 'merchant' && s.merchantStock) {
        ns = { ...ns, merchantStock: { ...s.merchantStock, [a.mat]: stock - a.qty } }
      }
      return addLog(ns, `购入 ${a.qty} 个材料，花费 ${fmt(total)}G${discount < 1 ? '（小铃砍价 -20%）' : ''}。`)
    }

    case 'ARM_BARGAIN':
      return s

    case 'FORGE': {
      const r = a.recipe
      const fuel = fuelNeeded(r.main, s)
      if (s.materials[r.main] < 1 || s.materials[a.sub] < 1 || s.materials.coal < fuel) return s
      const w = makeWeapon(r.type, r.main, a.sub, a.completion, a.allPerfect, s.facilities.anvil, s.nextWeaponId)
      const exp = QUALITIES[w.quality].exp
      let ns: GameState = {
        ...s,
        materials: {
          ...s.materials,
          [r.main]: s.materials[r.main] - 1,
          [a.sub]: s.materials[a.sub] - 1,
          coal: s.materials.coal - fuel,
        },
        inventory: [...s.inventory, w],
        nextWeaponId: s.nextWeaponId + 1,
        forgeExp: s.forgeExp + exp,
        socialCharge: true,
      }
      const beforeLv = forgeLevel(s.forgeExp)
      const afterLv = forgeLevel(ns.forgeExp)
      ns = addLog(ns, `锻造完成：【${QUALITIES[w.quality].name}】${w.name}（完成度 ${a.completion}%），经验 +${exp}。`)
      if (afterLv > beforeLv) ns = addLog(ns, `锻造等级提升！当前 Lv${afterLv}，新配方已解锁。`, 'hint')
      ns = applyFatigueForge(ns)
      return checkTriggers(ns)
    }

    case 'ENHANCE': {
      const w = s.inventory.find((x) => x.id === a.weaponId)
      if (!w || w.enhance >= 5) return s
      const row = ENHANCE_TABLE[w.enhance]
      if (s.materials.enhanceOre < row.ore) return addLog(s, '强化矿石不足。', 'hint')
      const prob = row.prob + DIFFICULTIES[s.difficulty].enhanceBonus
      const ok = rand() < prob
      let ns: GameState = { ...s, materials: { ...s.materials, enhanceOre: s.materials.enhanceOre - row.ore } }
      if (ok) {
        ns = {
          ...ns,
          inventory: ns.inventory.map((x) => (x.id === a.weaponId ? { ...x, enhance: x.enhance + 1, atk: Math.round(x.atk * 1.05) } : x)),
          forgeExp: ns.forgeExp + 5,
        }
        ns = addLog(ns, `强化成功！${w.name} +${w.enhance + 1}（攻击 +5%，售价 +15%）。`)
      } else {
        ns = addLog(ns, `强化失败……${w.name} 保持 +${w.enhance}，消耗了 ${row.ore} 个强化矿石。`, 'hint')
      }
      return ns
    }

    case 'DECOMPOSE': {
      const w = s.inventory.find((x) => x.id === a.weaponId)
      if (!w) return s
      const rate = QUALITIES[w.quality].decomposeRate
      const got: string[] = []
      const mats = { ...s.materials }
      if (rand() < rate) { mats[w.main] += 1; got.push(MAIN_MATS[w.main].name) }
      if (rand() < rate) { mats[w.sub] += 1 }
      let insight = s.insight
      if (rand() < QUALITIES[w.quality].insightRate) { insight += 1; got.push('锻造心得') }
      let ns: GameState = {
        ...s, inventory: s.inventory.filter((x) => x.id !== a.weaponId),
        materials: mats, insight, forgeExp: s.forgeExp + 2,
      }
      ns = addLog(ns, `分解了 ${w.name}，回收：${got.length ? got.join('、') : '少量碎料'}。`)
      return ns
    }

    case 'INSIGHT_UNLOCK': {
      if (s.insight < 5) return s
      const r = nextLockedRecipe(s)
      if (!r) return addLog(s, '已没有可用心得解锁的配方。', 'hint')
      let ns: GameState = { ...s, insight: s.insight - 5, insightUnlocked: [...s.insightUnlocked, r.id] }
      return addLog(ns, `集齐 5 个锻造心得，领悟了新配方：${r.name}！`, 'hint')
    }

    case 'SELL': {
      const c = s.customers.find((x) => x.id === a.customerId)
      const w = s.inventory.find((x) => x.id === a.weaponId)
      if (!c || !w || c.mode !== 'buy') return s
      if (w.type !== c.wantType) return addLog(s, `${c.name}想要的是其他类型的武器。`, 'hint')
      let accept = a.ask <= c.budget
      if (!accept && a.ask <= c.budget * 1.15) accept = rand() < 0.5
      if (!accept) {
        const ns = { ...s, customers: s.customers.filter((x) => x.id !== c.id) }
        return addLog(ns, `${c.name}嫌报价 ${fmt(a.ask)}G 太贵，摇摇头走了。`, 'hint')
      }
      let tip = 0
      if (QUALITIES[w.quality].coef >= QUALITIES[c.minQuality].coef) tip = Math.round(a.ask * randInt(10, 25) / 100)
      const gain = a.ask + tip
      const repBase = QUALITIES[w.quality].rep
      let ns: GameState = {
        ...s,
        gold: s.gold + gain, totalRevenue: s.totalRevenue + gain,
        inventory: s.inventory.filter((x) => x.id !== w.id),
        customers: s.customers.filter((x) => x.id !== c.id),
        salesCount: s.salesCount + 1,
        rep: s.rep + repGain(s, repBase),
        socialCharge: true,
      }
      ns = addLog(ns, `成交！${c.name}以 ${fmt(a.ask)}G 买下 ${w.name}${tip ? `，另付小费 ${fmt(tip)}G` : ''}。${repBase ? `声誉 +${repGain(s, repBase)}。` : ''}`)
      return checkTriggers(ns)
    }

    case 'ACCEPT_ORDER': {
      const c = s.customers.find((x) => x.id === a.customerId)
      if (!c || c.mode !== 'order' || !c.order) return s
      if (s.orders.length >= 3) return addLog(s, '最多同时接 3 个订单。', 'hint')
      const order = makeOrder(s, c.order)
      let ns: GameState = {
        ...s, orders: [...s.orders, order], nextOrderId: s.nextOrderId + 1,
        customers: s.customers.filter((x) => x.id !== c.id),
      }
      return addLog(ns, `接受了${c.name}的订单：${order.desc}`)
    }

    case 'FULFILL_ORDER': {
      const o = s.orders.find((x) => x.id === a.orderId)
      const w = s.inventory.find((x) => x.id === a.weaponId)
      if (!o || !w) return s
      if (o.wantType && w.type !== o.wantType) return addLog(s, '武器类型不符合订单要求。', 'hint')
      if (w.atk < o.minAtk) return addLog(s, `攻击力不足（需要 ≥${o.minAtk}）。`, 'hint')
      const qualityOk = QUALITIES[w.quality].coef >= QUALITIES[o.minQuality].coef
      if (!qualityOk) return addLog(s, `品质未达标（需要${QUALITIES[o.minQuality].name}以上）。`, 'hint')
      const affixOk = !o.wantAffix || w.affixes.includes(o.wantAffix)
      const tip = affixOk ? Math.round((o.reward * o.tipPct) / 100) : 0
      const gain = o.reward + tip
      const repBase = o.kind === 'villager' ? 2 : o.kind === 'adventurer' ? 4 : o.kind === 'noble' ? 7 : 10
      let ns: GameState = {
        ...s,
        gold: s.gold + gain, totalRevenue: s.totalRevenue + gain,
        inventory: s.inventory.filter((x) => x.id !== w.id),
        orders: s.orders.filter((x) => x.id !== o.id),
        rep: s.rep + repGain(s, repBase),
        salesCount: s.salesCount + 1,
        socialCharge: true,
        xiaoling: { ...s.xiaoling, ordersDone: s.xiaoling.ordersDone + 1, affection: o.fromXiaoling ? s.xiaoling.affection + Math.round(8 * DIFFICULTIES[s.difficulty].xiaoMult) : s.xiaoling.affection },
      }
      ns = addLog(ns, `订单完成！获得报酬 ${fmt(o.reward)}G${tip ? ` + 小费 ${fmt(tip)}G` : ''}，声誉 +${repGain(s, repBase)}。${o.fromXiaoling ? '小铃好感 +8。' : ''}`)
      return checkTriggers(ns)
    }

    case 'CANCEL_ORDER': {
      const o = s.orders.find((x) => x.id === a.orderId)
      if (!o) return s
      const loss = randInt(5, 20)
      let ns: GameState = { ...s, orders: s.orders.filter((x) => x.id !== o.id), rep: Math.max(0, s.rep - loss) }
      return addLog(ns, `取消了${o.customerName}的订单，声誉 -${loss}。`, 'hint')
    }

    case 'REPAIR': {
      const c = s.customers.find((x) => x.id === a.customerId)
      if (!c || c.mode !== 'repair') return s
      let ns: GameState = { ...s, customers: s.customers.filter((x) => x.id !== c.id), socialCharge: true }
      if (a.free) {
        ns = { ...ns, rep: ns.rep + repGain(s, 1) }
        ns = addLog(ns, `免费帮${c.name}修好了农具，声誉 +1。`)
      } else {
        const fee = randInt(20, 50)
        ns = { ...ns, gold: ns.gold + fee, totalRevenue: ns.totalRevenue + fee }
        ns = addLog(ns, `帮${c.name}修好了农具，收取 ${fee}G 工钱。`)
      }
      return checkTriggers(ns)
    }

    case 'BARTER': {
      const c = s.customers.find((x) => x.id === a.customerId)
      const w = s.inventory.find((x) => x.id === a.weaponId)
      if (!c || !w || c.mode !== 'barter' || !c.barterMat || !c.barterQty) return s
      if (w.type !== c.wantType || w.quality === 'crude') return addLog(s, '对方对这件武器不满意。', 'hint')
      let ns: GameState = {
        ...s,
        inventory: s.inventory.filter((x) => x.id !== w.id),
        customers: s.customers.filter((x) => x.id !== c.id),
        materials: { ...s.materials, [c.barterMat]: s.materials[c.barterMat] + c.barterQty },
        salesCount: s.salesCount + 1,
        socialCharge: true,
      }
      return addLog(ns, `以物易物：用 ${w.name} 换来了 ${c.barterQty} 个材料。`)
    }

    case 'DISMISS':
      return { ...s, customers: s.customers.filter((x) => x.id !== a.customerId) }

    case 'UPGRADE': {
      const cur = s.facilities[a.facility]
      const max = FACILITY_MAX[a.facility]
      if (cur >= max) return s
      const cost = FACILITY_INFO[a.facility].levels[cur - 1].cost
      if (s.gold < cost) return addLog(s, '金币不足，无法升级。', 'hint')
      let ns: GameState = { ...s, gold: s.gold - cost, facilities: { ...s.facilities, [a.facility]: cur + 1 } }
      ns = addLog(ns, `${FACILITY_INFO[a.facility].name}升级到 Lv${cur + 1}！${FACILITY_INFO[a.facility].levels[cur - 1].effect}。`, 'hint')
      return checkTriggers(ns)
    }

    case 'GUILD_JOIN': {
      if (s.guildMember || repLevel(s.rep) < 4 || s.gold < 2000) return s
      let ns: GameState = { ...s, gold: s.gold - 2000, guildMember: true }
      return addLog(ns, '缴纳 2,000G 押金，成为铁匠行会供应商会员：材料采购永久 -10%。', 'hint')
    }

    case 'STALL': {
      if (s.gold < 200 || s.stallNext) return s
      let ns: GameState = { ...s, gold: s.gold - 200, stallNext: true }
      return addLog(ns, '支付了 200G 摊位费：下次开门迎客时顾客流量翻倍！', 'hint')
    }

    case 'CONTEST': {
      if (s.rep < 80 || s.gold < 100) return s
      const r = contestResult(a.completion)
      let ns: GameState = { ...s, gold: s.gold - 100 + r.prize, totalRevenue: s.totalRevenue + r.prize }
      if (r.prize > 0) {
        ns = { ...ns, contestWins: ns.contestWins + 1, rep: ns.rep + repGain(ns, 5) }
        ns = addLog(ns, `铁匠大赛获得${r.rank}！奖金 ${fmt(r.prize)}G，声誉 +5。`, 'hint')
      } else {
        ns = addLog(ns, `铁匠大赛落选了……报名费 100G 打了水漂。`, 'hint')
      }
      return checkTriggers(ns)
    }

    case 'AMEI_TALK': {
      if (!s.socialCharge) return addLog(s, '先去忙一阵铺子里的事吧。', 'hint')
      // 有可触发的新要求
      if (s.amei.stage < 5 && s.pendingHint) {
        const ns: GameState = { ...s, socialCharge: false, pendingHint: false }
        return pushScene(ns, sceneAmeiStage(s))
      }
      let ns: GameState = { ...s, socialCharge: false, amei: { ...s.amei, affection: s.amei.affection + 1 } }
      ns = addLog(ns, '你和阿梅聊了一会儿。（阿梅好感 +1）', 'story')
      return pushScene(ns, sceneAmeiSmalltalk(s))
    }

    case 'AMEI_GIFT': {
      if (s.gold < 500) return addLog(s, '金币不足 500G，买不起像样的礼物。', 'hint')
      let ns: GameState = { ...s, gold: s.gold - 500, amei: { ...s.amei, affection: s.amei.affection + 5 } }
      ns = addLog(ns, '你送给阿梅一支时兴的发簪，她满意地收下了。（阿梅好感 +5）', 'story')
      return pushScene(ns, sceneAmeiGift())
    }

    case 'XIAO_TALK': {
      if (!s.socialCharge) return addLog(s, '先去忙一阵铺子里的事吧。', 'hint')
      const gain = Math.max(1, Math.round(1 * DIFFICULTIES[s.difficulty].xiaoMult))
      let ns: GameState = { ...s, socialCharge: false, xiaoling: { ...s.xiaoling, affection: s.xiaoling.affection + gain } }
      ns = addLog(ns, `你和小铃闲聊了一会儿。（小铃好感 +${gain}）`, 'story')
      if (ns.fatigue.active) {
        const f = { ...ns.fatigue, talkLeft: ns.fatigue.talkLeft - 1 }
        ns = { ...ns, fatigue: f }
        if (f.talkLeft <= 0 || f.forgeLeft <= 0) {
          ns = addLog({ ...ns, fatigue: { active: false, forgeLeft: 0, talkLeft: 0 } }, '和小铃聊了会儿天，心里的疲惫散去了。【心累】状态解除。', 'hint')
        }
      }
      ns = pushScene(ns, sceneXiaoSmalltalk(s))
      // 小铃告白（好感≥80 主动对话触发）
      if (ns.xiaoling.affection >= 80 && !ns.xiaoling.evConfess && !ns.ending) {
        ns = { ...ns, xiaoling: { ...ns.xiaoling, evConfess: true } }
        ns = pushScene(ns, sceneXiaolingConfess(false))
      }
      return checkTriggers(ns)
    }

    case 'XIAO_FLOWER': {
      if (s.gold < 100) return addLog(s, '金币不足 100G。', 'hint')
      if (!s.socialCharge) return addLog(s, '先去忙一阵铺子里的事吧。', 'hint')
      const gain = Math.max(1, Math.round(5 * DIFFICULTIES[s.difficulty].xiaoMult))
      let ns: GameState = { ...s, gold: s.gold - 100, socialCharge: false, xiaoling: { ...s.xiaoling, affection: s.xiaoling.affection + gain } }
      ns = addLog(ns, `你摘了一束山野花送给小铃。（小铃好感 +${gain}）`, 'story')
      ns = pushScene(ns, sceneXiaoFlower())
      if (ns.xiaoling.affection >= 80 && !ns.xiaoling.evConfess && !ns.ending) {
        ns = { ...ns, xiaoling: { ...ns.xiaoling, evConfess: true } }
        ns = pushScene(ns, sceneXiaolingConfess(false))
      }
      return checkTriggers(ns)
    }

    case 'XIAO_QUEST': {
      // 小铃的委托：给她一件普通品质以上的任意武器（她爹木工用）
      if (!s.xiaoling.helpUnlocked) return s
      const w = s.inventory.find((x) => x.quality !== 'crude')
      if (!w) return addLog(s, '库存里没有拿得出手的武器（普通品质以上）。', 'hint')
      const gain = Math.round(8 * DIFFICULTIES[s.difficulty].xiaoMult)
      let ns: GameState = {
        ...s,
        inventory: s.inventory.filter((x) => x.id !== w.id),
        xiaoling: { ...s.xiaoling, affection: s.xiaoling.affection + gain, ordersDone: s.xiaoling.ordersDone + 1 },
      }
      ns = addLog(ns, `你把 ${w.name} 送给了小铃，她爹做木工正缺一件好工具。（小铃好感 +${gain}）`, 'story')
      ns = pushScene(ns, sceneXiaoQuest())
      return checkTriggers(ns)
    }

    case 'SCENE_CHOICE': {
      const act = a.action
      const closeScene = (st: GameState): GameState => {
        const [next, ...rest] = st.pendingScenes
        return { ...st, scene: next ?? null, pendingScenes: rest }
      }
      switch (act.type) {
        case 'close':
          return closeScene(s)
        case 'ameiAccept': {
          if (s.amei.stage === 0) {
            let ns: GameState = { ...s, amei: { ...s.amei, stage: 1, affection: s.amei.affection + 10 } }
            ns = addLog(closeScene(ns), `你答应了彩礼的要求（目标 ${fmt(stageRevenue(1, s.difficulty))}G 总营收）。阿梅好感 +10。`, 'story')
            return ns
          }
          const st = s.amei.stage
          let ns: GameState = {
            ...s,
            amei: { ...s.amei, stage: st + 1, affection: s.amei.affection + 10, refused: 0 },
            fatigue: { active: true, forgeLeft: 5, talkLeft: 3 },
          }
          ns = addLog(closeScene(ns), `你咬牙答应了阿梅的「${AMEI_STAGES[st].label}」要求。阿梅好感 +10。【心累】QTE 判定 -10%（锻造 5 次或与小铃交谈 3 次后恢复）。`, 'story')
          return checkTriggers(ns)
        }
        case 'ameiConsider':
          return addLog(closeScene({ ...s, pendingHint: true }), '你敷衍了过去，但这件事迟早要面对。', 'story')
        case 'ameiRefuse': {
          const refused = s.amei.refused + 1
          let ns: GameState = { ...s, amei: { ...s.amei, affection: s.amei.affection - 15, refused }, pendingHint: true }
          ns = addLog(closeScene(ns), `你拒绝了阿梅的要求。她哭着跑了。（阿梅好感 -15）`, 'story')
          return ns
        }
        case 'finalAmei':
          return endGame(closeScene(s), resolveEnding(s, 'amei'))
        case 'finalXiaoling':
          if (s.xiaoling.affection < 70) return addLog(closeScene(s), '你想起了小铃……但你们之间似乎还差点什么。（需要小铃好感 ≥ 70）', 'hint')
          return endGame(closeScene(s), resolveEnding(s, 'xiaoling'))
        case 'finalNone':
          return endGame(closeScene(s), resolveEnding(s, 'none'))
        case 'acceptDowry': {
          let ns: GameState = { ...s, gold: s.gold + 3000 }
          return addLog(closeScene(ns), '你收下了小铃的嫁妆，换成 3,000G。她笑得很开心，你心里却沉甸甸的。', 'story')
        }
        case 'refuseDowry': {
          const gain = Math.round(20 * DIFFICULTIES[s.difficulty].xiaoMult)
          let ns: GameState = { ...s, xiaoling: { ...s.xiaoling, affection: s.xiaoling.affection + gain } }
          return addLog(closeScene(ns), `你把布包推了回去。小铃怔怔地看着你，眼眶慢慢红了——那是高兴的泪水。（小铃好感 +${gain}）`, 'story')
        }
        case 'defendXiaoling': {
          const gain = Math.round(10 * DIFFICULTIES[s.difficulty].xiaoMult)
          let ns: GameState = {
            ...s,
            xiaoling: { ...s.xiaoling, affection: s.xiaoling.affection + gain },
            amei: { ...s.amei, affection: s.amei.affection - 5 },
          }
          return addLog(closeScene(ns), `你站出来护住了祖传铁砧，也护住了小铃。（小铃好感 +${gain}，阿梅好感 -5）`, 'story')
        }
        case 'staySilent': {
          let ns: GameState = { ...s, amei: { ...s.amei, affection: s.amei.affection + 5 } }
          return addLog(closeScene(ns), '你沉默地走开了。阿梅知道后很满意，小铃却好几天没来铺子。（阿梅好感 +5）', 'story')
        }
        case 'visitXiaoling': {
          let ns: GameState = { ...s, xiaoling: { ...s.xiaoling, hasGloves: true } }
          return addLog(closeScene(ns), '你收下了小铃的护手。【锻造 QTE 判定 +10%】', 'story')
        }
        case 'acceptConfess':
          return endGame(closeScene(s), resolveEnding(s, 'xiaoling'))
        case 'declineConfess': {
          let ns: GameState = { ...s, xiaoling: { ...s.xiaoling, affection: s.xiaoling.affection - 5 } }
          return addLog(closeScene(ns), '小铃勉强笑了笑：「没关系，我等你。」（小铃好感 -5）', 'story')
        }
        default:
          return closeScene(s)
      }
    }

    case 'CLOSE_SCENE': {
      const [next, ...rest] = s.pendingScenes
      return { ...s, scene: next ?? null, pendingScenes: rest }
    }

    case 'NG_PLUS':
      return reducer(s, { type: 'NEW_GAME', difficulty: s.difficulty, inherit: s })

    default:
      return s
  }
}

// ---------- Context ----------
const GameCtx = createContext<{ state: GameState; dispatch: React.Dispatch<Action> } | null>(null)

export function GameProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, null as unknown as GameState)
  useEffect(() => {
    if (state && state.started) {
      try { localStorage.setItem(SAVE_KEY, JSON.stringify(state)) } catch { /* ignore */ }
    }
  }, [state])
  return <GameCtx.Provider value={{ state, dispatch }}>{children}</GameCtx.Provider>
}

export function useGame() {
  const ctx = useContext(GameCtx)
  if (!ctx) throw new Error('no game ctx')
  return ctx
}

export function loadSave(): GameState | null {
  try {
    const raw = localStorage.getItem(SAVE_KEY)
    if (!raw) return null
    const s = JSON.parse(raw) as GameState
    if (!s.started) return null
    return s
  } catch {
    return null
  }
}
export function clearSave() {
  try { localStorage.removeItem(SAVE_KEY) } catch { /* ignore */ }
}
