import type { GameState, Scene } from './types'
import { stageAmount, pick } from './engine'

const G = (s: GameState, i: number) => stageAmount(i, s.difficulty).toLocaleString('zh-CN')

// 开局：阿梅初次提出彩礼
export function sceneIntro(): Scene {
  return {
    id: 'intro', speaker: 'amei',
    lines: [
      '阿梅站在铁匠铺门口，夕阳把她的影子拉得很长。你们从小一起长大，村里人都说你们是天生一对。',
      '「我爹娘说了，彩礼要三十八……」她顿了顿，看到你的脸色，改口道，「按村里的规矩折算，先拿一笔彩礼钱来，我才能嫁给你。」',
      '「你不是最喜欢打铁吗？那就好好打，我等你。」她笑着转身离开，留下你一个人对着炉火发呆。',
      '隔壁木匠家的小铃探出头来：「哥，别愣着啦，我帮你生了炉火。慢慢来，总会攒够的。」',
    ],
    choices: [{ label: '开始经营铁匠铺', action: { type: 'ameiAccept' } }],
  }
}

// 阿梅加价剧情（阶段 1~4：婚宴/买房/弟弟聘礼/五金）
export function sceneAmeiStage(s: GameState): Scene {
  const st = s.amei.stage // 当前已完成的阶段数，新要求是第 st 个
  const amount = G(s, st)
  const bank: Record<number, string[]> = {
    1: [
      '阿梅提着一篮子点心来到铺子里，笑吟吟地看着你记账。',
      '「彩礼的钱我爹娘很满意。不过……」她掰着手指头，「出嫁总要有婚宴吧？村里嫁女儿都办三十桌，我不能比别人差。婚宴再加一笔，不多，真的不多。」',
      `【新要求：婚宴 ${amount}G】`,
    ],
    2: [
      '这次阿梅带来了一张城里的房产图样，铺在你的铁砧上。',
      '「我表姐嫁去城里，人家夫家直接备了宅子。」她的手指点着图样，「我们总不能一辈子窝在村里吧？买套房，我们的将来才算有着落。」',
      `【新要求：买房 ${amount}G】炉火映着图样上漂亮的宅子，你突然觉得很累。`,
    ],
    3: [
      '阿梅这次来眼睛红红的，说是跟家里吵了一架。',
      '「我弟弟也要说亲了，女方要聘礼。爹娘年纪大了，这笔钱……只能我们帮衬。」她拉着你的袖子，「你不会不管我弟弟吧？」',
      `【新要求：弟弟的聘礼 ${amount}G】`,
    ],
    4: [
      '「最后一件小事，真的是最后一件了。」阿梅举起一只手晃了晃。',
      '「五金、下车费，一样都不能少，这是规矩。你要是真疼我，就不会让我在姐妹们面前抬不起头，对吧？」',
      `【新要求：五金下车费 ${amount}G】`,
    ],
  }
  return {
    id: `amei_stage_${st}`, speaker: 'amei',
    lines: bank[st] ?? ['阿梅又提出了新的要求。'],
    choices: [
      { label: '「好，我答应你。」', hint: '阿梅好感 +10，但你会感到身心俱疲', action: { type: 'ameiAccept' } },
      { label: '「让我再想想……」', hint: '暂缓答复', action: { type: 'ameiConsider' } },
      { label: '「这太过分了！」', hint: '阿梅好感 -15', action: { type: 'ameiRefuse' } },
    ],
  }
}

// 阿梅最终要求：卖铺
export function sceneAmeiFinal(s: GameState): Scene {
  void s
  return {
    id: 'amei_final', speaker: 'amei',
    lines: [
      '所有钱都凑齐了。你以为终于熬到了头，阿梅却带来了最后一句话。',
      '「我爹娘说，嫁汉嫁汉，穿衣吃饭。你那铺子又脏又累，成亲后就卖了吧，我们搬去城里，你找个体面的营生。」',
      '卖掉铁匠铺——那是你爷爷传给爹、爹传给你的铁砧，是你一锤一锤敲出的人生。炉火在你身后噼啪作响，像是在替谁呜咽。',
      '你想起这些日子：彩礼、婚宴、房子、聘礼、五金……每一次都说"这是最后一次"。',
      '你也想起小铃：那个帮你生火、替你砍价、在你累的时候悄悄把便当挂在门上的姑娘。',
      '【最终抉择】',
    ],
    choices: [
      { label: '答应她，卖掉铺子', hint: '满足阿梅所有要求，进入阿梅线结局', action: { type: 'finalAmei' } },
      { label: '拒绝她，去找小铃', hint: '需要小铃好感 ≥ 70', action: { type: 'finalXiaoling' } },
      { label: '谁都不选，只想静静', hint: '进入逃避/事业结局', action: { type: 'finalNone' } },
    ],
  }
}

