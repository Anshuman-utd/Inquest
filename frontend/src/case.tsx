import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowLeft, ClipboardCheck, ChevronRight, FlaskConical, Play, Wrench } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { ApiError, post, request, type Schema } from './api'
import { useInvestigationStream, type Entry } from './stream'
import { amount, Button, ConfirmDialog, Empty, Failure, human, PageHeading, percent, short, Skeleton, Status, timestamp } from './ui'

type Detail = Schema['CaseDetail']
type DecisionPayload = Schema['DecisionRequest']

function Summary({ data }: { data: Detail }) {
  return <section className="panel section">
    <h2>Transaction</h2>
    <dl className="facts-grid">
      <div><dt>Transaction</dt><dd className="mono">TX-{data.source_sequence}</dd></div>
      <div><dt>Amount</dt><dd className="mono">{amount(data.amount_minor, data.currency)}</dd></div>
      <div><dt>Customer</dt><dd><Link to={`/explorer?customer=${encodeURIComponent(data.customer_id)}&through=${data.source_sequence}`}>{data.customer}</Link></dd></div>
      <div><dt>Merchant</dt><dd>{data.merchant}</dd></div>
      <div><dt>Channel</dt><dd>{data.channel.toUpperCase()} · {human(data.flow)}</dd></div>
      <div><dt>Attempt</dt><dd>{data.declined ? 'Declined' : 'Accepted'}</dd></div>
      <div><dt>Location</dt><dd>{data.city || 'Remote'}</dd></div>
      <div><dt>Device</dt><dd className="mono">{data.device_id}</dd></div>
      <div><dt>Transaction time (IST)</dt><dd>{timestamp(data.occurred_at)}</dd></div>
      <div><dt>Replay</dt><dd className="mono" title={data.replay_id}>{short(data.replay_id)}</dd></div>
    </dl>
  </section>
}

function Contributions({ data }: { data: Detail }) {
  const maximum = Math.max(...data.contributions.map(row => Math.abs(row.raw_margin_delta)), 0.001)
  return <section className="panel section risk-panel">
    <div className="section-heading">
      <div><h2>Risk score</h2><p>Alert threshold {percent(data.threshold, 3)}</p></div>
      <strong className="score mono">{percent(data.score, 2)}</strong>
    </div>
    <div className="contribution-label"><h3>Top risk drivers</h3><span>Signed model contribution</span></div>
    {!data.contributions.length && <Empty title="No risk drivers recorded" />}
    {!!data.contributions.length && <ul className="contributions" aria-label="Top model feature contributions">
      {data.contributions.map(row => <li key={row.feature}>
        <span>{human(row.feature)}</span>
        <span className="contribution-track" aria-hidden>
          <i className={row.raw_margin_delta < 0 ? 'negative' : 'positive'} style={{ width: `${Math.abs(row.raw_margin_delta) / maximum * 50}%` }} />
        </span>
        <span className="mono numeric">{row.raw_margin_delta >= 0 ? '+' : ''}{row.raw_margin_delta.toFixed(3)}</span>
      </li>)}
    </ul>}
    <p className="muted caption">TreeSHAP raw-margin units · <span className="mono">{data.model_version}</span></p>
  </section>
}

function decisionKey(previous: { body: string; key: string } | null, body: DecisionPayload) {
  const serialized = JSON.stringify(body)
  return previous?.body === serialized ? previous : { body: serialized, key: crypto.randomUUID() }
}

