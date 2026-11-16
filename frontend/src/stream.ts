import { useQueryClient } from '@tanstack/react-query'
import { createParser } from 'eventsource-parser'
import { useEffect, useRef, useState } from 'react'
import { ApiError, request, type Schema } from './api'

export type Entry = Schema['InvestigationEvent'] & { id: string }
type Connection = 'connecting' | 'live' | 'reconnecting' | 'settled' | 'unavailable'
const kinds = new Set<Entry['kind']>([
  'queued', 'triage', 'tool_started', 'tool_observed', 'recording_used',
  'recording_unavailable', 'report_ready', 'decision_recorded', 'completed', 'failed',
])

export function useInvestigationStream(run: string, renewal: number, caseId: string) {
  const [entries, setEntries] = useState<Entry[]>([])
  const [connection, setConnection] = useState<Connection>('connecting')
  const cursor = useRef('')
  const client = useQueryClient()
  useEffect(() => {
    const controller = new AbortController()
    const signal = controller.signal
    let retry: ReturnType<typeof setTimeout> | undefined
    const snapshot = () => request<Schema['Snapshot']>(`/investigations/${run}`, { signal })

    async function connect() {
      try {
        const response = await fetch(`/api/v1/investigations/${run}/events`, {
          headers: cursor.current ? { 'Last-Event-ID': cursor.current } : undefined,
          cache: 'no-store', signal,
        })
        if ([401, 403, 404].includes(response.status)) {
          setConnection('unavailable')
          void client.invalidateQueries({ queryKey: ['session'] })
          return
        }
        if (!response.ok || !response.body || !response.headers.get('Content-Type')?.startsWith('text/event-stream')) {
          throw new Error('Stream unavailable')
        }
        setConnection('live')
        const parser = createParser({ onEvent: event => {
          if (signal.aborted || !event.id || event.id === cursor.current || !kinds.has(event.event as Entry['kind'])) return
          const payload: unknown = JSON.parse(event.data)
          cursor.current = event.id
          const entry = { id: event.id, kind: event.event, payload } as Entry
          setEntries(prior => [...prior, entry])
        } })
        const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
        try {
          while (!signal.aborted) {
            const chunk = await reader.read()
            if (chunk.done) break
            parser.feed(chunk.value)
          }
        } finally {
          await reader.cancel().catch(() => {})
          reader.releaseLock()
        }
        if (signal.aborted) return
        const current = await snapshot()
        client.setQueryData(['investigation', run], current)
        void client.invalidateQueries({ queryKey: ['case', caseId] })
        void client.invalidateQueries({ queryKey: ['cases'] })
        if (['review', 'complete', 'failed'].includes(current.status)) {
          setConnection('settled')
          return
        }
      } catch (error) {
        if (signal.aborted) return
        if (error instanceof ApiError && error.status < 500) {
          setConnection('unavailable')
          return
        }
      }
      if (!signal.aborted) {
        setConnection('reconnecting')
        retry = setTimeout(() => void connect(), 1500)
      }
    }
    void connect()
    return () => {
      controller.abort()
      clearTimeout(retry)
    }
  }, [run, renewal, caseId, client])
  return { entries, connection }
}
