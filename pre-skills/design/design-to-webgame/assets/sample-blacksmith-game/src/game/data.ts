import type {
  CustomerKind, Difficulty, MainMat, MaterialId, Quality, Recipe, SubMat, WeaponType, FacilityId,
} from './types'

// ============ 武器类型 ============
export const WEAPON_TYPES: Record<WeaponType, { name: string; atk: number; dur: number; coef: number; priceBase: number; icon: string }> = {
  sword:  { name: '剑',   atk: 30, dur: 100, coef: 1.0, priceBase: 80,  icon: '🗡' },
  axe:    { name: '斧',   atk: 45, dur: 150, coef: 1.2, priceBase: 89,  icon: '🪓' },
  spear:  { name: '枪',   atk: 40, dur: 120, coef: 1.1, priceBase: 94,  icon: '🔱' },
  hammer: { name: '锤',   atk: 55, dur: 200, coef: 1.3, priceBase: 136, icon: '🔨' },
  glove:  { name: '拳套', atk: 25, dur: 80,  coef: 0.9, priceBase: 90,  icon: '🥊' },
  bow:    { name: '弓',   atk: 35, dur: 90,  coef: 1.0, priceBase: 110, icon: '🏹' },
}

// ============ 材料 ============
export const MAIN_MATS: Record<MainMat, { name: string; price: number; atkMult: number; durMult: number; priceMult: number; fuel: number }> = {
  copper:  { name: '铜矿',   price: 20,  atkMult: 1.0, durMult: 1.0, priceMult: 1.0, fuel: 2 },
  iron:    { name: '铁矿',   price: 50,  atkMult: 1.5, durMult: 1.2, priceMult: 1.8, fuel: 3 },
  silver:  { name: '银矿',   price: 120, atkMult: 2.2, durMult: 1.4, priceMult: 2.8, fuel: 4 },
  mithril: { name: '秘银',   price: 300, atkMult: 3.2, durMult: 1.7, priceMult: 4.5, fuel: 5 },
  magic:   { name: '魔矿石', price: 800, atkMult: 4.5, durMult: 2.0, priceMult: 7.0, fuel: 6 },
}

export const SUB_MATS: Record<SubMat, { name: string; price: number; affix: string; affixDesc: string }> = {
  wood:        { name: '木材',     price: 15,  affix: '坚固',   affixDesc: '耐久 +15%' },
  leather:     { name: '皮革',     price: 30,  affix: '轻盈',   affixDesc: '速度提升，冒险者偏爱' },
  fireCore:    { name: '火魔核',   price: 150, affix: '火焰',   affixDesc: '火属性附着' },
  iceCore:     { name: '冰魔核',   price: 150, affix: '寒冰',   affixDesc: '冰属性附着' },
  thunderCore: { name: '雷魔核',   price: 150, affix: '雷电',   affixDesc: '雷属性附着' },
  gem:         { name: '宝石',     price: 200, affix: '会心',   affixDesc: '会心率提升，贵族偏爱' },
  monster:     { name: '怪物素材', price: 120, affix: '噬魂',   affixDesc: '特殊技能槽' },
}

export const MISC_MATS: Record<string, { name: string; price: number }> = {
  coal:       { name: '燃料(煤)', price: 5 },
  enhanceOre: { name: '强化矿石', price: 50 },
}

export const MATERIAL_NAMES: Record<MaterialId, string> = {
  copper: '铜矿', iron: '铁矿', silver: '银矿', mithril: '秘银', magic: '魔矿石',
  wood: '木材', leather: '皮革', fireCore: '火魔核', iceCore: '冰魔核', thunderCore: '雷魔核',
  gem: '宝石', monster: '怪物素材', coal: '燃料(煤)', enhanceOre: '强化矿石',
}

// 杂货铺常备 / 流动行商可能出现
export const SHOP_STOCK: MaterialId[] = ['copper', 'iron', 'silver', 'wood', 'leather', 'coal', 'enhanceOre']
export const MERCHANT_POOL: MaterialId[] = ['mithril', 'magic', 'fireCore', 'iceCore', 'thunderCore', 'gem', 'monster', 'silver']