// 小铃：初次帮忙
export function sceneXiaolingHelp(): Scene {
  return {
    id: 'xl_help', speaker: 'xiaoling',
    lines: [
      '小铃抱着一捆劈好的柴火推门进来，额头上全是汗。',
      '「哥，我看你一个人忙不过来。我爹说了，邻里之间就该互相帮衬。」',
      '「以后我没事就来帮你照看铺子——砍价、整理库存，都包在我身上！」她拍了拍胸脯，发间的铃铛叮当作响。',
      '【解锁：小铃帮忙】市场砍价（-20%）与库存整理功能开放。',
    ],
    choices: [{ label: '「那就麻烦你了。」', action: { type: 'close' } }],
  }
}

// 小铃：维护铁砧
export function sceneXiaolingAnvil(): Scene {
  return {
    id: 'xl_anvil', speaker: 'xiaoling',
    lines: [
      '你路过阿梅家，听见院里传来争执声。阿梅的母亲正指挥伙计抬一块旧铁砧——那是你家祖传的、早年借给阿梅家用的老伙计。',
      '「这破铁疙瘩还能卖几个钱！」阿梅母亲嚷着。',
      '小铃张开双臂拦在门口：「婶子，这铁砧是哥家里三代传下来的！打铁的人没了铁砧，就像木匠没了刨子，您不能这样！」',
      '她回头看见了你，眼神里有焦急，也有委屈。',
    ],
    choices: [
      { label: '站出来：「小铃说得对，铁砧不卖。」', hint: '小铃好感 +10，阿梅好感 -5', action: { type: 'defendXiaoling' } },
      { label: '沉默地走开', hint: '阿梅好感 +5', action: { type: 'staySilent' } },
    ],
  }
}

// 小铃：生病
export function sceneXiaolingSick(): Scene {
  return {
    id: 'xl_sick', speaker: 'xiaoling',
    lines: [
      '一连几天没见小铃来铺子，你去木匠家探望，才知道她淋雨生了病，正发着低烧。',
      '「哥……你怎么来了。」她挣扎着想坐起来，「铺子……铺子没人帮你看着……」',
      '都这时候了还惦记着你的铺子。你把她按回被窝里，笨手笨脚地熬了一锅粥。',
      '临走时，她从枕下摸出一副护手塞给你：「我用爹的皮料缝的，打铁戴上，就不怕烫了。」',
      '【获得：小铃的护手】锻造 QTE 判定 +10%。',
    ],
    choices: [{ label: '收下护手，叮嘱她好好休息', action: { type: 'visitXiaoling' } }],
  }
}

// 小铃：卖嫁妆
export function sceneXiaolingDowry(): Scene {
  return {
    id: 'xl_dowry', speaker: 'xiaoling',
    lines: [
      '深夜，小铃敲开了铺子的门，怀里抱着一个小布包。烛光下，里面是一支银簪和几件崭新的嫁衣。',
      '「哥，我都知道了……阿梅姐要的钱越来越多。」她低着头，声音很轻，「这些是我攒的嫁妆。拿去当了吧，应该能顶一些。」',
      '「你别误会！」她慌忙抬头，脸涨得通红，「我只是……只是看不得你把自己熬干。」',
    ],
    choices: [
      { label: '推回去：「你的嫁妆，我不能要。」', hint: '小铃好感 +20', action: { type: 'refuseDowry' } },
      { label: '收下这份心意', hint: '获得 3,000G', action: { type: 'acceptDowry' } },
    ],
  }
}

// ============ 日常闲聊场景 ============

// 阿梅日常交谈（随剧情阶段与好感变化）
export function sceneAmeiSmalltalk(s: GameState): Scene {
  const st = s.amei.stage
  const banks: string[][] = []
  if (st <= 1) {
    banks.push(
      ['「城里新开了一家绸缎庄，料子可好看了。」阿梅比划着，「等我出嫁那天，一定要穿那样的料子。」'],
      ['「你别光顾着打铁，也学学人家王家的儿子，在城里账房做事，多体面。」她顿了顿，又笑道，「不过你打铁的样子……也还行啦。」'],
      ['阿梅翻看着你的账本：「攒了多少了？我爹娘可天天问呢。你呀，手脚得快点。」'],
    )
  } else if (st <= 3) {
    banks.push(
      ['「我表姐夫家又添了一辆马车。」阿梅状似无意地提起，「我们以后可不能比他们差。」'],
      ['「最近是不是很累？」她难得地问了一句，随即又道，「累就对了，吃得苦中苦，我爹娘才看得起你。」'],
      ['阿梅看着你手上的茧，皱了皱眉：「成亲以后，这粗活还是少干些吧，让人笑话。」'],
    )
  } else {
    banks.push(
      ['「就差最后一点了。」阿梅的眼睛亮晶晶的，「等搬到城里，你就不用守着这烟熏火燎的铺子了。」'],
      ['「我娘已经在看日子了。」阿梅掰着手指算着什么，没有注意到你欲言又止的表情。'],
    )
  }
  if (s.amei.affection >= 80) {
    banks.push(['阿梅难得地红了脸：「其实……我也知道我要得多。可我就是想风风光光地嫁给你，让全村人都羡慕。」'])
  }
  return { id: 'amei_talk', speaker: 'amei', lines: pick(banks), choices: [{ label: '（继续）', action: { type: 'close' } }] }
}

