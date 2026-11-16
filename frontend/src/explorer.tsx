import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowDown, ArrowUpRight, Flag, MapPin, Search } from 'lucide-react'
import { useDeferredValue, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { request, type Schema } from './api'
import { amount, Button, Empty, Failure, human, Loading, number, PageHeading, Skeleton, timestamp } from './ui'

type Attempt = Schema['CustomerAttempt']

function elapsed(seconds: number) {
  const minutes = Math.floor(seconds / 60)
  if (minutes < 1) return `${Math.round(seconds)} sec`
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)} hr ${minutes % 60} min`
}

function Comparison({ attempt }: { attempt?: Attempt }) {
  const travel = attempt?.travel
  return <section className="panel section comparison">
    <h2>Distance comparison</h2>
    {attempt && <p className="muted mono">TX-{attempt.source_sequence}</p>}
    {attempt && travel ? <>
      <div className="distance-track" aria-label={`From ${travel.previous_city} to ${attempt.city}`}>
        <span><MapPin size={18} aria-hidden />{travel.previous_city}</span><i aria-hidden /><span><MapPin size={18} aria-hidden />{attempt.city}</span>
      </div>
      <dl className="facts-grid compact">
        <div><dt>Estimated distance</dt><dd>{number.format(travel.distance_km)} km</dd></div>
        <div><dt>Elapsed time</dt><dd>{elapsed(travel.elapsed_seconds)}</dd></div>
      </dl>
      <p className="caption muted">Straight-line estimate between synthetic city centers. Source is the fixture’s physical location field.</p>
    </> : <p className="muted">{attempt ? 'Both attempts need a physical city for a distance estimate.' : 'Select an attempt to compare it with the preceding transaction.'}</p>}
  </section>
}

export function Explorer() {
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('q') || '')
  const [cursor, setCursor] = useState<number | null>(null)
  const [selected, select] = useState<number | null>(null)
  const [inline, setInline] = useState(() => matchMedia('(max-width: 850px)').matches)
  useEffect(() => {
    const media = matchMedia('(max-width: 850px)')
    const update = () => setInline(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  const customer = params.get('customer')
  const through = params.get('through')
  const historyParams = new URLSearchParams()
  if (cursor) historyParams.set('before', String(cursor))
  if (through) historyParams.set('through', through)
  const query = useDeferredValue(search.trim())
  const suggestions = useQuery({
    queryKey: ['customers', query], queryFn: () => request<Schema['Customer'][]>(
      `/customers?q=${encodeURIComponent(query)}`,
    ),
    enabled: query.length > 0,
  })
  const timeline = useQuery({
    queryKey: ['customer-history', customer, cursor, through],
    queryFn: () => request<Schema['HistoryPage']>(
      `/customers/${encodeURIComponent(customer || '')}/transactions?${historyParams}`,
    ),
    enabled: !!customer, placeholderData: keepPreviousData,
  })
  useEffect(() => {
    setCursor(null)
    select(null)
  }, [customer, through])
  const history = timeline.data?.customer.id === customer ? timeline.data : undefined
  const current = history?.items.find(item => item.source_sequence === selected)

  return <>
    <PageHeading title="Transaction explorer" description="Review synthetic customer activity and compare payment locations." />
    <section className="panel section explorer-search" aria-label="Find a customer">
      <label className="field-caption" htmlFor="customer-search">Customer ID or alias</label>
      <div className="search-field">
        <Search size={16} aria-hidden />
        <input id="customer-search" aria-label="Search synthetic customers" placeholder="Search customer records" value={search}
          maxLength={100} onChange={event => setSearch(event.target.value)} />
      </div>
      {query && suggestions.isPending && <Loading text="Searching customers…" />}
      {suggestions.error && <Failure error={suggestions.error} retry={() => void suggestions.refetch()} />}
      {query && suggestions.data?.length === 0 && <p className="muted" role="status">No matching synthetic customers.</p>}
      {query && !!suggestions.data?.length && <ul className="customers" aria-label="Matching customers">
        {suggestions.data.map(item => <li key={item.id}>
          <Button variant="ghost" className={item.id === customer ? 'selected' : ''} aria-pressed={item.id === customer}
            onClick={() => { setSearch(''); setParams({ customer: item.id }); document.getElementById('customer-search')?.focus() }}>
            <span>{item.alias}</span><span className="mono muted">{item.id}</span>
          </Button>
        </li>)}
      </ul>}
    </section>
    {!customer && !query && <div className="panel"><Empty title="Select a synthetic customer">Open a customer from the search results or a case detail.</Empty></div>}
    {customer && timeline.isPending && <div className="panel"><Skeleton text="Loading transactions…" /></div>}
    {timeline.error && <Failure error={timeline.error} retry={() => void timeline.refetch()} />}
    {history && <div className="explorer-grid">
      <section className="panel section history">
        <div className="section-heading">
          <div><h2>{history.customer.alias}</h2><p className="mono">{history.customer.id}</p></div>
          <span className="muted">{through ? `Through TX-${through} · IST` : 'Newest first · IST'}</span>
        </div>
        {!history.items.length && <Empty title="No transaction history" />}
        <ol className="attempts">
          {history.items.map(item => <li className="attempt-row" key={item.source_sequence}>
            <button type="button" className="attempt" aria-pressed={selected === item.source_sequence}
              onClick={() => select(item.source_sequence)}>
              <div><strong>{item.merchant}</strong><small className="muted mono">TX-{item.source_sequence} · {timestamp(item.occurred_at)}</small></div>
              <div><span>{item.city || 'Remote'} · {item.channel.toUpperCase()}</span><small className="muted">{item.device_id} · {human(item.flow)}</small></div>
              <div className="attempt-amount"><strong className="mono">{amount(item.amount_minor, item.currency)}</strong>
                <small className="muted">{item.declined ? 'Declined' : 'Accepted'}</small>
              </div>
            </button>
            {item.flagged && <div className="attempt-alert">
              <span><Flag size={13} aria-hidden />Alerted</span>
              <Link to={`/?q=TX-${item.source_sequence}`}>View matching cases <ArrowUpRight size={13} aria-hidden /></Link>
            </div>}
            {inline && selected === item.source_sequence && <Comparison attempt={item} />}
          </li>)}
        </ol>
        {(history.next_cursor || cursor) && <div className="button-row history-footer">
          {cursor && <Button onClick={() => { setCursor(null); select(null) }}>Latest attempts</Button>}
          <Button disabled={!history.next_cursor || timeline.isPlaceholderData}
            onClick={() => { setCursor(history.next_cursor); select(null) }}>Older attempts<ArrowDown aria-hidden /></Button>
        </div>}
      </section>
      {!inline && <Comparison attempt={current} />}
    </div>}
    {customer && <Link className="back-link explorer-back" to="/">Return to Case Queue</Link>}
  </>
}
