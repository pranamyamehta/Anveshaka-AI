'use client'

import { useState } from 'react'
import { Bot, CheckCircle2, GitMerge, ListChecks, Loader2, Sparkles, Wrench } from 'lucide-react'
import type { AgentStep, Incident } from '@/lib/incidents'

const AI_GRADIENT = 'bg-gradient-to-r from-blue-600 via-violet-600 to-pink-500'

const stepIcons = {
  text: GitMerge,
  tool: Wrench,
  match: CheckCircle2,
  plan: ListChecks,
}

function StepBody({ step }: { step: AgentStep }) {
  switch (step.kind) {
    case 'text':
      return <p className="text-sm leading-relaxed text-slate-600">{step.body}</p>
    case 'tool':
      return (
        <div className="rounded-md border border-violet-200 bg-violet-50/40 px-3 py-2">
          <code
            className={`${AI_GRADIENT} block break-words bg-clip-text font-mono text-xs font-medium text-transparent`}
          >
            {step.call}
          </code>
        </div>
      )
    case 'match':
      return <p className="text-sm leading-relaxed text-slate-600">{step.body}</p>
    case 'plan':
      return (
        <ol className="flex flex-col gap-1.5">
          {step.actions.map((a, i) => (
            <li key={i} className="flex gap-2 text-sm text-slate-600">
              <span className="font-mono text-xs font-semibold leading-5 text-slate-400">{i + 1}.</span>
              <span>
                {a.text}
                {a.code && (
                  <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-xs text-slate-800">
                    {a.code}
                  </code>
                )}
                {a.after}
              </span>
            </li>
          ))}
        </ol>
      )
  }
}

type AuthState = 'idle' | 'running' | 'done'

export function AgentPanel({ incident, onResolve }: { incident: Incident, onResolve?: (id: string) => void }) {
  const [auth, setAuth] = useState<{ id: string; state: AuthState }>({ id: incident.id, state: 'idle' })
  const state = auth.id === incident.id ? auth.state : 'idle'

  const authorize = () => {
    const id = incident.id
    setAuth({ id, state: 'running' })
    setTimeout(() => {
      setAuth((cur) => (cur.id === id ? { id, state: 'done' } : cur))
      if (onResolve) {
        onResolve(id)
      }
    }, 1800)
  }

  return (
    <section
      aria-labelledby="agent-heading"
      className="relative flex flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm"
    >
      <div className={`${AI_GRADIENT} h-0.5 w-full`} aria-hidden="true" />

      <div className="flex items-center justify-between gap-2 border-b border-slate-200 p-4">
        <div className="flex items-center gap-2">
          <Bot className="size-4 text-violet-600" aria-hidden="true" />
          <h2 id="agent-heading" className="text-sm font-semibold text-slate-900">
            LangGraph Triage Agent
          </h2>
        </div>
        <span className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 font-mono text-[11px] text-slate-600">
          Ollama / Llama-3
        </span>
      </div>

      <ol className="flex flex-col p-4">
        {incident.steps.map((step, i) => {
          const Icon = stepIcons[step.kind]
          const isLast = i === incident.steps.length - 1
          const isTool = step.kind === 'tool'
          return (
            <li key={step.title} className="relative flex gap-3 pb-5 last:pb-0">
              {!isLast && (
                <span className="absolute left-[13px] top-7 h-[calc(100%-1.75rem)] w-px bg-slate-200" aria-hidden="true" />
              )}
              <span
                className={
                  isTool
                    ? `${AI_GRADIENT} flex size-7 shrink-0 items-center justify-center rounded-full text-white`
                    : 'flex size-7 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600'
                }
              >
                <Icon className="size-3.5" aria-hidden="true" />
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-1.5 pt-0.5">
                <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
                  <span className="font-mono text-xs text-slate-400">0{i + 1}</span>
                  {step.title}
                  {step.kind === 'match' && (
                    <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                      {step.incidentId}
                    </span>
                  )}
                </p>
                <StepBody step={step} />
              </div>
            </li>
          )
        })}
      </ol>

      <div className="mt-auto border-t border-slate-200 p-4">
        {state === 'done' ? (
          <div
            role="status"
            className="flex items-center justify-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm font-medium text-emerald-700"
          >
            <CheckCircle2 className="size-4" aria-hidden="true" />
            Remediation authorized for <span className="font-mono">{incident.node}</span>
          </div>
        ) : (
          <button
            type="button"
            onClick={authorize}
            disabled={state === 'running'}
            className={`${AI_GRADIENT} flex w-full items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500 focus-visible:ring-offset-2 disabled:opacity-80`}
          >
            {state === 'running' ? (
              <>
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                Executing Playbook...
              </>
            ) : (
              <>
                <Sparkles className="size-4" aria-hidden="true" />
                Authorize Automated Remediation
              </>
            )}
          </button>
        )}
      </div>
    </section>
  )
}
