import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Pause, Play, Radio, RotateCcw } from 'lucide-react'
import { useRef } from 'react'
import { ApiError, post, request, type Schema } from './api'
import { Button, ConfirmDialog, Failure, human, number, short, Skeleton, useDismissableDisclosure } from './ui'

export function useSimulator() {
  return useQuery({
    queryKey: ['simulator'],
    queryFn: () => request<Schema['ReplayStatus']>('/simulator'),
    refetchInterval: query => query.state.data?.state === 'running' ? 1500 : 6000,
  })
}

export function openSimulator() {
  const control = document.getElementById('simulator-trigger')
  if (control?.parentElement instanceof HTMLDetailsElement) control.parentElement.open = true
  control?.focus()
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
    onSuccess: (next, command) => {
      if (command === 'replay') dialog.current?.close()
      client.setQueryData(['simulator'], next)
      void client.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: error => {
      if (error instanceof ApiError && error.status === 409) void query.refetch()
    },
  })

  useDismissableDisclosure(menu)

  const label = state?.state || 'idle'
  const busy = mutate.isPending
  const mainCommand = label === 'running' ? 'pause' : 'start'
  const replayError = mutate.variables === 'replay' ? mutate.error : null

  function cancel() {
    dialog.current?.close()
    mutate.reset()
  }

  return <details className="simulator" ref={menu}>
    <summary id="simulator-trigger" className="button" title="Simulator controls">
      <Radio aria-hidden />
      <span>Simulator</span><span className="sim-summary">{state ? human(label) : '…'}</span>
      <ChevronDown className="sim-chev" aria-hidden />
    </summary>
    <section className="simulator-panel" aria-label="Simulator controls">
      <div className="section-heading">
        <h2>Transaction replay</h2>
        {state && <span className="tag">{human(label)}</span>}
      </div>
      {query.isPending && <Skeleton text="Loading simulator…" />}
      {query.error && <Failure error={query.error} retry={() => void query.refetch()} />}
      {state && <>
        <div className="sim-progress">
          <div className="progress-label"><span>Transactions replayed</span>
            <span className="mono">{number.format(state.cursor || 0)} / {number.format(state.total)}</span>
          </div>
          <progress value={state.cursor || 0} max={state.total} aria-label="Transactions replayed" />
          {state.replay_id && <p className="muted">Active replay <span className="mono" title={state.replay_id}>{short(state.replay_id)}</span></p>}
        </div>
        <div className="button-row simulator-actions">
          <Button icon={<RotateCcw />} disabled={busy || !state.replay_id} onClick={() => { mutate.reset(); dialog.current?.showModal() }}>Replay</Button>
          <Button variant="primary" icon={label === 'running' ? <Pause /> : <Play />}
            busy={busy && mutate.variables !== 'replay'} disabled={busy || label === 'complete'}
            onClick={() => mutate.mutate(mainCommand)}>
            {label === 'running' ? 'Pause' : label === 'paused' ? 'Resume' : 'Start'}
          </Button>
        </div>
      </>}
      {mutate.error && !replayError && <Failure error={mutate.error} />}
    </section>
    <ConfirmDialog dialogRef={dialog} title="Replay synthetic transactions?"
      description="This creates another run from the beginning. Previous cases and analyst decisions stay in the queue."
      confirm="Confirm replay" busy={busy && mutate.variables === 'replay'}
      onCancel={cancel} onConfirm={() => { if (!busy) mutate.mutate('replay') }} error={replayError} />
  </details>
}
