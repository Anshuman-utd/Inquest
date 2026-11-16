import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ArrowUpDown, Search } from 'lucide-react'
import { useDeferredValue } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { request, type QueueQuery, type Schema } from './api'
import { useSimulator } from './simulator'
import { amount, Empty, Failure, Loading, number, PageHeading, percent, short, Status, timestamp } from './ui'

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
    <PageHeading title="Case Queue" description="Review alerts and manage investigations." />
    {counts && <dl className="queue-stats">
      <div><dt>Total cases</dt><dd>{number.format(total || 0)}</dd></div>
      <div><dt>Queued</dt><dd>{number.format(counts.queued || 0)}</dd></div>
      <div><dt>Investigating</dt><dd>{number.format(counts.investigating || 0)}</dd></div>
      <div><dt>Needs review</dt><dd>{number.format(counts.review || 0)}</dd></div>
    </dl>}
    <section className="panel queue" aria-label="Case queue">
      <div className="filters">
        <label className="search-field">
          <Search size={16} aria-hidden />
          <input aria-label="Search cases" placeholder="Search case, transaction, customer or merchant" maxLength={100}
            value={search.get('q') || ''} onChange={event => change({ q: event.target.value }, true)} />
        </label>
        <label className="sr-only" htmlFor="status-filter">Case status</label>
        <select id="status-filter" value={search.get('status') || ''} onChange={event => change({ status: event.target.value })}>
          <option value="">All statuses</option>
          {states.map(([key, label]) => <option value={key} key={key}>{label}</option>)}
        </select>
        <label className="sr-only" htmlFor="channel-filter">Payment channel</label>
        <select id="channel-filter" value={search.get('channel') || ''} onChange={event => change({ channel: event.target.value })}>
          <option value="">All channels</option><option value="upi">UPI</option><option value="card">Card</option>
        </select>
        <label className="sr-only" htmlFor="risk-filter">Minimum risk</label>
        <select id="risk-filter" value={search.get('min_score') || ''} onChange={event => change({ min_score: event.target.value })}>
          <option value="">All risk scores</option><option value="0.01">Risk ≥ 1%</option>
          <option value="0.1">Risk ≥ 10%</option><option value="0.5">Risk ≥ 50%</option>
        </select>
        {filtersApplied && <button className="button text-button" type="button" onClick={() => change({ q: '', status: '', channel: '', min_score: '' })}>Clear filters</button>}
      </div>
      {data.isPending && <Loading text="Loading cases…" />}
      {data.error && <Failure error={data.error} retry={() => void data.refetch()} />}
      {data.data && data.data.items.length === 0 && !data.isPlaceholderData && (
        filtersApplied || !atFirstPage
          ? <Empty title="No matching cases">Change the filters or return to the first page.</Empty>
          : <Empty title="No cases yet">{simulator.data?.state === 'running'
            ? 'The simulator is scanning synthetic transactions.'
            : 'Open Simulator and start a transaction replay to populate the queue.'}</Empty>
      )}
      {!!data.data?.items.length && <div className="table-scroll" role="region" tabIndex={0} aria-label="Case rows">
        <table className="case-table">
          <thead><tr>
            <th scope="col">Case / transaction</th>
            {columns.map(([key, label]) => {
              const active = sort === key
              const Icon = !active ? ArrowUpDown : direction === 'asc' ? ArrowUp : ArrowDown
              return <th scope="col" key={key} aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : undefined}
                className={key === 'risk' || key === 'amount' ? 'numeric' : undefined}>
                <button type="button" className="sort-button" onClick={() => change({ sort: key, direction: active && direction === 'desc' ? 'asc' : 'desc' })}>
                  {label}<Icon size={13} aria-hidden />
                </button>
              </th>
            })}
          </tr></thead>
          <tbody>{data.data.items.map(row => <tr key={row.case_id}>
            <td><Link className="mono" to={`/cases/${row.case_id}`} state={{ queue: location.search }} aria-label={`Open case ${short(row.case_id)}, transaction ${row.source_sequence}`}>{short(row.case_id)}</Link>
              <small className="mono muted">TX-{row.source_sequence}</small></td>
            <td><Status value={row.disposition || row.status} /></td>
            <td className="numeric mono">{percent(row.score, 2)}</td>
            <td className="numeric">{amount(row.amount_minor, row.currency)}</td>
            <td>{row.merchant}<small className="muted">{row.city || 'Remote'}</small></td>
            <td>{row.channel === 'upi' ? 'UPI' : 'Card'}</td>
            <td className="muted nowrap">{timestamp(row.occurred_at)}</td>
          </tr>)}</tbody>
        </table>
      </div>}
      {data.data && (data.data.next_cursor || !atFirstPage || !!data.data.items.length) && <footer className="table-footer">
        <span role="status">{data.data.items.length} {data.data.items.length === 1 ? 'case' : 'cases'} shown</span>
        <div className="button-row">
          {!atFirstPage && <button className="button" type="button" onClick={() => change({ after: '' })}><ArrowLeft size={14} aria-hidden />First page</button>}
          <button className="button" type="button" disabled={!data.data.next_cursor || data.isPlaceholderData}
            onClick={() => change({ after: data.data?.next_cursor || '' })}>Next page<ArrowRight size={14} aria-hidden /></button>
        </div>
      </footer>}
    </section>
  </>
}
