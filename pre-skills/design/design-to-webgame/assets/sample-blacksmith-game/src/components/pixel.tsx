import React from 'react'
import { QUALITIES } from '@/game/data'
import type { Quality } from '@/game/types'

export function Panel({ title, right, children, className = '' }: { title?: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={`px-panel ${className}`}>
      {title && (
        <div className="px-titlebar">
          <span>{title}</span>
          {right}
        </div>
      )}
      <div className="p-3">{children}</div>
    </div>
  )
}

export function Btn({ children, onClick, disabled, variant, className = '', title }: {
  children: React.ReactNode
  onClick?: () => void
  disabled?: boolean
  variant?: 'primary' | 'danger' | 'green'
  className?: string
  title?: string
}) {
  const v = variant === 'primary' ? 'px-btn-primary' : variant === 'danger' ? 'px-btn-danger' : variant === 'green' ? 'px-btn-green' : ''
  return (
    <button className={`px-btn ${v} ${className}`} onClick={onClick} disabled={disabled} title={title}>
      {children}
    </button>
  )
}

export function Bar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="px-bar">
      <div style={{ width: `${Math.min(100, Math.max(0, pct))}%`, background: color }} />
    </div>
  )
}

export function QualityTag({ q }: { q: Quality }) {
  const info = QUALITIES[q]
  return (
    <span
      className="inline-block px-1 text-xs font-bold"
      style={{ color: '#fff7e0', background: info.color, border: '2px solid #141312' }}
    >
      {info.name}
    </span>
  )
}

export function Stat({ label, value, className = '' }: { label: string; value: React.ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-baseline gap-1 ${className}`}>
      <span className="text-xs opacity-70">{label}</span>
      <span className="font-pixel text-lg leading-none">{value}</span>
    </span>
  )
}