function DecisionForm({ data, current, recommendation, onRecorded }: {
  data: Detail; current: Schema['Snapshot']; recommendation: Schema['Report']['recommended_action']; onRecorded: () => void
}) {
  const [operation, choose] = useState<DecisionPayload['operation']>('approve')
  const [requestedAction, setAction] = useState<NonNullable<DecisionPayload['action']>>('block')
  const allowedActions = (['block', 'release', 'escalate'] as const).filter(value => value !== recommendation)
  const action = allowedActions.includes(requestedAction) ? requestedAction : allowedActions[0]
  const [confirmation, setConfirmation] = useState<DecisionPayload | null>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const outcome = operation === 'approve' ? recommendation : operation === 'escalate' ? 'escalate' : action
  const [note, setNote] = useState('')
  const idempotency = useRef<{ body: string; key: string } | null>(null)
  const cache = useQueryClient()
  const mutation = useMutation({
    mutationFn: (payload: DecisionPayload) => {
      idempotency.current = decisionKey(idempotency.current, payload)
      return post<Schema['Recorded']>(`/investigations/${data.investigation_id}/decision`, payload, idempotency.current.key)
    },
    onSuccess: () => { dialog.current?.close(); setConfirmation(null); onRecorded() },
    onError: error => {
      if (error instanceof ApiError && error.status === 409) {
        void cache.invalidateQueries({ queryKey: ['case', data.case_id] })
        void cache.invalidateQueries({ queryKey: ['investigation', data.investigation_id] })
      }
    },
  })

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    mutation.reset()
    setConfirmation({
      operation, expected_case_version: current.case_version, note,
      action: operation === 'override' ? action : undefined,
    })
    dialog.current?.showModal()
  }

  function dismiss() {
    dialog.current?.close()
    setConfirmation(null)
    mutation.reset()
  }

  const choices = [
    ['approve', 'Approve recommendation', `Accept the agent’s recommendation to ${recommendation}.`],
    ['override', 'Override', 'Record a different disposition.'],
    ['escalate', 'Escalate', 'Mark this case for further review.'],
  ] as const

  return <form className="decision-form" onSubmit={submit} aria-labelledby="analyst-decision">
    <fieldset disabled={mutation.isPending}>
      <legend id="analyst-decision" tabIndex={-1}>Analyst decision</legend>
      <div className="decision-options">
        {choices.map(([value, label, description]) => <label key={value}>
          <input type="radio" name="decision" checked={operation === value} onChange={() => choose(value)} aria-label={label} />
          <span><strong>{label}</strong><small>{description}</small></span>
        </label>)}
      </div>
      {operation === 'override' && <label className="stack-label">Override disposition
        <select value={action} onChange={event => setAction(event.target.value as typeof action)}>
          {allowedActions.map(value => <option key={value} value={value}>{human(value)}</option>)}
        </select>
      </label>}
      <label className="stack-label">Analyst notes <span className="muted">(optional)</span>
        <textarea rows={3} value={note} maxLength={1000} onChange={event => setNote(event.target.value)} aria-describedby="synthetic-disclaimer" />
      </label>
      <p id="synthetic-disclaimer" className="synthetic-notice">Synthetic data only. Don’t enter real personal data.</p>
      <div className="button-row decision-actions">
        <Button variant="primary" type="submit" icon={<ClipboardCheck />}>Record decision</Button>
      </div>
    </fieldset>
    <ConfirmDialog dialogRef={dialog} title="Confirm analyst decision"
      description={`This records ${outcome} as the disposition for this synthetic transaction.`}
      confirm={`Confirm ${outcome}`} caution={outcome === 'block'} busy={mutation.isPending}
      onCancel={dismiss} onConfirm={() => { if (confirmation && !mutation.isPending) mutation.mutate(confirmation) }}
      error={mutation.error instanceof ApiError && mutation.error.status === 409
        ? new Error('The case changed while you were reviewing it. Loading the latest status.')
        : mutation.error} />
  </form>
}

function RecordedDecision({ data }: { data: Schema['RecordedDecision'] }) {
  return <section className="recorded-section">
    <h3>Recorded decision</h3>
    <p><Status value={data.disposition} /> · {human(data.operation)}</p>
    <p className="muted">Analyst <span className="mono" title={data.analyst_id}>{short(data.analyst_id)}</span> · {timestamp(data.created_at)} IST</p>
    {data.note?.trim() && <p className="recorded-note">{data.note}</p>}
  </section>
}

const streamLabels = {
  connecting: 'Connecting…', live: 'Receiving events', reconnecting: 'Reconnecting…',
  settled: 'Up to date', unavailable: 'Timeline unavailable',
}

