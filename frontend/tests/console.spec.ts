import { expect, test, type Page } from '@playwright/test'
import type { Schema } from '../src/api'

const caseId = '00000001-aaaa-4000-8000-000000000001'
const investigationId = '00000002-aaaa-4000-8000-000000000002'
const analystId = '00000003-aaaa-4000-8000-000000000003'
const workspaceId = '00000004-aaaa-4000-8000-000000000004'
const replayId = '00000005-aaaa-4000-8000-000000000005'
const evidenceId = '00000006-aaaa-4000-8000-000000000006'

const transaction = {
  amount_minor: 321075, channel: 'upi', city: 'Bengaluru', currency: 'INR', customer_id: 'customer-5',
  declined: false, device_id: 'device-04', flow: 'push', location_source: 'physical', merchant: 'Test market',
  merchant_id: 'merchant-72', occurred_at: '2026-03-06T10:03:05Z', source_sequence: 251,
} as const

const caseDetail: Schema['CaseDetail'] = {
  ...transaction, case_id: caseId, customer: 'Customer 0005', dataset_id: 'fixture', status: 'review',
  version: 3, replay_id: replayId, score: 0.875, threshold: 0.01, investigation_id: investigationId,
  disposition: null, decision: null, contributions: [], model_version: 'v1', feature_version: 'v1',
}

const report: Schema['Report'] = {
  confidence: 0.96, evidence: [{ evidence_id: evidenceId, field: 'device_id', value: 'device-04' }],
  recommended_action: 'block', status: 'verified', verdict: 'fraud',
}

const replay: Schema['ReplayStatus'] = { state: 'paused', cursor: 700, total: 1000, replay_id: replayId }

const eventData = [
  { id: 1, event: 'tool_started', data: { call_sequence: 1, input: { tool: 'get_transaction' } } },
  { id: 2, event: 'tool_observed', data: {
    result: { evidence_id: evidenceId, call_sequence: 1, status: 'ok', observation: { tool: 'get_transaction', device_id: transaction.device_id } },
  } },
]
const sse = (entries = eventData) => entries.map(entry =>
  `id: ${entry.id}\nevent: ${entry.event}\ndata: ${JSON.stringify(entry.data)}\n\n`).join('')

async function setup(page: Page, authenticated = true) {
  await page.route('/api/v1/auth/session', route => authenticated
    ? route.fulfill({ json: { workspace_id: workspaceId, analyst_id: analystId } })
    : route.fulfill({ status: 401, json: { detail: 'Authentication required' } }))
  await page.route('/api/v1/auth/providers', route => route.fulfill({ json: { github: true, google: true } }))
  await page.route('/api/v1/simulator', route => route.fulfill({ json: replay }))
  await page.route(/\/api\/v1\/cases\?/, route => route.fulfill({
    json: {
      items: [caseDetail, ...(['block', 'release', 'escalate'] as const).map((disposition, i) => ({
        ...caseDetail, disposition, case_id: `1000000${i}-aaaa-4000-8000-000000000001`, source_sequence: 252 + i,
      }))],
      counts: { queued: 0, review: 1, resolved: 2, escalated: 1 }, next_cursor: caseId,
    } satisfies Schema['CasePage'],
  }))
}

test('both provider forms preserve their method, intent, and recovery message', async ({ page }) => {
  await setup(page, false)
  for (const intent of ['login', 'signup']) {
    await page.goto(`/${intent}?error=oauth`)
    await expect(page.getByRole('alert')).toContainText('Choose a provider to try again')
    for (const provider of ['GitHub', 'Google']) {
      const button = page.getByRole('button', { name: `Continue with ${provider}` })
      await expect(button).toBeEnabled()
      const form = button.locator('..')
      await expect(form).toHaveAttribute('method', 'post')
      await expect(form).toHaveAttribute('action', `/api/v1/auth/${provider.toLowerCase()}/start?intent=${intent}`)
    }
  }
  await expect(page.getByText('Synthetic data only. Don’t enter real personal data.')).toBeVisible()
})