// ============ 品质 ============
export const QUALITIES: Record<Quality, { name: string; coef: number; priceMult: number; color: string; decomposeRate: number; insightRate: number; exp: number; rep: number }> = {
  crude:  { name: '粗糙', coef: 0.8, priceMult: 0.8, color: '#8a8578', decomposeRate: 0.3, insightRate: 0,    exp: 5,  rep: 0 },
  normal: { name: '普通', coef: 1.0, priceMult: 1.0, color: '#4a4640', decomposeRate: 0.4, insightRate: 0.05, exp: 15, rep: 0 },
  fine:   { name: '精良', coef: 1.2, priceMult: 1.2, color: '#2e6b34', decomposeRate: 0.5, insightRate: 0.10, exp: 30, rep: 1 },
  epic:   { name: '史诗', coef: 1.5, priceMult: 1.6, color: '#7a4a9e', decomposeRate: 0.6, insightRate: 0.20, exp: 50, rep: 3 },
  legend: { name: '传说', coef: 2.0, priceMult: 2.0, color: '#c25e10', decomposeRate: 0.7, insightRate: 0.40, exp: 80, rep: 5 },
}
export const QUALITY_ORDER: Quality[] = ['crude', 'normal', 'fine', 'epic', 'legend']

// ============ 强化 ============
export const ENHANCE_TABLE = [
  { prob: 0.95, ore: 1 },
  { prob: 0.90, ore: 1 },
  { prob: 0.80, ore: 2 },
  { prob: 0.70, ore: 2 },
  { prob: 0.60, ore: 3 },
]

// ============ 锻造等级 ============
export const FORGE_LEVELS = [0, 100, 300, 800, 1500, 2500, 4000] // Lv1..Lv7 所需累计经验

// ============ 配方（锻造等级 × 铁砧 × 声誉 三重门槛） ============
export const RECIPES: Recipe[] = [
  { id: 'sword_copper',  type: 'sword',  main: 'copper',  name: '铜剑',     reqForgeLv: 1, reqAnvilLv: 1, reqRepLv: 1 },
  { id: 'axe_copper',    type: 'axe',    main: 'copper',  name: '铜斧',     reqForgeLv: 1, reqAnvilLv: 2, reqRepLv: 1 },
  { id: 'spear_copper',  type: 'spear',  main: 'copper',  name: '铜枪',     reqForgeLv: 1, reqAnvilLv: 2, reqRepLv: 1 },
  { id: 'sword_iron',    type: 'sword',  main: 'iron',    name: '铁剑',     reqForgeLv: 2, reqAnvilLv: 1, reqRepLv: 1 },
  { id: 'axe_iron',      type: 'axe',    main: 'iron',    name: '铁斧',     reqForgeLv: 2, reqAnvilLv: 2, reqRepLv: 1 },
  { id: 'spear_iron',    type: 'spear',  main: 'iron',    name: '铁枪',     reqForgeLv: 2, reqAnvilLv: 2, reqRepLv: 1 },
  { id: 'hammer_copper', type: 'hammer', main: 'copper',  name: '铜锤',     reqForgeLv: 2, reqAnvilLv: 3, reqRepLv: 1 },
  { id: 'sword_silver',  type: 'sword',  main: 'silver',  name: '银剑',     reqForgeLv: 3, reqAnvilLv: 1, reqRepLv: 1 },
  { id: 'axe_silver',    type: 'axe',    main: 'silver',  name: '银斧',     reqForgeLv: 3, reqAnvilLv: 2, reqRepLv: 1 },
  { id: 'spear_silver',  type: 'spear',  main: 'silver',  name: '银枪',     reqForgeLv: 3, reqAnvilLv: 2, reqRepLv: 1 },
  { id: 'hammer_iron',   type: 'hammer', main: 'iron',    name: '铁锤',     reqForgeLv: 3, reqAnvilLv: 3, reqRepLv: 1 },
  { id: 'sword_mithril', type: 'sword',  main: 'mithril', name: '秘银剑',   reqForgeLv: 4, reqAnvilLv: 1, reqRepLv: 3 },
  { id: 'hammer_silver', type: 'hammer', main: 'silver',  name: '银锤',     reqForgeLv: 4, reqAnvilLv: 3, reqRepLv: 3 },
  { id: 'bow_copper',    type: 'bow',    main: 'copper',  name: '铜弓',     reqForgeLv: 4, reqAnvilLv: 2, reqRepLv: 2 },
  { id: 'glove_copper',  type: 'glove',  main: 'copper',  name: '铜拳套',   reqForgeLv: 4, reqAnvilLv: 2, reqRepLv: 1 },
  { id: 'axe_mithril',   type: 'axe',    main: 'mithril', name: '秘银斧',   reqForgeLv: 5, reqAnvilLv: 2, reqRepLv: 3 },
  { id: 'spear_mithril', type: 'spear',  main: 'mithril', name: '秘银枪',   reqForgeLv: 5, reqAnvilLv: 2, reqRepLv: 3 },
  { id: 'bow_iron',      type: 'bow',    main: 'iron',    name: '铁弓',     reqForgeLv: 5, reqAnvilLv: 2, reqRepLv: 2 },
  { id: 'glove_iron',    type: 'glove',  main: 'iron',    name: '铁拳套',   reqForgeLv: 5, reqAnvilLv: 2, reqRepLv: 1 },
  { id: 'sword_magic',   type: 'sword',  main: 'magic',   name: '魔矿剑',   reqForgeLv: 6, reqAnvilLv: 1, reqRepLv: 3 },
  { id: 'axe_magic',     type: 'axe',    main: 'magic',   name: '魔矿斧',   reqForgeLv: 6, reqAnvilLv: 2, reqRepLv: 3 },
  { id: 'spear_magic',   type: 'spear',  main: 'magic',   name: '魔矿枪',   reqForgeLv: 6, reqAnvilLv: 2, reqRepLv: 3 },
  { id: 'hammer_magic',  type: 'hammer', main: 'magic',   name: '魔矿锤',   reqForgeLv: 6, reqAnvilLv: 3, reqRepLv: 3 },
  { id: 'bow_magic',     type: 'bow',    main: 'magic',   name: '魔矿弓',   reqForgeLv: 6, reqAnvilLv: 2, reqRepLv: 3 },
  { id: 'glove_magic',   type: 'glove',  main: 'magic',   name: '魔矿拳套', reqForgeLv: 6, reqAnvilLv: 2, reqRepLv: 3 },
  { id: 'hammer_heart',  type: 'hammer', main: 'magic',   name: '真心之锤', reqForgeLv: 7, reqAnvilLv: 5, reqRepLv: 5, special: true },
]

