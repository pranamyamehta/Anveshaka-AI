import {
  Activity,
  AlertTriangle,
  Cpu,
  Fan,
  Gauge,
  HardDrive,
  Server,
  Terminal,
  Thermometer,
  Wind,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Incident, Metric, Status } from '@/lib/incidents'

const icons: Record<Metric['icon'], LucideIcon> = {
  thermometer: Thermometer,
  fan: Fan,
  wind: Wind,
  zap: Zap,
  cpu: Cpu,
  'hard-drive': HardDrive,
  gauge: Gauge,
  activity: Activity,
}

const statusBadge: Record<Status, string> = {
  critical: 'bg-red-50 text-red-700 border-red-200',
  warning: 'bg-amber-50 text-amber-700 border-amber-200',
  nominal: 'bg-emerald-50 text-emerald-700 border-emerald-200',
}

const statusValue: Record<Status, string> = {
  critical: 'text-red-700',
  warning: 'text-amber-700',
  nominal: 'text-slate-900',
}

function MetricCard({ metric }: { metric: Metric }) {
  const Icon = icons[metric.icon]
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-slate-500">{metric.label}</p>
        <Icon className="size-4 text-slate-400" aria-hidden="true" />
      </div>
      <p className={cn('mt-3 font-mono text-2xl font-semibold tabular-nums', statusValue[metric.status])}>
        {metric.value}
        {metric.unit && <span className="ml-1 text-base font-medium text-slate-500">{metric.unit}</span>}
      </p>
      <span
        className={cn(
          'mt-3 inline-flex rounded border px-1.5 py-0.5 text-[11px] font-medium',
          statusBadge[metric.status],
        )}
      >
        {metric.badge}
      </span>
    </div>
  )
}

export function NodeContext({ incident }: { incident: Incident }) {
  return (
    <section aria-labelledby="node-heading" className="flex flex-col gap-4">
      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2">
          <Server className="size-4 text-slate-500" aria-hidden="true" />
          <h2 id="node-heading" className="text-sm font-semibold text-slate-900">
            Node: <span className="font-mono">{incident.node}</span>
            <span className="mx-2 text-slate-300">|</span>
            <span className="font-mono text-slate-600">{incident.rack}</span>
          </h2>
        </div>
        <div
          role="alert"
          className={cn(
            "mt-3 flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium",
            incident.status === 'resolved' 
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700"
          )}
        >
          <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
          {incident.bannerText}
          <span className={cn(
            "ml-auto font-mono text-xs font-normal",
            incident.status === 'resolved' ? "text-emerald-600" : "text-red-600"
          )}>
            {incident.id}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {incident.metrics.map((m) => (
          <MetricCard key={m.label} metric={m} />
        ))}
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900 shadow-sm">
        <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-2">
          <Terminal className="size-3.5 text-slate-400" aria-hidden="true" />
          <p className="text-xs font-medium text-slate-300">Raw Syslog</p>
          <span className="ml-auto font-mono text-[11px] text-slate-500">tail -f /var/log/ingest</span>
        </div>
        <pre className="overflow-x-auto whitespace-pre-wrap break-words p-4 font-mono text-sm leading-relaxed text-slate-200">
          {incident.syslog.map((line) => (
            <code key={line} className="block">
              <span className="select-none text-emerald-400">{'$ '}</span>
              {line}
            </code>
          ))}
        </pre>
      </div>
    </section>
  )
}
