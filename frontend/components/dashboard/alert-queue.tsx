'use client'

import { useState } from 'react'
import { Radio } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Incident, Severity } from '@/lib/incidents'

type Filter = 'all' | 'critical' | 'warning'

const severityStyles: Record<Severity, string> = {
  critical: 'bg-red-50 text-red-700 border-red-200',
  warning: 'bg-amber-50 text-amber-700 border-amber-200',
  error: 'bg-red-50 text-red-700 border-red-200',
}

export function AlertQueue({
  incidents,
  selectedId,
  onSelect,
}: {
  incidents: Incident[]
  selectedId: string
  onSelect: (id: string) => void
}) {
  const [filter, setFilter] = useState<Filter>('all')

  const visible = incidents.filter((i) => {
    if (filter === 'all') return true
    if (filter === 'critical') return i.severity === 'critical' || i.severity === 'error'
    return i.severity === 'warning'
  })

  const filters: { id: Filter; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'critical', label: 'Critical' },
    { id: 'warning', label: 'Warning' },
  ]

  return (
    <section
      aria-labelledby="queue-heading"
      className="flex flex-col rounded-lg border border-slate-200 bg-white shadow-sm"
    >
      <div className="border-b border-slate-200 p-4">
        <div className="flex items-center gap-2">
          <Radio className="size-4 text-blue-600" aria-hidden="true" />
          <h2 id="queue-heading" className="text-sm font-semibold text-slate-900">
            Live Telemetry Stream
          </h2>
        </div>
        <div className="mt-3 flex gap-1.5" role="group" aria-label="Filter alerts">
          {filters.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              aria-pressed={filter === f.id}
              className={cn(
                'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                filter === f.id
                  ? 'border-slate-900 bg-slate-900 text-white'
                  : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <ul className="flex flex-col gap-2 p-3">
        {visible.map((incident) => {
          const active = incident.id === selectedId
          return (
            <li key={incident.id}>
              <button
                type="button"
                onClick={() => onSelect(incident.id)}
                aria-current={active ? 'true' : undefined}
                className={cn(
                  'w-full rounded-md border border-l-2 p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/40',
                  active
                    ? 'border-slate-200 border-l-blue-600 bg-blue-50/50'
                    : 'border-slate-200 border-l-transparent bg-white hover:bg-slate-50',
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={cn(
                      'rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
                      severityStyles[incident.severity],
                    )}
                  >
                    {incident.severity}
                  </span>
                  <span className="text-[11px] text-slate-400">{incident.receivedAgo}</span>
                </div>
                <p className="mt-2 text-sm text-slate-900">
                  <span className="font-mono font-medium">{incident.node}</span>
                  <span className="text-slate-400"> · </span>
                  <span className="font-mono text-slate-600">{incident.rack}</span>
                </p>
                <p className="mt-0.5 text-xs font-medium text-slate-500">{incident.type}</p>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{incident.snippet}</p>
              </button>
            </li>
          )
        })}
        {visible.length === 0 && (
          <li className="p-4 text-center text-xs text-slate-500">No alerts match this filter.</li>
        )}
      </ul>
    </section>
  )
}
