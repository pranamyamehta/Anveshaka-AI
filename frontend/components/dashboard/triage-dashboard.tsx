'use client'

import { useState } from 'react'
import { incidents } from '@/lib/incidents'
import { SystemHeader } from './system-header'
import { AlertQueue } from './alert-queue'
import { NodeContext } from './node-context'
import { AgentPanel } from './agent-panel'

export function TriageDashboard() {
  const [selectedId, setSelectedId] = useState(incidents[0].id)
  const selected = incidents.find((i) => i.id === selectedId) ?? incidents[0]

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-900">
      <SystemHeader />
      <main className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-[25fr_40fr_35fr] lg:p-6">
        <AlertQueue incidents={incidents} selectedId={selected.id} onSelect={setSelectedId} />
        <NodeContext incident={selected} />
        <AgentPanel incident={selected} />
      </main>
    </div>
  )
}
