import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ArrowUpDown, ListFilter, Search, X } from 'lucide-react'
import { useDeferredValue, useRef } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { request, type QueueQuery, type Schema } from './api'
import { openSimulator, useSimulator } from './simulator'
import { amount, Button, Empty, Failure, number, PageHeading, percent, short, Skeleton, Status, timestamp, useDismissableDisclosure } from './ui'

const columns = [
  ['status', 'Status'], ['risk', 'Risk score'], ['amount', 'Amount'],
  ['merchant', 'Merchant'], ['channel', 'Channel'], ['time', 'Transaction time (IST)'],
] as const

const states = [
  ['queued', 'Queued'], ['investigating', 'Investigating'], ['review', 'Needs review'],
  ['resolved', 'Resolved'], ['escalated', 'Escalated'],
] as const

export function Queue() {
  const [search, setSearch] = useSearchParams()
  const navigate = useNavigate()
  const filterMenu = useRef<HTMLDetailsElement>(null)
  useDismissableDisclosure(filterMenu)
  const simulator = useSimulator()
  const deferred = useDeferredValue(search.toString())
  const params = new URLSearchParams(deferred)
  const data = useQuery({
    queryKey: ['cases', deferred],
    queryFn: () => request<Schema['CasePage']>(`/cases?${deferred}`),
    placeholderData: keepPreviousData,
    refetchInterval: simulator.data?.state === 'running' ? 1500 : 5000,
  })
  const sort = columns.find(([key]) => key === search.get('sort'))?.[0] || 'time'
  const direction = search.get('direction') === 'asc' ? 'asc' : 'desc'
  const filtersApplied = ['q', 'status', 'channel', 'min_score'].some(key => search.has(key))
  const counts = data.data?.counts
  const total = counts && Object.values(counts).reduce((sum, value) => sum + value, 0)
  const atFirstPage = !params.has('after')
  const refreshing = deferred !== search.toString() || data.isPlaceholderData

  function change(values: Partial<Record<keyof QueueQuery, string>>, replace = false) {
    setSearch(previous => {
      const next = new URLSearchParams(previous)
      next.delete('after')
      for (const [key, value] of Object.entries(values)) {
        if (value) next.set(key, value)
        else next.delete(key)
      }
      return next
    }, { replace })
  }

  return <>
    <PageHeading title="Case queue" description="Review flagged card and UPI payments." />
    <section className="panel queue" aria-label="Case queue">
      <dl className="queue-summary" aria-label="Workspace case counts">
        {[
          ['Total cases', total], ['Queued', counts?.queued], ['Investigating', counts?.investigating],
          ['Needs review', counts?.review],
        ].map(([label, value]) => <div key={label}>
          <dt>{label}</dt><dd>{counts ? number.format(Number(value || 0)) : '—'}</dd>
        </div>)}
      </dl>
      <div className="filters">
        <label className="search-field">
          <Search size={16} aria-hidden />
          <input aria-label="Search cases" placeholder="Search cases, transactions, or merchants" maxLength={100}
            value={search.get('q') || ''} onChange={event => change({ q: event.target.value }, true)} />
        </label>
        {search.has('q') && <Button variant="ghost" size="small" className="icon-button" aria-label="Clear search" title="Clear search" icon={<X />} onClick={() => change({ q: '' })} />}
        <details className="filter-menu" ref={filterMenu}>
          <summary className="button"><ListFilter aria-hidden />Filters</summary>
          <div className="filter-options">
            <label>Case status
              <select id="status-filter" value={search.get('status') || ''} onChange={event => change({ status: event.target.value })}>
                <option value="">All statuses</option>
                {states.map(([key, label]) => <option value={key} key={key}>{label}</option>)}
              </select>
            </label>
            <label>Payment channel
              <select id="channel-filter" value={search.get('channel') || ''} onChange={event => change({ channel: event.target.value })}>
                <option value="">All channels</option><option value="upi">UPI</option><option value="card">Card</option>
              </select>
            </label>
            <label>Minimum risk
              <select id="risk-filter" value={search.get('min_score') || ''} onChange={event => change({ min_score: event.target.value })}>
                <option value="">All risk scores</option><option value="0.01">Risk ≥ 1%</option>
                <option value="0.1">Risk ≥ 10%</option><option value="0.5">Risk ≥ 50%</option>
              </select>
            </label>
          </div>
        </details>
      </div>
      {filtersApplied && <div className="applied-filters" aria-label="Active filters">
        {search.has('q') && <span className="filter-chip">Search: {search.get('q')}</span>}
        {search.has('status') && <Button variant="ghost" size="small" className="filter-chip" icon={<X />} aria-label="Remove status filter" onClick={() => change({ status: '' })}>
          {states.find(([key]) => key === search.get('status'))?.[1] || 'Status'}
        </Button>}
        {search.has('channel') && <Button variant="ghost" size="small" className="filter-chip" icon={<X />} aria-label="Remove channel filter" onClick={() => change({ channel: '' })}>{search.get('channel') === 'upi' ? 'UPI' : 'Card'}</Button>}
        {search.has('min_score') && <Button variant="ghost" size="small" className="filter-chip" icon={<X />} aria-label="Remove risk filter" onClick={() => change({ min_score: '' })}>Risk ≥ {percent(Number(search.get('min_score')), 0)}</Button>}
        <Button variant="link" size="small" onClick={() => change({ q: '', status: '', channel: '', min_score: '' })}>Clear filters</Button>
      </div>}
      {data.isPending && <Skeleton className="queue-skeleton" text="Loading cases…" />}
      {data.error && <Failure error={data.error} retry={() => void data.refetch()} />}
      {data.data && data.data.items.length === 0 && !data.isPlaceholderData && (
        filtersApplied || !atFirstPage
          ? <Empty title="No matching cases">Change the filters or return to the first page.</Empty>
          : <Empty title="No cases yet">{simulator.data?.state === 'running'
            ? 'The simulator is scanning synthetic transactions.'
            : 'Start a transaction replay to populate the queue.'}</Empty>
      )}
      {data.data?.items.length === 0 && !data.isPlaceholderData && !filtersApplied && atFirstPage && simulator.data?.state !== 'running' &&
        <div className="queue-empty-action"><Button onClick={openSimulator}>Open simulator</Button></div>}
      {!!data.data?.items.length && (
        // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- the scrolling region needs keyboard access.
        <section className="table-scroll" tabIndex={0} aria-label="Case rows">
        <table className="case-table">
          <thead><tr>
            <th scope="col">Case / transaction</th>
            {columns.map(([key, label]) => {
              const active = sort === key
              const Icon = !active ? ArrowUpDown : direction === 'asc' ? ArrowUp : ArrowDown
              return <th scope="col" key={key} aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : undefined}
                className={key === 'risk' || key === 'amount' ? 'numeric' : undefined}>
                <button type="button" className="button ghost small sort-button" onClick={() => change({ sort: key, direction: active && direction === 'desc' ? 'asc' : 'desc' })}>
                  {label}<Icon size={13} aria-hidden />
                </button>
              </th>
            })}
          </tr></thead>
          <tbody>{data.data.items.map(row => <tr key={row.case_id}>
            <td><Link className="mono" to={`/cases/${row.case_id}`} onClick={event => {
              if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
              event.preventDefault()
              void navigate(`/cases/${row.case_id}`, { state: { queue: window.location.search } })
            }} aria-label={`Open case ${short(row.case_id)}, transaction ${row.source_sequence}`}>{short(row.case_id)}</Link>
              <small className="mono muted">TX-{row.source_sequence}</small></td>
            <td><Status value={row.disposition || row.status} /></td>
            <td className="numeric mono">{percent(row.score, 2)}</td>
            <td className="numeric">{amount(row.amount_minor, row.currency)}</td>
            <td>{row.merchant}<small className="muted">{row.city || 'Remote'}</small></td>
            <td>{row.channel === 'upi' ? 'UPI' : 'Card'}</td>
            <td className="muted nowrap">{timestamp(row.occurred_at)}</td>
          </tr>)}</tbody>
        </table>
      </section>)}
      {data.data && (data.data.next_cursor || !atFirstPage || !!data.data.items.length) && <footer className="table-footer">
        <output>{data.data.items.length} {data.data.items.length === 1 ? 'case' : 'cases'} shown</output>
        <div className="button-row">
          {!atFirstPage && <Button size="small" icon={<ArrowLeft />} onClick={() => change({ after: '' })}>First page</Button>}
          <Button size="small" disabled={!data.data.next_cursor || refreshing}
            onClick={() => change({ after: data.data?.next_cursor || '' })}>Next page<ArrowRight aria-hidden /></Button>
        </div>
      </footer>}
    </section>
  </>
}
