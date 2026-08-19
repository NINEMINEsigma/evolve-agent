import { useState } from 'react'
import { useGame } from '@/game/state'
import { Btn } from './pixel'

export default function SceneModal() {
  const { state, dispatch } = useGame()
  const [line, setLine] = useState(0)
  const scene = state.scene
  if (!scene) return null

  const portrait = scene.speaker === 'amei' ? '/assets/amei.png' : scene.speaker === 'xiaoling' ? '/assets/xiaoling.png' : null
  const name = scene.speaker === 'amei' ? '阿梅' : scene.speaker === 'xiaoling' ? '小铃' : '——'
  const last = line >= scene.lines.length - 1

  const choose = (action: import('@/game/types').SceneAction) => {
    setLine(0)
    dispatch({ type: 'SCENE_CHOICE', action })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center pb-6" style={{ background: 'rgba(20,19,18,0.55)' }}>
      <div className="px-panel w-full max-w-3xl mx-4">
        <div className="px-titlebar"><span>{name}</span><span className="font-pixel text-sm">{line + 1}/{scene.lines.length}</span></div>
        <div className="p-4 flex gap-4">
          {portrait && <img src={portrait} alt={name} className="w-24 h-24 object-cover shrink-0" style={{ border: '3px solid #141312' }} />}
          <div className="flex-1 min-h-24">
            <p className="leading-relaxed" style={{ color: scene.speaker === 'narrator' ? '#4a4640' : '#141312' }}>
              {scene.lines[line]}
            </p>
            <div className="mt-4 flex gap-2 flex-wrap justify-end">
              {!last ? (
                <Btn variant="primary" onClick={() => setLine(line + 1)}><span className="scene-cursor">继续</span></Btn>
              ) : scene.choices ? (
                scene.choices.map((c, i) => (
                  <Btn key={i} variant={i === 0 ? 'primary' : undefined} onClick={() => choose(c.action)} title={c.hint}>
                    {c.label}
                  </Btn>
                ))
              ) : (
                <Btn variant="primary" onClick={() => choose({ type: 'close' })}>继续</Btn>
              )}
            </div>
            {last && scene.choices?.some((c) => c.hint) && (
              <div className="mt-2 text-xs opacity-60 text-right">
                {scene.choices.filter((c) => c.hint).map((c, i) => <div key={i}>{c.label}：{c.hint}</div>)}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
