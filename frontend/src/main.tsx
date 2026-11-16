import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { ChartNoAxesCombined, ClipboardList, Database, LogIn, LogOut, Monitor, Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
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
import { Brand, Failure, Loading, Missing, short } from './ui'
import '@fontsource-variable/geist'
import '@fontsource/ibm-plex-mono/400.css'
import './styles.css'

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
      <div className="auth-panel">
        <h1>{signup ? 'Create your workspace' : 'Sign in to Inquest'}</h1>
        <p>Your first sign-in creates a private analyst workspace for investigating synthetic payments.</p>
        {error && <div role="alert" className="auth-alert">{error}</div>}
        {available.error && <Failure error={available.error} retry={() => void available.refetch()} />}
        {available.isPending && <Loading text="Loading sign-in options…" />}
        <div className="auth-buttons">
          {(['github', 'google'] as const).map(provider => <form key={provider} method="post" action={`/api/v1/auth/${provider}/start?intent=${intent}`}>
            <button className="button" disabled={!available.data?.[provider]}>
              <LogIn size={17} aria-hidden />Continue with {provider === 'github' ? 'GitHub' : 'Google'}
            </button>
          </form>)}
        </div>
        {available.data && !available.data.github && !available.data.google && <p className="auth-alert">Sign-in is unavailable. Configure an OAuth provider in the API environment.</p>}
        <p className="synthetic-notice">Synthetic data only. Don’t enter real personal data.</p>
        <p>{signup ? <>Already have an account? <Link to="/login">Sign in</Link></> : <>New to Inquest? <Link to="/signup">Create a workspace</Link></>}</p>
      </div>
    </main>
  </div>
}

const links = [
  { to: '/', label: 'Case Queue', icon: ClipboardList },
  { to: '/explorer', label: 'Transaction Explorer', icon: Database },
  { to: '/evaluation', label: 'Evaluation', icon: ChartNoAxesCombined },
]

function Workspace() {
  const session = useSession()
  const location = useLocation()
  const [logoutError, setLogoutError] = useState<Error | null>(null)
  const [loggingOut, setLoggingOut] = useState(false)
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
      <div className="rail-label">Workspace</div>
      <nav aria-label="Workspace">
        {links.map(({ to, label, icon: Icon }) => {
          const active = to === '/' && location.pathname.startsWith('/cases/')
          return <NavLink key={to} to={to} end={to === '/'} title={label} className={active ? 'active' : undefined}>
            <Icon size={17} aria-hidden /><span>{label}</span>
          </NavLink>
        })}
      </nav>
      <div className="rail-footer"><span className="fixture-dot" /><span>Synthetic data</span></div>
    </aside>
    <div className="workspace-content">
      <header className="topbar">
        <span className="workspace-identifier">Workspace <span className="mono" title={session.data.workspace_id}>{short(session.data.workspace_id)}</span></span>
        <div className="top-actions">
          <Simulator /><ThemeControl />
          <button className="button icon-button" type="button" aria-label="Sign out" title="Sign out" disabled={loggingOut} onClick={() => void signOut()}>
            <LogOut size={16} aria-hidden />
          </button>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="content">
        {logoutError && <Failure error={logoutError} retry={() => void signOut()} />}
        <Outlet />
      </main>
    </div>
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
