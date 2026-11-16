import type { components, paths } from './schema'

export type Schema = components['schemas']
export type QueueQuery = NonNullable<paths['/api/v1/cases']['get']['parameters']['query']>

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { cache: 'no-store', ...init })
  if (!response.ok) {
    const json: { detail?: unknown } = await response.json().catch(() => ({}))
    throw new ApiError(response.status, typeof json.detail === 'string'
      ? json.detail : `Request failed (${response.status})`)
  }
  return response.status === 204 ? undefined as T : response.json()
}

export function post<T>(path: string, body?: unknown, idempotencyKey?: string): Promise<T> {
  const headers = new Headers()
  if (body !== undefined) headers.set('Content-Type', 'application/json')
  if (idempotencyKey) headers.set('Idempotency-Key', idempotencyKey)
  return request<T>(path, {
    method: 'POST', headers, body: body === undefined ? undefined : JSON.stringify(body),
  })
}