// 小铃日常闲聊
export function sceneXiaoSmalltalk(s: GameState): Scene {
  const banks: string[][] = [
    ['「哥，我爹新打了一张犁，可漂亮了！」小铃絮絮地说着木匠铺的琐事，「他说你的手艺在村里也是数一数二的。」'],
    ['小铃一边擦着柜台一边哼着小调，发间的铃铛随着节奏轻轻响。注意到你在听，她不好意思地停了：「吵到你啦？」'],
    ['「炉火不能断，铁器怕急冷。」小铃认真地复述着不知从哪听来的门道，「我都记着呢，以后能帮你看着火。」'],
    ['小铃趴在窗边看着远山：「城里的灯，真的有星星那么亮吗？」随即又摇摇头，「不去也罢，村里挺好的。」'],
  ]
  if (s.fatigue.active) {
    banks.unshift(
      ['小铃给你倒了一碗热茶：「哥，你这几天眉头一直皱着。」她轻声说，「天大的事，喝口茶再说。铁要慢慢打，人也要慢慢活。」'],
      ['「累了就歇会儿嘛。」小铃不由分说地把一块桂花糕塞到你手里，「铺子我帮你看着，跑不了。」'],
    )
  }
  if (s.xiaoling.affection >= 60) {
    banks.push(['小铃欲言又止了好几次，最后只是低着头帮你整理工具，耳朵尖红红的。'])
  }
  return { id: 'xiao_talk', speaker: 'xiaoling', lines: pick(banks), choices: [{ label: '（继续）', action: { type: 'close' } }] }
}

// 送礼小剧场
export function sceneAmeiGift(): Scene {
  return {
    id: 'amei_gift', speaker: 'amei',
    lines: [pick([
      '阿梅接过发簪，对着日光看了又看：「算你有心。」她别到发间，「好看吗？」——好看是好看，就是不知道这份心意在账本上又记了几笔。',
      '「哟，还知道给我买东西。」阿梅嘴上嗔怪，手却诚实地把礼物收进了袖子里，「下次……下次带城里的那种就行。」',
    ])],
    choices: [{ label: '（继续）', action: { type: 'close' } }],
  }
}

export function sceneXiaoFlower(): Scene {
  return {
    id: 'xiao_flower', speaker: 'xiaoling',
    lines: [pick([
      '小铃捧着那束山野花愣了好一会儿，脸慢慢红到了耳根：「给、给我的？」她小心翼翼地抽出一支别在发间，转身时铃铛响得格外欢快。',
      '「路边的花……你怎么知道我喜欢这个？」小铃把花插进窗台的粗陶罐里，看了又看，「谢谢你，哥。」',
    ])],
    choices: [{ label: '（继续）', action: { type: 'close' } }],
  }
}

export function sceneXiaoQuest(): Scene {
  return {
    id: 'xiao_quest', speaker: 'xiaoling',
    lines: [
      '「这、这是给我的？」小铃双手接过武器，眼睛瞪得圆圆的。',
      '「我爹正缺一件好家伙什！他肯定高兴坏了。」她把武器抱在怀里，郑重其事地鞠了一躬，「哥，谢谢你。你打的东西，都是带着心意的。」',
    ],
    choices: [{ label: '（继续）', action: { type: 'close' } }],
  }
}

// 小铃：告白
export function sceneXiaolingConfess(ngPlus: boolean): Scene {
  return {
    id: 'xl_confess', speaker: 'xiaoling',
    lines: [
      ngPlus
        ? '这一世，小铃似乎早就下定了决心。她把你拉到村后的樱花树下，深吸了一口气。'
        : '打烊后，小铃没有回家。她站在炉火边，手指绞着围裙角，铃铛随着她的呼吸轻轻晃。',
      '「哥，我有句话，憋了好久好久了。」',
      '「我不要彩礼，不要房子，也不要什么五金。我就想……每天给你送便当，帮你生火，看你打铁。」',
      '「你打的铁是热的，可你这些日子过得太冷了。让我陪着你，好不好？」',
      '炉火噼啪作响。这一次，换你来做选择了。',
    ],
    choices: [
      { label: '握住她的手：「好。」', hint: '进入小铃线结局', action: { type: 'acceptConfess' } },
      { label: '「对不起，我……还没想好。」', hint: '继续经营', action: { type: 'declineConfess' } },
    ],
  }
}
