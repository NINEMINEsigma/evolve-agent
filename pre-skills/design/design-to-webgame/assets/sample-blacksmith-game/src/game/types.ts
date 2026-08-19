// 游戏类型定义
export type WeaponType = 'sword' | 'axe' | 'spear' | 'hammer' | 'glove' | 'bow'
export type MainMat = 'copper' | 'iron' | 'silver' | 'mithril' | 'magic'
export type SubMat = 'wood' | 'leather' | 'fireCore' | 'iceCore' | 'thunderCore' | 'gem' | 'monster'
export type MiscMat = 'coal' | 'enhanceOre'
export type MaterialId = MainMat | SubMat | MiscMat
export type Quality = 'crude' | 'normal' | 'fine' | 'epic' | 'legend'
export type Difficulty = 'easy' | 'normal' | 'hard' | 'brutal'
export type CustomerKind = 'villager' | 'adventurer' | 'noble' | 'army'

export interface Recipe {
  id: string
  type: WeaponType
  main: MainMat
  name: string
  reqForgeLv: number
  reqAnvilLv: number
  reqRepLv: number
  special?: boolean
}

export interface Weapon {
  id: number
  type: WeaponType
  main: MainMat
  sub: SubMat
  name: string
  quality: Quality
  completion: number
  atk: number
  dur: number
  enhance: number
  affixes: string[]
  basePrice: number
}

export interface Order {
  id: number
  kind: CustomerKind
  customerName: string
  wantType: WeaponType | null // null = 任意类型
  minAtk: number
  minQuality: Quality
  wantAffix: string | null
  reward: number
  tipPct: number // 小费比例
  desc: string
  fromXiaoling?: boolean
}

export interface Customer {
  id: number
  kind: CustomerKind
  name: string
  mode: 'buy' | 'order' | 'repair' | 'barter'
  wantType: WeaponType
  minQuality: Quality
  budget: number
  desc: string
  order?: Omit<Order, 'id'>
  barterMat?: MaterialId
  barterQty?: number
}

export type FacilityId = 'anvil' | 'shelf' | 'storage' | 'sign' | 'furnace'

export interface Facilities {
  anvil: number
  shelf: number
  storage: number
  sign: number
  furnace: number
}

export interface SceneChoice {
  label: string
  hint?: string
  action: SceneAction
}

export type SceneAction =
  | { type: 'close' }
  | { type: 'ameiAccept' }
  | { type: 'ameiRefuse' }
  | { type: 'ameiConsider' }
  | { type: 'finalAmei' }
  | { type: 'finalXiaoling' }
  | { type: 'finalNone' }
  | { type: 'acceptDowry' }
  | { type: 'refuseDowry' }
  | { type: 'defendXiaoling' }
  | { type: 'staySilent' }
  | { type: 'visitXiaoling' }
  | { type: 'acceptConfess' }
  | { type: 'declineConfess' }

export interface Scene {
  id: string
  speaker: 'amei' | 'xiaoling' | 'narrator'
  lines: string[]
  choices?: SceneChoice[]
  onEnd?: SceneAction
}

export interface LogEntry {
  text: string
  kind: 'story' | 'system' | 'hint'
}

export interface GameState {
  started: boolean
  difficulty: Difficulty
  ngPlus: number
  gold: number
  totalRevenue: number
  rep: number
  forgeExp: number
  salesCount: number
  materials: Record<MaterialId, number>
  inventory: Weapon[]
  nextWeaponId: number
  orders: Order[]
  nextOrderId: number
  customers: Customer[]
  nextCustomerId: number
  marketHeat: number
  merchantStock: Partial<Record<MaterialId, number>> | null
  merchantPriceMult: number
  stallNext: boolean
  insight: number
  insightUnlocked: string[] // 通过心得解锁的配方 id
  facilities: Facilities
  amei: {
    affection: number
    stage: number // 0=未开始 1..6 已接受到第几阶段要求
    finalTriggered: boolean
    refused: number
  }
  xiaoling: {
    affection: number
    helpUnlocked: boolean
    hasGloves: boolean
    ordersDone: number
    evHelp: boolean
    evAnvil: boolean
    evSick: boolean
    evDowry: boolean
    evConfess: boolean
    lunchUsed: boolean
  }
  fatigue: { active: boolean; forgeLeft: number; talkLeft: number }
  socialCharge: boolean
  bargainUsed: boolean // 本次行商/采购已用小铃砍价
  guildMember: boolean
  contestWins: number
  log: LogEntry[]
  scene: Scene | null
  pendingScenes: Scene[]
  ending: string | null
  pendingHint: boolean // 社交页 "!" 提示
}
