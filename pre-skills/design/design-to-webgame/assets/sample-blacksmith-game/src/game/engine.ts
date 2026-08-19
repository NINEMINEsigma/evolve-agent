import {
  WEAPON_TYPES, MAIN_MATS, SUB_MATS, QUALITIES, QUALITY_ORDER, RECIPES, FORGE_LEVELS,
  REP_LEVELS, CUSTOMER_KINDS, VILLAGER_NAMES, ADVENTURER_NAMES, NOBLE_NAMES, ARMY_NAMES,
  AMEI_STAGES, STORY_SCALE, DIFFICULTIES, MATERIAL_NAMES, MERCHANT_POOL,
} from './data'
import type {
  Customer, CustomerKind, Difficulty, GameState, MainMat, MaterialId, Order, Quality,
  Recipe, SubMat, Weapon, WeaponType,
} from './types'

let seed = Date.now() % 2147483647
export function rand(): number {
  seed = (seed * 48271) % 2147483647
  return seed / 2147483647
}
export function randInt(min: number, max: number): number {
  return Math.floor(rand() * (max - min + 1)) + min
}
export function pick<T>(arr: T[]): T {
  return arr[Math.floor(rand() * arr.length)]
}
export function fmt(n: number): string {
  return n.toLocaleString('zh-CN')
}

// ---------- 等级 ----------
export function forgeLevel(exp: number): number {
  let lv = 1
  for (let i = 0; i < FORGE_LEVELS.length; i++) if (exp >= FORGE_LEVELS[i]) lv = i + 1
  return lv
}
export function repLevel(rep: number): number {
  let lv = 1
  for (let i = 0; i < REP_LEVELS.length; i++) if (rep >= REP_LEVELS[i]) lv = i + 1
  return lv
}
export function haggleLevel(sales: number): number {
  return Math.min(5, Math.floor(sales / 8))
}

// ---------- 配方 ----------
export function unlockedRecipes(s: GameState): Recipe[] {
  const fl = forgeLevel(s.forgeExp)
  const rl = repLevel(s.rep)
  return RECIPES.filter(
    (r) =>
      (r.reqForgeLv <= fl && r.reqAnvilLv <= s.facilities.anvil && r.reqRepLv <= rl) ||
      s.insightUnlocked.includes(r.id),
  )
}
export function nextLockedRecipe(s: GameState): Recipe | null {
  const unlocked = new Set(unlockedRecipes(s).map((r) => r.id))
  const locked = RECIPES.filter((r) => !unlocked.has(r.id) && !r.special)
  if (!locked.length) return null
  return pick(locked)
}

// ---------- 品质 ----------
export function qualityOf(completion: number, allPerfect: boolean): Quality {
  if (completion >= 100 && allPerfect) return 'legend'
  if (completion >= 90) return 'epic'
  if (completion >= 75) return 'fine'
  if (completion >= 50) return 'normal'
  return 'crude'
}
export function anvilQualityCap(anvilLv: number): Quality {
  if (anvilLv >= 4) return 'legend'
  if (anvilLv === 3) return 'epic'
  if (anvilLv === 2) return 'fine'
  return 'normal'
}
export function capQuality(q: Quality, cap: Quality): Quality {
  return QUALITY_ORDER[Math.min(QUALITY_ORDER.indexOf(q), QUALITY_ORDER.indexOf(cap))]
}

// ---------- 武器数值 ----------
export function weaponName(type: WeaponType, main: MainMat): string {
  return MAIN_MATS[main].name.replace(/矿|石/g, '') + WEAPON_TYPES[type].name
}

export function makeWeapon(
  type: WeaponType, main: MainMat, sub: SubMat,
  completion: number, allPerfect: boolean, anvilLv: number, id: number,
): Weapon {
  const t = WEAPON_TYPES[type]
  const m = MAIN_MATS[main]
  let q = qualityOf(completion, allPerfect)
  q = capQuality(q, anvilQualityCap(anvilLv))
  let atkMult = 1
  let durMult = 1
  if (q === 'fine') atkMult = 1.1
  if (q === 'epic') { atkMult = 1.25; durMult = 1.3 }
  if (q === 'legend') { atkMult = 1.5; durMult = 1.5 }
  if (q === 'crude') durMult = 0.8
  const affixes = [SUB_MATS[sub].affix]
  let subDur = 1
  if (sub === 'wood') subDur = 1.15
  const atk = Math.round(t.atk * m.atkMult * atkMult)
  const dur = Math.round(t.dur * m.durMult * durMult * subDur)
  const basePrice = Math.round(t.priceBase * m.priceMult)
  return { id, type, main, sub, name: weaponName(type, main), quality: q, completion, atk, dur, enhance: 0, affixes, basePrice }
}

