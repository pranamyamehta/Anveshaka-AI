'use client'

import Image from 'next/image'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

import type { Incident } from '@/lib/incidents'

const INGEST_INTERVAL = 18

export function SystemHeader({ incidents = [] }: { incidents?: Incident[] }) {
  const fatalCount = incidents.filter(i => i.severity === 'fatal' && i.status !== 'resolved').length
  const criticalCount = incidents.filter(i => i.severity === 'critical' && i.status !== 'resolved').length
  const errorCount = incidents.filter(i => i.severity === 'error' && i.status !== 'resolved').length
  const warningCount = incidents.filter(i => i.severity === 'warning' && i.status !== 'resolved').length
  const infoCount = incidents.filter(i => i.severity === 'info' && i.status !== 'resolved').length
  const resolvedCount = incidents.filter(i => i.status === 'resolved').length

  const summary = [
    ...(fatalCount > 0 ? [{ label: 'Fatal', count: fatalCount, className: 'bg-gradient-to-r from-rose-700 to-violet-700 text-white border-transparent', dot: 'bg-white' }] : []),
    ...(criticalCount > 0 ? [{ label: 'Critical', count: criticalCount, className: 'bg-gradient-to-r from-red-600 to-orange-500 text-white border-transparent', dot: 'bg-white' }] : []),
    ...(errorCount > 0 ? [{ label: 'Error', count: errorCount, className: 'bg-gradient-to-r from-orange-500 to-rose-400 text-white border-transparent', dot: 'bg-white' }] : []),
    ...(warningCount > 0 ? [{ label: 'Warning', count: warningCount, className: 'bg-gradient-to-r from-amber-500 to-yellow-400 text-white border-transparent', dot: 'bg-white' }] : []),
    ...(infoCount > 0 ? [{ label: 'Info', count: infoCount, className: 'bg-gradient-to-r from-blue-500 to-cyan-400 text-white border-transparent', dot: 'bg-white' }] : []),
    { label: 'Resolved', count: resolvedCount, className: 'bg-gradient-to-r from-emerald-500 to-teal-500 text-white border-transparent', dot: 'bg-white' },
  ]
  const [seconds, setSeconds] = useState(INGEST_INTERVAL)

  useEffect(() => {
    const id = setInterval(() => {
      setSeconds((s) => (s <= 1 ? INGEST_INTERVAL : s - 1))
    }, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 lg:px-6">
        <div className="flex items-center gap-3">
          <Image
            src="/images/anvesaka-logo.png"
            alt="ANVESAKA logo"
            width={56}
            height={56}
            className="size-14 object-contain"
            priority
          />
          <div className="leading-tight">
            <p className="text-lg font-semibold tracking-[0.18em] text-[#0b2a5b]">ANVESAKA</p>
            <p className="text-xs text-slate-500">Infrastructure Incident Triage</p>
          </div>
        </div>

        <div
          className="order-3 flex w-full justify-center md:order-none md:w-auto"
          aria-live="polite"
        >
          <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm text-slate-700">
            <span className="relative flex size-2.5" aria-hidden="true">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex size-2.5 rounded-full bg-emerald-500" />
            </span>
            Next Ingest:
            <span className="font-mono font-medium tabular-nums text-slate-900">{seconds}s</span>
          </div>
        </div>

        <ul className="flex items-center gap-2" aria-label="Fleet health summary">
          {summary.map((s) => (
            <li
              key={s.label}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium',
                s.className,
              )}
            >
              <span className={cn('size-1.5 rounded-full', s.dot)} aria-hidden="true" />
              <span className="font-mono">{s.count}</span> {s.label}
            </li>
          ))}
        </ul>
      </div>
    </header>
  )
}