function eventLabel(entry: Entry) {
  switch (entry.kind) {
    case 'queued': return 'Investigation queued'
    case 'triage': return 'Model score loaded'
    case 'tool_started': return human(entry.payload.input.tool)
    case 'tool_observed': {
      const result = entry.payload.result
      return human('observation' in result ? result.observation.tool : result.tool)
    }
    case 'recording_used': return 'Recorded recommendation loaded'
    case 'recording_unavailable': return 'Recording unavailable'
    case 'report_ready': return 'Report ready for review'
    case 'decision_recorded': return 'Analyst decision recorded'
    case 'completed': return 'Investigation completed'
    case 'failed': return 'Investigation failed'
  }
}

function Timeline({ entries, connection, register }: {
  entries: Entry[]; connection: keyof typeof streamLabels; register: (id: string, node: HTMLDetailsElement | null) => void
}) {
  const inputs = new Map(entries.flatMap(entry => entry.kind === 'tool_started'
    ? [[entry.payload.call_sequence, entry] as const] : []))
  const observed = new Set(entries.flatMap(entry => entry.kind === 'tool_observed' ? [entry.payload.result.call_sequence] : []))
  return <section className="panel section timeline">
    <div className="section-heading"><h2>Investigation timeline</h2><output className="stream-status" data-connection={connection}>{streamLabels[connection]}</output></div>
    {!entries.length && <p className="muted">Waiting for investigation events.</p>}
    <ol>
      {entries.map(entry => {
        if (entry.kind === 'tool_started' && observed.has(entry.payload.call_sequence)) return null
        if (entry.kind === 'tool_observed') {
          const result = entry.payload.result
          const input = inputs.get(result.call_sequence)?.payload.input
          return <li key={inputs.get(result.call_sequence)?.id || entry.id}>
            <details ref={node => register(result.evidence_id, node)}>
              <summary><ChevronRight size={15} aria-hidden /><Wrench size={15} aria-hidden />
                <span>{eventLabel(entry)}</span><span className="timeline-meta">{human(result.status)}</span>
              </summary>
              <div className="evidence-body">
                <p className="mono muted">Evidence {short(result.evidence_id)}</p>
                {input && <><h3>Validated input</h3><pre>{JSON.stringify(input, null, 2)}</pre></>}
                <h3>Observation</h3>
                <pre>{JSON.stringify('observation' in result ? result.observation : { reason: result.reason }, null, 2)}</pre>
              </div>
            </details>
          </li>
        }
        return <li key={entry.id} className="timeline-entry">
          <span className="event-dot" aria-hidden /><span>{eventLabel(entry)}</span>
          {'summary' in entry.payload && <small>{entry.payload.summary}</small>}
        </li>
      })}
    </ol>
  </section>
}