// ---------- 定价 ----------
export function weaponPrice(w: Weapon, s: GameState): number {
  const diff = DIFFICULTIES[s.difficulty]
  const qi = QUALITIES[w.quality]
  const affixBonus = 1 + 0.1 * w.affixes.length
  const price =
    w.basePrice *
    qi.priceMult *
    (1 + 0.15 * w.enhance) *
    s.marketHeat *
    (1 + 0.05 * haggleLevel(s.salesCount)) *
    affixBonus *
    diff.priceMult
  return Math.round(price)
}

// ---------- 材料价格 ----------
export function materialBasePrice(mat: MaterialId): number {
  if (mat in MAIN_MATS) return MAIN_MATS[mat as MainMat].price
  if (mat in SUB_MATS) return SUB_MATS[mat as SubMat].price
  if (mat === 'coal') return 5
  return 50
}
export function materialPrice(mat: MaterialId, s: GameState): number {
  const diff = DIFFICULTIES[s.difficulty]
  let p = materialBasePrice(mat) * diff.matMult
  if (s.guildMember) p *= 0.9
  return Math.max(1, Math.round(p))
}
export function merchantPrice(mat: MaterialId, s: GameState): number {
  const diff = DIFFICULTIES[s.difficulty]
  return Math.max(1, Math.round(materialBasePrice(mat) * diff.matMult * s.merchantPriceMult))
}
export function storageCap(s: GameState): number {
  return 100 + (s.facilities.storage - 1) * 75
}
export function materialCount(s: GameState): number {
  return Object.values(s.materials).reduce((a, b) => a + b, 0)
}
export function fuelNeeded(main: MainMat, s: GameState): number {
  const base = MAIN_MATS[main].fuel
  return Math.max(1, Math.round(base * (s.facilities.furnace >= 2 ? 0.8 : 1)))
}

// ---------- 彩礼剧情阈值 ----------
export function stageAmount(stageIdx: number, diff: Difficulty): number {
  return Math.round(AMEI_STAGES[stageIdx].amount * STORY_SCALE * DIFFICULTIES[diff].ameiMult)
}
export function stageRevenue(stageIdx: number, diff: Difficulty): number {
  return Math.round(AMEI_STAGES[stageIdx].atRevenue * STORY_SCALE * DIFFICULTIES[diff].ameiMult)
}
// 当前彩礼累计目标
export function dowryTarget(s: GameState): { label: string; amount: number; met: boolean } | null {
  if (s.ending) return null
  const st = s.amei.stage
  if (st >= AMEI_STAGES.length) return null
  const amount = stageAmount(st, s.difficulty)
  const need = stageRevenue(st, s.difficulty)
  return { label: AMEI_STAGES[st].label, amount, met: s.totalRevenue >= need }
}
// 最终抉择阈值
export function finalRevenue(diff: Difficulty): number {
  return stageRevenue(5, diff)
}

// ---------- 顾客与订单生成 ----------
const TYPE_BY_KIND: Record<CustomerKind, WeaponType[]> = {
  villager: ['sword', 'axe', 'glove', 'bow'],
  adventurer: ['sword', 'axe', 'spear', 'bow', 'glove'],
  noble: ['sword', 'hammer', 'bow'],
  army: ['spear', 'sword', 'axe'],
}
const WANT_DESC: Record<WeaponType, string[]> = {
  sword: ['想要一把趁手的剑防身', '家里的旧剑断了，想换把新的'],
  axe: ['需要一把劈柴开路两用的斧子', '想要一把够分量的战斧'],
  spear: ['想订一支长枪', '需要一支结实的枪'],
  hammer: ['想收藏一把好锤', '需要一把有排面的锤'],
  glove: ['想要一副练拳的拳套', '格斗比赛快到了，需要好拳套'],
  bow: ['想换一把顺手的猎弓', '需要一把拉得满的好弓'],
}

function nameOf(kind: CustomerKind): string {
  if (kind === 'villager') return pick(VILLAGER_NAMES)
  if (kind === 'adventurer') return pick(ADVENTURER_NAMES)
  if (kind === 'noble') return pick(NOBLE_NAMES)
  return pick(ARMY_NAMES)
}

