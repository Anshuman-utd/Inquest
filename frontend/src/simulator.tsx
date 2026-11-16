import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pause, Play, Radio, RotateCcw } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { ApiError, post, request, type Schema } from './api'
import { Failure, human, number, short } from './ui'

export function useSimulator() {
  return useQuery({
    queryKey: ['simulator'],
    queryFn: () => request<Schema['ReplayStatus']>('/simulator'),
    refetchInterval: query => query.state.data?.state === 'running' ? 1500 : 6000,
  })
}

export function Simulator() {
  const query = useSimulator()
  const client = useQueryClient()
  const dialog = useRef<HTMLDialogElement>(null)
  const menu = useRef<HTMLDetailsElement>(null)
  const state = query.data
  const mutate = useMutation({
    mutationFn: (command: Schema['ReplayCommand']['command']) => post<Schema['ReplayStatus']>(
      '/simulator/commands', { command, expected_replay_id: state?.replay_id ?? null },
    ),
    onSuccess: next => {
      client.setQueryData(['simulator'], next)
      void client.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: error => {
      if (error instanceof ApiError && error.status === 409) void query.refetch()
    },
  })

  useEffect(() => {
    function dismiss(event: PointerEvent) {
      if (event.target instanceof Node && !menu.current?.contains(event.target)) {
        menu.current?.removeAttribute('open')
      }
    }
    document.addEventListener('pointerdown', dismiss)
    return () => document.removeEventListener('pointerdown', dismiss)
  }, [])

  return <details className="simulator" ref={menu} onKeyDown={event => {
    if (event.key === 'Escape' && !dialog.current?.open) {
      menu.current?.removeAttribute('open')
      menu.current?.querySelector('summary')?.focus()
    }
  }}>
    <summary className="button" title="Simulator controls">
      <Radio size={16} aria-hidden />
      <span>Simulator</span><span className="sim-summary">{state ? human(state.state || 'idle') : '…'}</span>
    </summary>
    <section className="simulator-panel" aria-label="Simulator controls">
      <h2>Transaction replay</h2>
      {query.error && <Failure error={query.error} retry={() => void query.refetch()} />}
      {state && <>
        <div className="progress-label"><span>{human(state.state || 'idle')}</span>
          <span className="mono">{number.format(state.cursor || 0)} / {number.format(state.total)}</span>
        </div>
        <progress value={state.cursor || 0} max={state.total} aria-label="Transactions replayed" />
        {state.replay_id && <p className="muted">Active replay <span className="mono" title={state.replay_id}>{short(state.replay_id)}</span></p>}
        <div className="button-row">
          {state.state === 'running'
            ? <button className="button" type="button" disabled={mutate.isPending} onClick={() => mutate.mutate('pause')}>
              <Pause size={15} aria-hidden />Pause
            </button>
            : <button className="button primary" type="button" disabled={mutate.isPending || state.state === 'complete'} onClick={() => mutate.mutate('start')}>
              <Play size={15} aria-hidden />{state.state === 'paused' ? 'Resume' : 'Start'}
            </button>}
          <button className="button" type="button" disabled={mutate.isPending || !state.replay_id} onClick={() => dialog.current?.showModal()}>
            <RotateCcw size={15} aria-hidden />Replay
          </button>
        </div>
      </>}
      {mutate.error && <Failure error={mutate.error} />}
    </section>
    <dialog ref={dialog} aria-labelledby="replay-title">
      <h2 id="replay-title">Replay synthetic transactions?</h2>
      <p>This starts another run from the beginning. Existing cases and decisions stay in the queue.</p>
      <form method="dialog" className="button-row">
        <button className="button" autoFocus>Cancel</button>
        <button className="button primary" onClick={() => mutate.mutate('replay')}>Start new replay</button>
      </form>
    </dialog>
  </details>
}