// ============ 店铺升级 ============
export const FACILITY_INFO: Record<FacilityId, { name: string; levels: { cost: number; effect: string }[] }> = {
  anvil: {
    name: '铁砧',
    levels: [
      { cost: 500,   effect: '可锻造精良品质，解锁斧/枪类配方' },
      { cost: 2000,  effect: '可锻造史诗品质，解锁锤类配方' },
      { cost: 5000,  effect: '可锻造传说品质，解锁弓/拳套高级配方' },
      { cost: 15000, effect: '全配方解锁（含传说专属）' },
    ],
  },
  shelf: {
    name: '陈列柜',
    levels: [
      { cost: 800,  effect: '顾客上限 +2' },
      { cost: 3000, effect: '顾客上限 +3，贵族出现率 +10%' },
    ],
  },
  storage: {
    name: '仓库',
    levels: [
      { cost: 400,  effect: '材料存储上限 +50' },
      { cost: 1500, effect: '材料存储上限 +100' },
    ],
  },
  sign: {
    name: '招牌',
    levels: [{ cost: 600, effect: '声誉获取 +20%' }],
  },
  furnace: {
    name: '熔炉',
    levels: [{ cost: 1000, effect: '锻造燃料消耗 -20%' }],
  },
}
export const FACILITY_MAX: Record<FacilityId, number> = { anvil: 5, shelf: 3, storage: 3, sign: 2, furnace: 2 }

// ============ 声誉等级 ============
export const REP_LEVELS = [0, 30, 80, 150, 250]
export const REP_PERKS = [
  '基础顾客、基础配方',
  '冒险者顾客上门、弓类解锁',
  '贵族顾客上门、锤/秘银配方解锁',
  '军队批量订单、行会供应商资格',
  '传说配方、特殊委托',
]

// ============ 顾客 ============
export const CUSTOMER_KINDS: Record<CustomerKind, { name: string; budgetMin: number; budgetMax: number; orderMin: number; orderMax: number; reqRepLv: number }> = {
  villager:   { name: '村民',   budgetMin: 100,  budgetMax: 300,   orderMin: 100,  orderMax: 300,   reqRepLv: 1 },
  adventurer: { name: '冒险者', budgetMin: 300,  budgetMax: 2000,  orderMin: 500,  orderMax: 3000,  reqRepLv: 2 },
  noble:      { name: '贵族',   budgetMin: 1000, budgetMax: 8000,  orderMin: 2000, orderMax: 10000, reqRepLv: 3 },
  army:       { name: '军队',   budgetMin: 2000, budgetMax: 6000,  orderMin: 5000, orderMax: 20000, reqRepLv: 4 },
}

export const VILLAGER_NAMES = ['老王', '樵夫阿岩', '农夫春耕', '猎户大山', '渔夫小川', '守夜人张伯']
export const ADVENTURER_NAMES = ['佣兵红莲', '游侠疾风', '盾卫铁岩', '刺客夜刃', '术士星尘', '骑士白银']
export const NOBLE_NAMES = ['子爵冯·罗严', '男爵夫人莉莉安', '商会会长金满楼', '伯爵管家塞巴斯']
export const ARMY_NAMES = ['王国军需官', '边境军团长', '王都卫队长']