export function generateCustomers(s: GameState): { customers: Customer[]; heat: number; merchant: GameState['merchantStock']; merchantMult: number } {
  const rl = repLevel(s.rep)
  const heat = Math.round((0.8 + rand() * 0.7) * 100) / 100
  let count = 3 + [0, 0, 2, 3][s.facilities.shelf] || 3
  if (s.stallNext) count *= 2
  const kinds: CustomerKind[] = (['villager', 'adventurer', 'noble', 'army'] as CustomerKind[]).filter(
    (k) => CUSTOMER_KINDS[k].reqRepLv <= rl,
  )
  const customers: Customer[] = []
  let cid = s.nextCustomerId
  for (let i = 0; i < count; i++) {
    // 顾客类型权重
    let kind: CustomerKind = 'villager'
    const roll = rand()
    if (kinds.includes('army') && roll > 0.9) kind = 'army'
    else if (kinds.includes('noble') && roll > 0.72 - (s.facilities.shelf >= 3 ? 0.1 : 0)) kind = 'noble'
    else if (kinds.includes('adventurer') && roll > 0.4) kind = 'adventurer'
    const ck = CUSTOMER_KINDS[kind]
    const wantType = pick(TYPE_BY_KIND[kind])
    const name = nameOf(kind)
    const modeRoll = rand()
    let mode: Customer['mode'] = 'buy'
    if (modeRoll > 0.72) mode = 'order'
    else if (modeRoll > 0.62 && kind === 'adventurer') mode = 'barter'
    else if (modeRoll > 0.55 && kind === 'villager') mode = 'repair'
    const diff = DIFFICULTIES[s.difficulty]
    const budget = randInt(ck.budgetMin, ck.budgetMax)
    const minQuality: Quality = kind === 'noble' ? (rand() > 0.5 ? 'epic' : 'fine') : kind === 'army' ? 'fine' : rand() > 0.6 ? 'fine' : 'normal'
    const base: Customer = {
      id: cid++, kind, name, mode, wantType, minQuality, budget,
      desc: `${pick(WANT_DESC[wantType])}（预算约 ${fmt(budget)}G）`,
    }
    if (mode === 'order') {
      const reward = Math.round(randInt(ck.orderMin, ck.orderMax) * diff.orderMult)
      const wantAffix = rand() > 0.6 ? pick(['坚固', '轻盈', '火焰', '会心']) : null
      const atkRange: Record<CustomerKind, [number, number]> = {
        villager: [1.0, 1.6], adventurer: [1.2, 2.5], noble: [2.0, 3.0], army: [2.2, 3.6],
      }
      const [lo, hi] = atkRange[kind]
      const minAtk = Math.round(WEAPON_TYPES[wantType].atk * (lo + rand() * (hi - lo)))
      base.order = {
        kind, customerName: name, wantType, minAtk, minQuality, wantAffix,
        reward, tipPct: randInt(10, 25),
        desc: `${name}想订制${wantAffix ? `一把带「${wantAffix}」词条的` : '一把'}${QUALITIES[minQuality].name}品质以上的${WEAPON_TYPES[wantType].name}，攻击≥${minAtk}，报酬 ${fmt(reward)}G（小费 ${base.order?.tipPct ?? randInt(10, 25)}%）`,
      }
      base.desc = `【订单】${QUALITIES[minQuality].name}品质以上的${WEAPON_TYPES[wantType].name}，攻击≥${minAtk}${wantAffix ? `，带「${wantAffix}」词条` : ''}，报酬 ${fmt(reward)}G`
    } else if (mode === 'barter') {
      base.barterMat = pick(MERCHANT_POOL)
      base.barterQty = randInt(2, 5)
      base.desc = `想用${base.barterQty}个${MATERIAL_NAMES[base.barterMat]}换一把${WEAPON_TYPES[wantType].name}（普通品质以上）`
    } else if (mode === 'repair') {
      base.desc = '家里的旧农具坏了，想请你帮忙修一修'
    }
    customers.push(base)
  }
  // 流动行商
  let merchant: GameState['merchantStock'] = null
  let merchantMult = 1
  if (rand() > 0.35) {
    merchantMult = Math.round((0.8 + rand() * 0.7) * 100) / 100
    merchant = {}
    const n = randInt(2, 4)
    const pool = [...MERCHANT_POOL]
    for (let i = 0; i < n && pool.length; i++) {
      const idx = Math.floor(rand() * pool.length)
      const mat = pool.splice(idx, 1)[0]
      merchant[mat] = randInt(2, 6)
    }
  }
  return { customers, heat, merchant, merchantMult }
}

export function makeOrder(s: GameState, o: Omit<Order, 'id'>): Order {
  return { ...o, id: s.nextOrderId }
}

// ---------- 铁匠大赛 ----------
export function contestResult(completion: number): { rank: string; prize: number } {
  if (completion >= 98) return { rank: '冠军', prize: 5000 }
  if (completion >= 90) return { rank: '亚军', prize: 2000 }
  if (completion >= 75) return { rank: '季军', prize: 1000 }
  return { rank: '落选', prize: 0 }
}

// ---------- 结局判定 ----------
export function resolveEnding(s: GameState, choice: 'amei' | 'xiaoling' | 'none'): string {
  if (choice === 'xiaoling') {
    return s.xiaoling.affection >= 80 ? 'trueHammer' : 'quietHappy'
  }
  if (choice === 'amei') {
    if (s.amei.affection >= 80) return 'obsession'
    if (s.amei.affection >= 60) return 'reluctant'
    return 'lonely'
  }
  // 谁都不选
  const shopMax = s.facilities.anvil >= 5
  const repMax = repLevel(s.rep) >= 5
  if (shopMax && repMax && s.gold >= 20000) return 'tycoon'
  return 'escape'
}
