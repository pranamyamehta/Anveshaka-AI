'use client'

import { useState, useEffect } from 'react'
import { incidents as fallbackIncidents, Incident, AgentStep } from '@/lib/incidents'
import { SystemHeader } from './system-header'
import { AlertQueue } from './alert-queue'
import { NodeContext } from './node-context'
import { AgentPanel } from './agent-panel'

export function TriageDashboard() {
  const [liveIncidents, setLiveIncidents] = useState<Incident[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    const eventSource = new EventSource('http://localhost:8000/events')
    
    eventSource.addEventListener('alert_received', (e) => {
      try {
        const data = JSON.parse(e.data)
        const alertId = data.alert_id

        // For demo visual variety, predictably assign a severity based on the ID's last character
        const severityMap: Record<string, any> = {
          '0': 'critical', '1': 'warning', '2': 'error', '3': 'info', '4': 'fatal',
          '5': 'critical', '6': 'warning', '7': 'error', '8': 'info', '9': 'fatal'
        }
        const lastChar = alertId.slice(-1)
        const demoSeverity = severityMap[lastChar] || (data.severity ? data.severity.toLowerCase() : 'warning')
        
        const newIncident: Incident = {
          id: alertId,
          severity: demoSeverity,
          node: data.node_id || 'unknown-node',
          rack: data.rack_id || 'unknown-rack',
          type: 'System',
          snippet: data.raw_message ? data.raw_message.substring(0, 60) + '...' : '',
          receivedAgo: 'Just now',
          bannerText: 'Investigation Pending',
          metrics: [],
          syslog: data.raw_message ? [data.raw_message] : [],
          steps: [
            {
              kind: 'text',
              title: 'Triage Pending',
              body: 'Alert queued for LangGraph agent investigation...'
            }
          ]
        }
        
        setLiveIncidents((prev) => [newIncident, ...prev])
        setSelectedId((current) => current === null ? newIncident.id : current)
        
        // Queue it for analysis
        fetch(`http://localhost:8000/alerts/${alertId}/analyze`, { method: 'POST' })
          .then(() => {
            // Fetch the completed triage result
            return fetch(`http://localhost:8000/triage/${alertId}`)
          })
          .then((res) => res.json())
          .then((triage) => {
            if (triage && !triage.error) {
              setLiveIncidents((prev) => prev.map(inc => {
                if (inc.id === alertId) {
                  const steps: AgentStep[] = []
                  if (triage.tool_trace) {
                    triage.tool_trace.forEach((t: any) => {
                      steps.push({
                        kind: 'tool',
                        title: t.tool,
                        call: t.summary || JSON.stringify(t.args)
                      })
                    })
                  }
                  if (triage.matched_incident_id) {
                    steps.push({
                      kind: 'match',
                      title: 'Root Cause Match',
                      incidentId: triage.matched_incident_id,
                      body: triage.root_cause
                    })
                  }
                  if (triage.recommended_steps && triage.recommended_steps.length > 0) {
                    steps.push({
                      kind: 'plan',
                      title: 'Action Plan',
                      actions: triage.recommended_steps.map((s: string) => ({ text: s }))
                    })
                  }
                  
                  return {
                    ...inc,
                    bannerText: triage.decision === 'escalate_unknown' ? 'Escalation Required' : 'Resolution Planned',
                    steps: steps.length > 0 ? steps : inc.steps,
                    metrics: triage.evidence ? triage.evidence.map((ev: string) => ({
                      label: ev.split('=')[0] || 'Evidence',
                      value: ev.split('=')[1] || ev,
                      unit: '', badge: '', status: 'nominal', icon: 'activity'
                    })) : inc.metrics
                  }
                }
                return inc
              }))
            }
          })
          .catch((err) => console.error("Triage fetch failed", err))

      } catch (err) {
        console.error('Failed to parse SSE event', err)
      }
    })

    return () => {
      eventSource.close()
    }
  }, [])

  const displayIncidents = liveIncidents.length > 0 ? liveIncidents : fallbackIncidents
  const selected = displayIncidents.find((i) => i.id === selectedId) ?? displayIncidents[0]

  const handleResolve = (id: string) => {
    setLiveIncidents((prev) => prev.map(inc => {
      if (inc.id === id) {
        return {
          ...inc,
          status: 'resolved',
          bannerText: 'Incident Resolved',
        }
      }
      return inc
    }))
  }

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-900">
      <SystemHeader incidents={displayIncidents} />
      <main className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-[25fr_40fr_35fr] lg:p-6">
        <AlertQueue incidents={displayIncidents} selectedId={selected?.id || ''} onSelect={setSelectedId} />
        <NodeContext incident={selected} />
        <AgentPanel incident={selected} onResolve={handleResolve} />
      </main>
    </div>
  )
}