test('queue retains URL controls and keyboard navigation into a case', async ({ page }) => {
  await setup(page)
  await page.route(`/api/v1/cases/${caseId}`, route => route.fulfill({ json: { ...caseDetail, status: 'queued', investigation_id: null } }))
  await page.goto('/?channel=upi&sort=risk')
  await expect(page.getByRole('heading', { name: 'Case queue' })).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  const sort = page.getByRole('button', { name: 'Risk score' })
  await sort.press('Enter')
  await expect(page).toHaveURL(/direction=asc/)
  await page.getByText('Filters', { exact: true }).press('Enter')
  await page.getByLabel('Case status').selectOption('review')
  await expect(page).toHaveURL(/status=review/)
  const refreshedQueue = page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname === '/api/v1/cases' && url.searchParams.get('status') === 'review' && !url.searchParams.has('channel')
  })
  await page.getByLabel('Remove channel filter').press('Enter')
  await refreshedQueue
  await expect(page).not.toHaveURL(/channel=/)
  const next = page.getByRole('button', { name: 'Next page' })
  await expect(next).toBeEnabled()
  await next.press('Enter')
  await expect(page).toHaveURL(/after=/)
  await expect(page.getByRole('button', { name: 'First page' })).toBeVisible()
  await page.getByRole('link', { name: 'Open case 00000001, transaction 251' }).press('Enter')
  await expect(page.getByRole('button', { name: 'Start investigation' })).toBeVisible()
  await page.getByRole('link', { name: 'Back to case queue' }).press('Enter')
  await expect(page).toHaveURL(/sort=risk.*status=review.*after=/)
})

test('citations focus their evidence and decisions keep the existing request contract', async ({ page }) => {
  await setup(page)
  let recorded = false
  await page.route(`/api/v1/cases/${caseId}`, route => route.fulfill({ json: recorded ? {
    ...caseDetail, status: 'resolved', disposition: 'release',
    decision: { analyst_id: analystId, created_at: transaction.occurred_at, operation: 'override', disposition: 'release', note: 'Reviewed evidence.' },
  } : caseDetail }))
  await page.route(`/api/v1/investigations/${investigationId}`, route => route.fulfill({ json: { status: 'review', mode: 'replay', case_version: 3, report } }))
  await page.route(`/api/v1/investigations/${investigationId}/events`, route =>
    route.fulfill({ contentType: 'text/event-stream', body: sse() }))
  await page.route(`/api/v1/investigations/${investigationId}/decision`, async route => {
    expect(route.request().method()).toBe('POST')
    expect(route.request().headers()['idempotency-key']).toMatch(/^[\da-f-]{36}$/)
    expect(route.request().postDataJSON()).toEqual({ operation: 'override', expected_case_version: 3, note: 'Reviewed evidence.', action: 'release' })
    recorded = true
    await route.fulfill({ json: { decision_id: evidenceId } })
  })
  await page.goto(`/cases/${caseId}`)
  await page.getByRole('button', { name: /Device id/ }).press('Enter')
  await expect(page.locator('.timeline summary')).toBeFocused()
  await expect(page.getByRole('heading', { name: 'Observation' })).toBeVisible()
  await page.getByRole('radio', { name: 'Override', exact: true }).press('Space')
  await page.getByLabel('Override disposition').selectOption('release')
  await page.getByLabel('Analyst notes').fill('Reviewed evidence.')
  await page.getByRole('button', { name: 'Record decision' }).press('Enter')
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Record decision' })).toBeFocused()
  await page.getByRole('button', { name: 'Record decision' }).press('Enter')
  await dialog.getByRole('button', { name: 'Confirm release' }).press('Enter')
  await expect(page.getByRole('heading', { name: 'Recorded decision' })).toBeVisible()
  await expect(page.getByText('Reviewed evidence.')).toBeVisible()
})

