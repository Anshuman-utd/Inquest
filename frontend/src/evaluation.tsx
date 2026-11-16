import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { request, type Schema } from './api'
import { Empty, Failure, human, Loading, number, PageHeading, percent } from './ui'

const counts = (value: number) => number.format(value)
const scenarios = (value: string) => human(value).replace(/^Upi/, 'UPI')
const windows = { test: 'Fresh test', shift_test: 'Shifted test' }
const arms = {
  ml_only: 'ML only', full: 'Full agent', no_tools: 'No tools', no_policy: 'No policy', no_self_check: 'No self-check',
}
const date = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeZone: 'UTC' })
const seconds = (value: number | null) => value === null ? '—' : `${value.toFixed(2)} s`

function PrecisionRecall({ cohort }: { cohort: Schema['ScorerCohort'] }) {
  const x = (value: number) => 50 + value * 458
  const y = (value: number) => 210 - value * 182
  const line = cohort.pr_curve.map(point => `${x(point.recall)},${y(point.precision)}`).join(' ')
  const ticks = [0, 0.25, 0.5, 0.75, 1]
  return <section className="panel section pr">
    <div className="section-heading"><h2>Precision–recall</h2><span className="muted">AP {cohort.average_precision.toFixed(3)}</span></div>
    <svg viewBox="0 0 540 252" role="img" aria-label={`Precision–recall curve. Locked operating point: ${percent(cohort.recall)} recall, ${percent(cohort.precision)} precision.`}>
      {ticks.map(value => <g key={value}>
        <line x1={x(0)} x2={x(1)} y1={y(value)} y2={y(value)} className="grid-line" />
        <text x={x(0) - 10} y={y(value) + 4} textAnchor="end">{percent(value, 0)}</text>
        <text x={x(value)} y={230} textAnchor="middle">{percent(value, 0)}</text>
      </g>)}
      <text x="54" y="14">Precision</text><text x="511" y="247" textAnchor="end">Recall</text>
      <polyline points={line} className="pr-line" />
      <circle cx={x(cohort.recall)} cy={y(cohort.precision)} r={5} className="operating-point" />
    </svg>
    <p className="caption muted"><span className="point-legend" /> Locked threshold · {percent(cohort.recall)} recall · {percent(cohort.precision)} precision</p>
    <details className="chart-data">
      <summary>View chart data</summary>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Precision–recall points">
        <table><thead><tr><th scope="col">Recall</th><th scope="col">Precision</th></tr></thead>
          <tbody>{cohort.pr_curve.map(point => <tr key={point.recall}>
            <td>{percent(point.recall)}</td><td>{percent(point.precision)}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </details>
  </section>
}

function ScorerMetrics({ data }: { data: Schema['ScorerEvaluation'] }) {
  const [window, setWindow] = useState<keyof typeof windows>('test')
  const cohort = data.cohorts[window]
  return <section className="evaluation-section" aria-label="Scorer evaluation">
    <div className="section-heading evaluation-heading">
      <div><h2>Scorer performance</h2><p>{data.model_version} · Locked threshold {percent(data.threshold, 3)}</p></div>
      <select aria-label="Scorer cohort" value={window} onChange={event => setWindow(event.target.value as keyof typeof windows)}>
        {Object.entries(windows).map(([key, label]) => <option value={key} key={key}>{label}</option>)}
      </select>
    </div>
    {cohort ? <>
      <dl className="queue-stats">
        <div><dt>Fraud recall</dt><dd>{percent(cohort.recall)}</dd></div>
        <div><dt>Precision</dt><dd>{percent(cohort.precision)}</dd></div>
        <div><dt>Alerts per 1,000</dt><dd>{cohort.alerts_per_1000.toFixed(2)}</dd></div>
        <div><dt>Attempts</dt><dd>{counts(cohort.attempts)}</dd><small>{counts(cohort.fraud)} fraud attempts</small></div>
      </dl>
      <div className="evaluation-grid">
        <PrecisionRecall cohort={cohort} />
        <section className="panel section">
          <h2>Recall by scenario</h2>
          <div className="table-scroll scenario-scroll" role="region" tabIndex={0} aria-label="Scorer recall by fraud scenario">
            <table className="scenarios"><thead><tr><th scope="col">Scenario</th><th scope="col">Recall</th><th scope="col" className="numeric">Caught</th></tr></thead>
              <tbody>{Object.entries(cohort.scenarios).map(([key, scenario]) => <tr key={key}>
                <td>{scenarios(key)}</td>
                <td><span className="recall-meter" aria-hidden><i style={{ width: percent(scenario.recall, 0) }} /></span>{percent(scenario.recall, 0)}</td>
                <td className="mono numeric">{scenario.fraud ? `${scenario.caught}/${scenario.fraud}` : '—'}</td>
              </tr>)}</tbody>
            </table>
          </div>
        </section>
      </div>
    </> : <Empty title="Scorer cohort unavailable" />}
  </section>
}

function AgentMetrics({ reports }: { reports: Schema['EvaluationReport'][] }) {
  const [name, select] = useState(reports.find(report => report.cohort.name === 'held_out')?.cohort.name || reports[0]?.cohort.name)
  const selected = reports.find(report => report.cohort.name === name)
  if (!selected) return <Empty title="No published agent evaluations" />
  const cohort = selected.cohort
  const start = new Date(cohort.config.start)
  const end = new Date(start.getTime() + cohort.config.days * 86_400_000)
  return <section className="evaluation-section" aria-label="Agent evaluation">
    <div className="section-heading evaluation-heading">
      <div><h2>Agent ablations</h2><p>{date.format(start)} to {date.format(end)} UTC · {counts(cohort.attempts)} attempts · {counts(cohort.alerted)} alerts · {counts(cohort.alerted_fraud)}/{counts(cohort.fraud)} fraud alerted</p></div>
      <select aria-label="Agent cohort" value={name} onChange={event => select(event.target.value)}>
        {reports.map(report => <option key={report.cohort.name} value={report.cohort.name}>{human(report.cohort.name)}</option>)}
      </select>
    </div>
    <div className="panel">
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Agent ablation comparison">
        <table className="ablation">
          <thead><tr><th scope="col">Configuration</th><th scope="col">Sample</th><th scope="col">Legit alerts cleared</th>
            <th scope="col">Alerted fraud retained</th><th scope="col">Overall fraud retained</th>
            <th scope="col">Grounded</th><th scope="col">Median latency</th><th scope="col">Tokens</th></tr></thead>
          <tbody>{Object.entries(arms).map(([key, label]) => {
            const arm = selected.arms[key]
            if (!arm) return null
            const cacheOnly = arm.cache_only_latency.cases > 0 && arm.live_latency.cases === 0
            const failures = Object.values(arm.failure_codes).reduce((sum, value) => sum + value, 0)
            return <tr key={key}>
              <th scope="row">{label}{failures > 0 && <small className="muted">Partial · {failures} {failures === 1 ? 'failure' : 'failures'}</small>}</th>
              <td>{arm.sample_size}<small className="muted">{arm.sample_fraud} fraud</small></td>
              <td>{percent(arm.legit_alerts_cleared)}<small className="muted">{arm.sample_true_releases} sampled clears</small></td>
              <td>{percent(arm.alert_fraud_retained)}</td><td>{percent(arm.end_to_end_fraud_retained)}</td>
              <td>{arm.grounding_denominator ? `${arm.grounded_sample}/${arm.grounding_denominator}` : '—'}</td>
              <td>{seconds(cacheOnly ? arm.cache_only_latency.p50_seconds : arm.live_latency.p50_seconds)}
                {cacheOnly && <small className="muted">Cache only</small>}</td>
              <td>{counts(arm.accounted_tokens)}</td>
            </tr>
          })}</tbody>
        </table>
      </div>
      <p className="caption muted metric-footnote">— indicates an undefined or unavailable metric. Retention includes escalated fraud alerts.</p>
    </div>
  </section>
}

export function Evaluations() {
  const evaluation = useQuery({
    queryKey: ['evaluation'], queryFn: () => request<Schema['PublishedEvaluations']>('/evaluations'),
  })
  return <>
    <PageHeading title="Evaluation" description="Compare scorer and investigation performance on held-out synthetic cohorts." />
    {evaluation.isPending && <Loading text="Loading evaluation reports…" />}
    {evaluation.error && <Failure error={evaluation.error} retry={() => void evaluation.refetch()} />}
    {evaluation.data && <>
      {evaluation.data.scorer && <ScorerMetrics data={evaluation.data.scorer} />}
      <AgentMetrics reports={evaluation.data.reports} />
    </>}
  </>
}
