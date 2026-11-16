import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { ChartNoAxesCombined, ClipboardList, Database, LogOut, Monitor, Moon, Sun, UserRound } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  BrowserRouter, Link, NavLink, Navigate, Outlet, Route, Routes, useLocation, useSearchParams,
} from 'react-router-dom'
import { ApiError, post, request, type Schema } from './api'
import { CasePage } from './case'
import { Evaluations } from './evaluation'
import { Explorer } from './explorer'
import { Queue } from './queue'
import { Simulator } from './simulator'
import { Brand, Button, Failure, Loading, Missing, short, useDismissableDisclosure } from './ui'
import '@fontsource-variable/geist'
import '@fontsource/ibm-plex-mono/400.css'
import './styles.css'
import githubMark from './assets/github.svg'
import googleMark from './assets/google.svg'

const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: (failureCount, error) => failureCount < 1 && (!(error instanceof ApiError) || error.status >= 500),
    },
  },
})

type Theme = 'system' | 'light' | 'dark'

function ThemeControl() {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem('inquest-theme')
    return saved === 'light' || saved === 'dark' ? saved : 'system'
  })
  useEffect(() => {
    localStorage.setItem('inquest-theme', theme)
    const media = matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      document.documentElement.dataset.theme = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme
    }
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [theme])
  const Icon = theme === 'system' ? Monitor : theme === 'light' ? Sun : Moon
  return <label className="theme-control">
    <Icon size={16} aria-hidden />
    <select value={theme} aria-label="Color theme" onChange={event => setTheme(event.target.value as Theme)}>
      <option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option>
    </select>
  </label>
}

function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: () => request<Schema['Session']>('/auth/session'),
    retry: false,
  })
}

const errors: Record<string, string> = {
  unavailable: 'This sign-in provider is unavailable.',
  rate: 'Too many sign-in attempts. Wait a minute and try again.',
  oauth: 'Sign-in could not be completed. Choose a provider to try again.',
}

function Auth({ signup = false }: { signup?: boolean }) {
  const session = useSession()
  const [params] = useSearchParams()
  const available = useQuery({
    queryKey: ['auth-providers'], queryFn: () => request<Schema['AuthOptions']>('/auth/providers'),
  })
  if (session.data) return <Navigate replace to="/" />
  const error = errors[params.get('error') || '']
  const intent = signup ? 'signup' : 'login'
  return <div className="auth-layout">
    <header className="auth-header"><Brand /><ThemeControl /></header>
    <main className="auth-main">
      <div className="auth-panel" aria-labelledby="auth-title">
        <h1 id="auth-title">{signup ? 'Create your workspace' : 'Sign in to Inquest'}</h1>
        <p>{signup ? 'Your first sign-in creates a private workspace for investigating synthetic payments.' : 'Access your case queue, investigations, and analyst decisions.'}</p>
        {error && <div role="alert" className="auth-alert">{error}</div>}
        {available.error && <Failure error={available.error} retry={() => void available.refetch()} />}
        {available.isPending && <Loading text="Loading sign-in options…" />}
        <div className="auth-buttons">
          {([{ key: 'github', label: 'GitHub', mark: githubMark }, { key: 'google', label: 'Google', mark: googleMark }] as const).map(provider => <form key={provider.key} method="post" action={`/api/v1/auth/${provider.key}/start?intent=${intent}`}>
            <Button type="submit" size="large" disabled={!available.data?.[provider.key]}
              icon={<img className={`provider-mark ${provider.key}`} src={provider.mark} alt="" />}>
              Continue with {provider.label}
            </Button>
            {available.data && !available.data[provider.key] && <p className="provider-unavailable">{provider.label} is currently unavailable.</p>}
          </form>)}
        </div>
        <p className="synthetic-notice">Synthetic data only. Don’t enter real personal data.</p>
        <p className="auth-switch">{signup ? <>Already have an account? <Link to="/login">Sign in</Link></> : <>New to Inquest? <Link to="/signup">Create a workspace</Link></>}</p>
      </div>
    </main>
  </div>
}

const links = [
  { to: '/', label: 'Cases', icon: ClipboardList },
  { to: '/explorer', label: 'Explorer', icon: Database },
  { to: '/evaluation', label: 'Evaluation', icon: ChartNoAxesCombined },
]

function Workspace() {
  const session = useSession()
  const location = useLocation()
  const [logoutError, setLogoutError] = useState<Error | null>(null)
  const [loggingOut, setLoggingOut] = useState(false)
  const account = useRef<HTMLDetailsElement>(null)
  useDismissableDisclosure(account)
  async function signOut() {
    setLoggingOut(true)
    try {
      await post('/auth/logout')
      client.clear()
      window.location.assign('/login')
    } catch (error) {
      setLogoutError(error instanceof Error ? error : new Error('Unable to sign out'))
      setLoggingOut(false)
    }
  }
  if (session.isPending) return <Loading text="Opening workspace…" />
  if (session.error instanceof ApiError && session.error.status === 401) return <Navigate replace to="/login" />
  if (session.error) return <Failure error={session.error} retry={() => void session.refetch()} />
  if (!session.data) return null
  return <div className="workspace">
    <a className="skip-link" href="#main">Skip to content</a>
    <aside className="sidebar">
      <Link className="brand-link" to="/" aria-label="Inquest case queue"><Brand /></Link>
      
      <nav aria-label="Workspace">
        {links.map(({ to, label, icon: Icon }) => {
          const active = to === '/' && location.pathname.startsWith('/cases/')
          return <NavLink key={to} to={to} end={to === '/'} title={label} aria-current={active ? 'page' : undefined} className={active ? 'active' : undefined}>
            <Icon size={17} aria-hidden /><span>{label}</span>
          </NavLink>
        })}
      </nav>
      <div className="rail-footer"><span className="fixture-dot" /><span>Synthetic data</span></div>
    </aside>
    <header className="topbar">
      <Link className="compact-brand" to="/" aria-label="Inquest case queue"><Brand /></Link>
      <span className="workspace-identifier">Workspace <span className="mono" title={session.data.workspace_id}>{short(session.data.workspace_id)}</span></span>
      <div className="top-actions">
        <Simulator />
        <div className="header-preferences">
          <ThemeControl />
          <details className="account-menu" ref={account}>
            <summary className="button icon-button" aria-label="Account" title="Account"><UserRound aria-hidden /></summary>
            <section className="account-panel" aria-label="Account details">
              <h2>Analyst account</h2>
              <dl>
                <div><dt>Workspace ID</dt><dd className="mono" title={session.data.workspace_id}>{short(session.data.workspace_id)}</dd></div>
                <div><dt>Analyst ID</dt><dd className="mono" title={session.data.analyst_id}>{short(session.data.analyst_id)}</dd></div>
              </dl>
              <Button variant="ghost" icon={<LogOut />} busy={loggingOut} onClick={() => void signOut()}>Sign out</Button>
              {logoutError && <Failure error={logoutError} retry={() => void signOut()} />}
            </section>
          </details>
        </div>
      </div>
    </header>
    <main id="main" tabIndex={-1} className="content">
      <Outlet />
    </main>
  </div>
}

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={client}>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Auth />} />
        <Route path="/signup" element={<Auth signup />} />
        <Route element={<Workspace />}>
          <Route index element={<Queue />} />
          <Route path="/cases/:caseId" element={<CasePage />} />
          <Route path="/explorer" element={<Explorer />} />
          <Route path="/evaluation" element={<Evaluations />} />
          <Route path="*" element={<Missing />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </QueryClientProvider>,
)