function Investigation({ data, run }: { data: Detail; run: string }) {
  const [renewal, renew] = useState(0)
  const evidence = useRef(new Map<string, HTMLDetailsElement>())
  const cache = useQueryClient()
  const snapshot = useQuery({
    queryKey: ['investigation', run],
    queryFn: () => request<Schema['Snapshot']>(`/investigations/${run}`),
    refetchInterval: query => ['queued', 'running', 'resume'].includes(query.state.data?.status || '') ? 2500 : false,
  })
  const stream = useInvestigationStream(run, renewal, data.case_id)
  const current = snapshot.data
  const report = current?.report

  function register(id: string, node: HTMLDetailsElement | null) {
    if (node) evidence.current.set(id, node)
    else evidence.current.delete(id)
  }
  function cite(id: string) {
    const target = evidence.current.get(id)
    if (target) {
      target.open = true
      target.querySelector('summary')?.focus({ preventScroll: true })
      target.scrollIntoView({ block: 'nearest' })
    }
  }
  function onRecorded() {
    renew(count => count + 1)
    void cache.invalidateQueries({ queryKey: ['case', data.case_id] })
    void snapshot.refetch()
  }

  return <div className="case-columns">
    <Timeline {...stream} register={register} />
    <section className="panel section report">
      <div className="section-heading">
        <h2 id="agent-recommendation" tabIndex={-1}>Agent recommendation</h2>
        {current && <span className="tag">{human(current.mode)} mode</span>}
      </div>
      {snapshot.error && <Failure error={snapshot.error} retry={() => void snapshot.refetch()} />}
      {!report && !snapshot.error && (current?.status === 'failed'
        ? <Empty title="Investigation failed">Start a new investigation to try again.</Empty>
        : <Empty title="Report pending">The report will appear when the investigation is ready for review.</Empty>)}
      {report && <>
        <div className="report-summary">
          <Status value={report.verdict} />
          <span className="muted">{human(report.status)}{report.reason ? ` · ${human(report.reason)}` : ''}</span>
        </div>
        <dl className="facts-grid compact">
          <div><dt>Recommended action</dt><dd>{human(report.recommended_action)}</dd></div>
          <div><dt>Confidence</dt><dd className="mono">{percent(report.confidence, 0)}</dd></div>
        </dl>
        {!!report.evidence.length && <div className="evidence-list">
          <h3>Evidence citations</h3>
          <ul>{report.evidence.map(fact => <li key={`${fact.evidence_id}:${fact.field}`}>
            <button type="button" className="citation" onClick={() => cite(fact.evidence_id)}
              disabled={!stream.entries.some(entry => entry.kind === 'tool_observed' && entry.payload.result.evidence_id === fact.evidence_id)}>
              <span className="mono">{short(fact.evidence_id)}</span> {human(fact.field.split('.').join(' · '))}
            </button>
            <span className="fact-value">{String(fact.value)}</span>
          </li>)}</ul>
        </div>}
      </>}
      {data.decision && <RecordedDecision data={data.decision} />}
      {report && current?.status === 'review' && !data.decision && <DecisionForm data={data} current={current} recommendation={report.recommended_action} onRecorded={onRecorded} />}
    </section>
  </div>
}

export function CasePage() {
  const { caseId = '' } = useParams()
  const location = useLocation()
  const cache = useQueryClient()
  const startKey = useRef<{ caseId: string; value: string } | null>(null)
  const query = useQuery({
    queryKey: ['case', caseId], queryFn: () => request<Detail>(`/cases/${caseId}`),
  })
  const start = useMutation({
    mutationFn: () => {
      if (startKey.current?.caseId !== caseId) startKey.current = { caseId, value: crypto.randomUUID() }
      return post<Schema['Started']>(`/cases/${caseId}/investigations`, undefined, startKey.current.value)
    },
    onSuccess: value => {
      startKey.current = null
      cache.setQueryData<Detail>(['case', caseId], prior => prior && ({
        ...prior, status: 'investigating', investigation_id: value.investigation_id,
      }))
      void query.refetch()
      void cache.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: error => {
      if (error instanceof ApiError && error.status === 409) void query.refetch()
    },
  })
  const data = query.data

  return <>
    <Link className="back-link" to={`/${location.state?.queue || ''}`}><ArrowLeft size={15} aria-hidden />Back to case queue</Link>
    {query.isPending && <div className="panel"><Skeleton text="Loading case…" /></div>}
    {query.error && <Failure error={query.error} retry={() => void query.refetch()} />}
    {data && <>
      <PageHeading title={`Case ${short(data.case_id)}`} description={`TX-${data.source_sequence} · ${data.merchant}`}>
        <div className="button-row case-heading-actions">
          <Status value={data.disposition || data.status} />
          {data.status === 'queued' && <Button variant="primary" icon={<Play />} onClick={() => start.mutate()} busy={start.isPending}>Start investigation</Button>}
          {data.status === 'review' && !data.decision && <Button variant="link" icon={<ArrowDown />} onClick={() => {
            const target = document.getElementById('analyst-decision') || document.getElementById('agent-recommendation')
            target?.focus()
          }}>Review decision</Button>}
        </div>
      </PageHeading>
      {start.error && <Failure error={start.error} />}
      <div className="case-columns top-case"><Summary data={data} /><Contributions data={data} /></div>
      {data.investigation_id
        ? <Investigation key={data.investigation_id} data={data} run={data.investigation_id} />
        : <section className="panel section idle-investigation"><FlaskConical size={22} aria-hidden />
          <div><h2>Investigation</h2><p className="muted">Start an investigation to gather evidence and prepare a recommendation.</p></div>
        </section>}
    </>}
  </>
}