// ============ 彩礼剧情（金额为设计值 × 剧情缩放） ============
export const STORY_SCALE = 1 / 50
export const AMEI_STAGES = [
  { key: 'bride',   label: '彩礼',       amount: 380000,  atRevenue: 0 },
  { key: 'feast',   label: '婚宴',       amount: 200000,  atRevenue: 380000 },
  { key: 'house',   label: '买房',       amount: 2000000, atRevenue: 580000 },
  { key: 'brother', label: '弟弟聘礼',   amount: 500000,  atRevenue: 2580000 },
  { key: 'gold5',   label: '五金下车费', amount: 300000,  atRevenue: 3080000 },
  { key: 'sellout', label: '卖掉铁匠铺', amount: 0,       atRevenue: 3380000 },
]

// ============ 难度 ============
export const DIFFICULTIES: Record<Difficulty, { name: string; matMult: number; priceMult: number; ameiMult: number; xiaoMult: number; orderMult: number; enhanceBonus: number }> = {
  easy:   { name: '轻松', matMult: 0.7, priceMult: 1.3, ameiMult: 0.7, xiaoMult: 1.5, orderMult: 1.2, enhanceBonus: 0.10 },
  normal: { name: '普通', matMult: 1.0, priceMult: 1.0, ameiMult: 1.0, xiaoMult: 1.0, orderMult: 1.0, enhanceBonus: 0 },
  hard:   { name: '困难', matMult: 1.3, priceMult: 0.8, ameiMult: 1.5, xiaoMult: 0.7, orderMult: 0.8, enhanceBonus: -0.10 },
  brutal: { name: '极难', matMult: 1.6, priceMult: 0.6, ameiMult: 2.0, xiaoMult: 0.5, orderMult: 0.6, enhanceBonus: -0.20 },
}

// ============ 结局 ============
export const ENDINGS: Record<string, { title: string; subtitle: string; desc: string }> = {
  trueHammer: {
    title: '真心之锤',
    subtitle: '完美结局',
    desc: '你放下了那杆永远填不满的秤。小铃没有要一分彩礼，只把她亲手做的木锤挂在了铺子门口——"两个人一起打铁的铺子，才叫家"。炉火依旧，炊烟袅袅，铁匠铺的招牌换成了两个人的名字。多年后村里人常说：真心铺里打出的武器，都带着温度。',
  },
  quietHappy: {
    title: '平凡幸福',
    subtitle: '小铃结局',
    desc: '你选择了小铃。日子平淡得像村口的溪水：清晨她送来便当，傍晚你们一起收拾铺子。没有大富大贵，但每一锤都敲得踏实。偶尔你也会想起阿梅，但看着身边人的笑容，你知道自己没有选错。',
  },
  obsession: {
    title: '执念成婚',
    subtitle: '阿梅结局',
    desc: '你满足了阿梅所有的要求，卖掉了祖传的铁匠铺，搬进了城里的宅子。婚礼上她笑得很美，可婚后她的目光总落在别人更新的宅子、更亮的马车上。你失去了铁砧，也再没听见那声清脆的锤响。深夜里你常梦见炉火，醒来只剩一片冰凉。',
  },
  reluctant: {
    title: '勉强成婚',
    subtitle: '阿梅结局',
    desc: '婚是结了，彩礼却欠了一屁股债。阿梅总在抱怨：抱怨房子不够大，抱怨你赚钱不够快。你每天打十六个小时的铁还债，手上的茧越来越厚，心里的火越来越弱。你们成了夫妻，却像两个讨债的与还债的。',
  },
  escape: {
    title: '逃避之路',
    subtitle: '孤独结局',
    desc: '你谁都没有选，把自己埋进了炉火里。多年后你成了传说中的铁匠，你的作品被贵族争抢、被王室收藏。可每当夜深人静，铺子里只有炉火噼啪作响。你赢得了名声，却弄丢了所有等你回家的人。',
  },
  tycoon: {
    title: '商业大亨',
    subtitle: '事业结局',
    desc: '你把铁匠铺做成了王国最大的武器商行，分号开到了王都。金币如潮水般涌来，账房先生打算盘的声音昼夜不停。你什么都有了——除了一个会在傍晚给你送便当的人。账本的最后一页，你写下：利润，无法锻造。',
  },
  lonely: {
    title: '孤独铁匠',
    subtitle: '失败结局',
    desc: '阿梅嫁给了城里的布商，小铃也随父亲搬去了邻村。铁匠铺的炉火还亮着，只是再没有人推门进来喊你的名字。你守着祖传的铁砧，一年又一年，把孤独打进了每一把剑里。',
  },
}