test('stream reconnect resumes with the last event ID', async ({ page }) => {
  await setup(page)
  let connection = 0
  await page.route(`/api/v1/cases/${caseId}`, route => route.fulfill({ json: { ...caseDetail, status: 'investigating' } }))
  await page.route(`/api/v1/investigations/${investigationId}`, route => route.fulfill({
    json: { status: connection >= 2 ? 'review' : 'running', mode: 'live', case_version: 3, report: connection >= 2 ? report : null },
  }))
  await page.route(`/api/v1/investigations/${investigationId}/events`, async route => {
    connection += 1
    if (connection > 1) expect(route.request().headers()['last-event-id']).toBe('1')
    await route.fulfill({ contentType: 'text/event-stream', body: sse(connection === 1 ? eventData.slice(0, 1) : eventData.slice(1)) })
  })
  await page.goto(`/cases/${caseId}`)
  await expect(page.getByText('Reconnecting…')).toBeVisible()
  await expect(page.getByRole('group', { name: 'Analyst decision' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Device id/ })).toBeEnabled()
  expect(connection).toBe(2)
})

test('replay confirms once and preserves the command payload', async ({ page }) => {
  await setup(page)
  let calls = 0
  await page.route('/api/v1/simulator/commands', async route => {
    calls += 1
    expect(route.request().postDataJSON()).toEqual({ command: 'replay', expected_replay_id: replayId })
    await route.fulfill({ json: { ...replay, state: 'running', cursor: 0 } })
  })
  await page.goto('/')
  await page.locator('#simulator-trigger').press('Enter')
  await page.getByRole('button', { name: 'Replay', exact: true }).press('Enter')
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await expect(dialog).toContainText('Previous cases and analyst decisions stay in the queue.')
  await dialog.getByRole('button', { name: 'Confirm replay' }).press('Enter')
  await expect(dialog).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible()
  expect(calls).toBe(1)
})

test('tablet explorer shows comparisons inline and links flagged attempts', async ({ page }) => {
  await setup(page)
  await page.setViewportSize({ width: 768, height: 1024 })
  await page.route(/\/api\/v1\/customers\/customer-5\/transactions\?/, route => route.fulfill({
    json: { customer: { id: 'customer-5', alias: 'Customer 0005' }, next_cursor: null, items: [{
      ...transaction, flagged: true, travel: { distance_km: 318, elapsed_seconds: 1800, previous_city: 'Chennai', previous_sequence: 241 },
    }] } satisfies Schema['HistoryPage'],
  }))
  await page.goto('/explorer?customer=customer-5')
  await page.getByRole('button', { name: /Test market/ }).press('Enter')
  await expect(page.locator('.attempt-row .comparison')).toContainText('318 km')
  await expect(page.getByRole('link', { name: 'View matching cases' })).toHaveAttribute('href', '/?q=TX-251')
})

test('evaluation tabs respond to arrow keys and retain the selected cohort', async ({ page }) => {
  await setup(page)
  const cohort: Schema['ScorerCohort'] = {
    alerts_per_1000: 16, attempts: 900, average_precision: 0.47, fraud: 9,
    precision: 0.23, recall: 0.89, scenarios: {}, pr_curve: [{ precision: 0.5, recall: 0.7 }],
  }
  await page.route('/api/v1/evaluations', route => route.fulfill({ json: {
    schema_version: 1, reports: [], scorer: { cohorts: { test: cohort, shift_test: cohort }, model_version: 'v1', threshold: 0.01 },
  } }))
  await page.goto('/evaluation')
  await page.getByLabel('Scorer cohort').selectOption('shift_test')
  await page.getByRole('tab', { name: 'Chart' }).press('ArrowRight')
  await expect(page.getByRole('tab', { name: 'Table' })).toBeFocused()
  await expect(page.getByRole('tabpanel')).toContainText('70.0%')
  await expect(page.getByLabel('Scorer cohort')).toHaveValue('shift_test')
})

