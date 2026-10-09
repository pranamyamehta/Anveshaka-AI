export type Severity = 'fatal' | 'critical' | 'error' | 'warning' | 'info'
export type Status = 'critical' | 'warning' | 'nominal'

export type Metric = {
  label: string
  value: string
  unit: string
  badge: string
  status: Status
  icon: 'thermometer' | 'fan' | 'wind' | 'zap' | 'cpu' | 'hard-drive' | 'gauge' | 'activity'
}

export type AgentStep =
  | { kind: 'text'; title: string; body: string }
  | { kind: 'tool'; title: string; call: string }
  | { kind: 'match'; title: string; incidentId: string; body: string }
  | { kind: 'plan'; title: string; actions: { text: string; code?: string; after?: string }[] }

export type Incident = {
  id: string
  severity: Severity
  node: string
  rack: string
  type: string
  snippet: string
  receivedAgo: string
  bannerText: string
  metrics: Metric[]
  syslog: string[]
  steps: AgentStep[]
  status?: 'pending' | 'resolved'
}

export const incidents: Incident[] = [
  {
    id: 'ALT-90412',
    severity: 'critical',
    node: 'srv-node-45',
    rack: 'Rack-A12',
    type: 'Thermal',
    snippet: 'Fan 2 stalled (0 RPM) & PROCHOT asserted',
    receivedAgo: '12s ago',
    bannerText: 'Thermal Throttling Active',
    metrics: [
      { label: 'CPU Package Temp', value: '96.4', unit: '°C', badge: '+35.2°C vs Baseline', status: 'critical', icon: 'thermometer' },
      { label: 'Chassis Fan Speed', value: '0', unit: 'RPM', badge: 'STALLED < 2000 RPM', status: 'critical', icon: 'fan' },
      { label: 'Cold Aisle Inlet', value: '23.5', unit: '°C', badge: 'ASHRAE Compliant', status: 'nominal', icon: 'wind' },
      { label: 'Power Draw', value: '392', unit: 'W', badge: 'Nominal Draw', status: 'nominal', icon: 'zap' },
    ],
    syslog: [
      'Zabbix: PROBLEM: Fan 2 stalled (0RPM) and CPU1 PROCHOT asserted on srv-node-45 | CPU1 Temp=96.4C Inlet=23.5C',
    ],
    steps: [
      {
        kind: 'text',
        title: 'Correlation',
        body: 'Detected CPU temp > 85°C with 0 RPM fan speed. Ambient inlet is normal (23.5°C). Localized hardware fault likely.',
      },
      {
        kind: 'tool',
        title: 'Tool Execution',
        call: 'tool_call: query_playbook(category="Thermal", signature="fan_rpm < 2000")',
      },
      {
        kind: 'match',
        title: 'Root Cause Match',
        incidentId: 'INC-4731',
        body: 'Matched Historical Incident: Chassis fan module 2 bearing failure and rotor seizure.',
      },
      {
        kind: 'plan',
        title: 'Action Plan',
        actions: [
          { text: 'Cordon ', code: 'srv-node-45', after: ' via Kubernetes API.' },
          { text: 'Drain active workloads.' },
          { text: 'Apply 250W temporary BMC power cap.' },
          { text: 'Dispatch field technician with replacement FRU.' },
        ],
      },
    ],
  },
  {
    id: 'ALT-90398',
    severity: 'warning',
    node: 'srv-node-401',
    rack: 'Rack-C04',
    type: 'Compute',
    snippet: 'Sustained CPU steal time 38% across 12 vCPUs',
    receivedAgo: '1m ago',
    bannerText: 'Compute Contention Detected',
    metrics: [
      { label: 'CPU Steal Time', value: '38.2', unit: '%', badge: '+31.0% vs Baseline', status: 'warning', icon: 'cpu' },
      { label: 'Load Average (5m)', value: '41.7', unit: '', badge: 'Above 32-core cap', status: 'warning', icon: 'activity' },
      { label: 'CPU Package Temp', value: '68.1', unit: '°C', badge: 'Within Envelope', status: 'nominal', icon: 'thermometer' },
      { label: 'Power Draw', value: '418', unit: 'W', badge: 'Nominal Draw', status: 'nominal', icon: 'zap' },
    ],
    syslog: [
      'Prometheus: WARN: node_cpu_steal_ratio=0.382 on srv-node-401 (10.42.7.18) for 15m | load5=41.7 cores=32',
    ],
    steps: [
      {
        kind: 'text',
        title: 'Correlation',
        body: 'High steal time with healthy thermals and power. Contention originates from co-located noisy-neighbor VMs, not hardware.',
      },
      {
        kind: 'tool',
        title: 'Tool Execution',
        call: 'tool_call: query_playbook(category="Compute", signature="cpu_steal > 0.30")',
      },
      {
        kind: 'match',
        title: 'Root Cause Match',
        incidentId: 'INC-3902',
        body: 'Matched Historical Incident: Over-subscribed hypervisor after batch job autoscale event.',
      },
      {
        kind: 'plan',
        title: 'Action Plan',
        actions: [
          { text: 'Identify top-3 vCPU consumers on ', code: 'srv-node-401', after: '.' },
          { text: 'Live-migrate batch VMs to Rack-C07 pool.' },
          { text: 'Lower overcommit ratio to 1.5:1.' },
          { text: 'Monitor steal time for 30 minutes.' },
        ],
      },
    ],
  },
  {
    id: 'ALT-90377',
    severity: 'error',
    node: 'srv-node-203',
    rack: 'Rack-B09',
    type: 'Storage',
    snippet: 'NVMe2 media errors rising, SMART pre-fail',
    receivedAgo: '3m ago',
    bannerText: 'Storage Degradation Detected',
    metrics: [
      { label: 'NVMe2 Media Errors', value: '1,284', unit: '', badge: '+1,240 in 1h', status: 'critical', icon: 'hard-drive' },
      { label: 'Read Latency p99', value: '48.6', unit: 'ms', badge: '12x Baseline', status: 'warning', icon: 'gauge' },
      { label: 'Drive Temp', value: '44.0', unit: '°C', badge: 'Within Envelope', status: 'nominal', icon: 'thermometer' },
      { label: 'Power Draw', value: '305', unit: 'W', badge: 'Nominal Draw', status: 'nominal', icon: 'zap' },
    ],
    syslog: [
      'smartd: Device /dev/nvme2n1 on srv-node-203 (10.42.3.9): media_errors=1284 critical_warning=0x04 | RAID-10 degraded',
    ],
    steps: [
      {
        kind: 'text',
        title: 'Correlation',
        body: 'Rapid growth of media errors on a single NVMe with normal temperature. Isolated device wear-out, array still serving reads.',
      },
      {
        kind: 'tool',
        title: 'Tool Execution',
        call: 'tool_call: query_playbook(category="Storage", signature="media_errors_rate > 500/h")',
      },
      {
        kind: 'match',
        title: 'Root Cause Match',
        incidentId: 'INC-4208',
        body: 'Matched Historical Incident: NAND endurance exhaustion on Gen3 NVMe batch #7731.',
      },
      {
        kind: 'plan',
        title: 'Action Plan',
        actions: [
          { text: 'Mark ', code: '/dev/nvme2n1', after: ' as failed in mdadm.' },
          { text: 'Trigger RAID-10 rebuild onto hot spare.' },
          { text: 'Throttle replica rebalancing to 200 MB/s.' },
          { text: 'Open RMA for drive serial and schedule swap.' },
        ],
      },
    ],
  },
  {
    id: 'ALT-90351',
    severity: 'critical',
    node: 'srv-node-118',
    rack: 'Rack-A03',
    type: 'Power',
    snippet: 'PSU1 input lost, running on single supply',
    receivedAgo: '6m ago',
    bannerText: 'Power Redundancy Lost',
    metrics: [
      { label: 'PSU1 Input Voltage', value: '0', unit: 'V', badge: 'INPUT LOST', status: 'critical', icon: 'zap' },
      { label: 'PSU2 Load', value: '91', unit: '%', badge: 'Near Capacity', status: 'warning', icon: 'gauge' },
      { label: 'CPU Package Temp', value: '71.3', unit: '°C', badge: 'Within Envelope', status: 'nominal', icon: 'thermometer' },
      { label: 'Cold Aisle Inlet', value: '22.8', unit: '°C', badge: 'ASHRAE Compliant', status: 'nominal', icon: 'wind' },
    ],
    syslog: [
      'IPMI SEL: Power Supply PSU1 | AC lost | Asserted on srv-node-118 (10.42.1.66) | Redundancy Lost',
    ],
    steps: [
      {
        kind: 'text',
        title: 'Correlation',
        body: 'PSU1 shows zero input while adjacent nodes on PDU-A03-L are also reporting. Upstream PDU branch circuit fault likely.',
      },
      {
        kind: 'tool',
        title: 'Tool Execution',
        call: 'tool_call: query_playbook(category="Power", signature="psu_input_v == 0")',
      },
      {
        kind: 'match',
        title: 'Root Cause Match',
        incidentId: 'INC-3377',
        body: 'Matched Historical Incident: Tripped 20A breaker on PDU left bank after load imbalance.',
      },
      {
        kind: 'plan',
        title: 'Action Plan',
        actions: [
          { text: 'Apply 400W BMC power cap on ', code: 'srv-node-118', after: '.' },
          { text: 'Rebalance rack load to PDU-A03-R.' },
          { text: 'Notify facilities to inspect branch breaker.' },
          { text: 'Verify dual-feed redundancy restored.' },
        ],
      },
    ],
  },
]