for (const theme of ['light', 'dark'] as const) {
  test(`${theme} palette meets contrast and retains status meaning`, async ({ page, context }) => {
    await setup(page)
    await page.addInitScript(mode => localStorage.setItem('inquest-theme', mode), theme)
    await page.goto('/')
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    await expect(page.locator('.case-table')).toBeVisible()
    const failures = await page.evaluate(() => {
      const css = getComputedStyle(document.documentElement)
      function luminance(token: string) {
        const hex = css.getPropertyValue(token).trim()
        const channels = [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16) / 255)
        const [r, g, b] = channels.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
        return r * .2126 + g * .7152 + b * .0722
      }
      const pairs = [
        ['--text', '--surface', 4.5], ['--muted', '--canvas', 4.5], ['--muted', '--rail', 4.5],
        ['--accent', '--accent-fill', 4.5], ['--accent-ink', '--accent', 4.5],
        ['--fraud', '--fraud-fill', 4.5], ['--legit', '--legit-fill', 4.5],
        ['--review', '--review-fill', 4.5], ['--escalated', '--escalated-fill', 4.5],
        ['--control', '--surface', 3], ['--accent', '--canvas', 3], ['--chart', '--surface', 3],
      ] as const
      return pairs.filter(([foreground, background, minimum]) => {
        const [dark, light] = [luminance(foreground), luminance(background)].sort((a, b) => a - b)
        return !( (light + .05) / (dark + .05) >= minimum )
      })
    })
    expect(failures).toEqual([])
    const cdp = await context.newCDPSession(page)
    for (const type of ['protanopia', 'deuteranopia', 'tritanopia'] as const) {
      await cdp.send('Emulation.setEmulatedVisionDeficiency', { type })
      for (const label of ['Fraud', 'Legitimate', 'Needs review', 'Escalated']) {
        const badge = page.locator('.status').filter({ hasText: label })
        await expect(badge).toBeVisible()
        await expect(badge.locator('svg')).toBeVisible()
      }
    }
  })
}


test('compact shell keeps page overflow local and honors reduced motion', async ({ page }) => {
  await setup(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'Cases', exact: true })).toBeVisible()
  await expect(page.locator('.sidebar nav a').first()).toHaveCSS('transition-duration', '0s')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  const scroll = page.getByRole('region', { name: 'Case rows' })
  await expect(scroll).toBeVisible()
  expect(await scroll.evaluate(node => node.scrollWidth > node.clientWidth)).toBe(true)
})

test('account popover closes with Escape and signs out through the session endpoint', async ({ page }) => {
  await setup(page)
  let signedOut = false
  await page.route('/api/v1/auth/session', route => signedOut
    ? route.fulfill({ status: 401, json: { detail: 'Authentication required' } })
    : route.fulfill({ json: { workspace_id: workspaceId, analyst_id: analystId } }))
  await page.route('/api/v1/auth/logout', async route => {
    expect(route.request().method()).toBe('POST')
    signedOut = true
    await route.fulfill({ status: 204 })
  })
  await page.goto('/')
  const trigger = page.locator('.account-menu summary')
  await trigger.press('Enter')
  const account = page.getByRole('region', { name: 'Account details' })
  await expect(account).toContainText('Workspace ID')
  await expect(account).toContainText('Analyst ID')
  await account.getByRole('button', { name: 'Sign out' }).focus()
  await page.keyboard.press('Escape')
  await expect(account).not.toBeVisible()
  await expect(trigger).toBeFocused()
  await trigger.press('Enter')
  await account.getByRole('button', { name: 'Sign out' }).press('Enter')
  await expect(page.getByRole('heading', { name: 'Sign in to Inquest' })).toBeVisible()
})
