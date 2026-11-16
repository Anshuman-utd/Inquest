import {
  AlertCircle, ArrowUpRight, CircleCheck, CircleHelp, Clock3, LoaderCircle, ShieldAlert, ShieldCheck,
} from 'lucide-react'
import { useId, type ComponentPropsWithoutRef, type ReactNode, type Ref } from 'react'
import { Link } from 'react-router-dom'

export const number = new Intl.NumberFormat('en-IN')
const time = new Intl.DateTimeFormat('en-IN', {
  day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  hourCycle: 'h23', timeZone: 'Asia/Kolkata',
})
export const timestamp = (value: string) => time.format(new Date(value))
export const percent = (value: number | null | undefined, places = 1) =>
  value == null ? '—' : `${(value * 100).toFixed(places)}%`
export const amount = (value: number, currency: string) => new Intl.NumberFormat('en-IN', {
  style: 'currency', currency, maximumFractionDigits: 2,
}).format(value / 100)
export const human = (value: string) => value.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase())
export const short = (id: string) => id.slice(0, 8).toUpperCase()

export function Brand() {
  return <span className="brand"><span className="brand-mark"><ShieldCheck size={18} aria-hidden /></span>Inquest</span>
}

const statuses = {
  queued: [Clock3, 'Queued', 'neutral'],
  investigating: [LoaderCircle, 'Investigating', 'neutral'],
  review: [CircleHelp, 'Needs review', 'review'],
  resolved: [CircleCheck, 'Resolved', 'neutral'],
  escalated: [ArrowUpRight, 'Escalated', 'escalated'],
  block: [ShieldAlert, 'Fraud', 'fraud'],
  release: [CircleCheck, 'Legitimate', 'legit'],
  escalate: [ArrowUpRight, 'Escalated', 'escalated'],
  fraud: [ShieldAlert, 'Fraud', 'fraud'],
  legit: [CircleCheck, 'Legitimate', 'legit'],
  needs_human_review: [CircleHelp, 'Needs review', 'review'],
} as const

export function Status({ value }: { value: keyof typeof statuses }) {
  const [Icon, label, kind] = statuses[value]
  return <span className={`status ${kind}`}><Icon size={14} aria-hidden />{label}</span>
}

export function PageHeading({ title, description, children }: {
  title: string; description?: string; children?: ReactNode
}) {
  return <div className="page-heading">
    <div><h1>{title}</h1>{description && <p>{description}</p>}</div>
    {children}
  </div>
}

type ButtonProps = ComponentPropsWithoutRef<'button'> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'caution' | 'link'
  size?: 'small' | 'medium' | 'large'
  icon?: ReactNode
  busy?: boolean
}

export function Button({ variant = 'secondary', size = 'medium', icon, busy = false,
  className = '', disabled, children, type = 'button', ...props }: ButtonProps) {
  return <button {...props} type={type} className={`button ${variant} ${size} ${className}`}
    disabled={disabled || busy} aria-busy={busy || undefined}>
    {(icon || busy) && <span className="button-icon" aria-hidden>
      {busy ? <LoaderCircle size={16} className="animate-spin" /> : icon}
    </span>}
    {children}
  </button>
}

export function ConfirmDialog({ dialogRef, title, description, confirm, onConfirm, onCancel, busy, caution, error }: {
  dialogRef: Ref<HTMLDialogElement>; title: string; description: string; confirm: string
  onConfirm: () => void; onCancel: () => void; busy: boolean; caution?: boolean; error?: Error | null
}) {
  const titleId = useId()
  const descriptionId = useId()
  return <dialog ref={dialogRef} className="confirm-dialog" aria-labelledby={titleId} aria-describedby={descriptionId} onCancel={event => {
    if (busy) event.preventDefault()
    else onCancel()
  }}>
    <h2 id={titleId}>{title}</h2>
    <p id={descriptionId}>{description}</p>
    {error && <Failure error={error} />}
    <div className="button-row dialog-actions">
      <Button autoFocus disabled={busy} onClick={onCancel}>Cancel</Button>
      <Button variant={caution ? 'caution' : 'primary'} busy={busy} onClick={onConfirm}>{confirm}</Button>
    </div>
  </dialog>
}

export function Skeleton({ text, className = '' }: { text: string; className?: string }) {
  return <div className={`skeleton-state ${className}`} role="status">
    <span className="sr-only">{text}</span>
    <div aria-hidden className="skeleton-lines">{Array.from({ length: 4 }, (_, i) => <span key={i} />)}</div>
  </div>
}

export function Loading({ text = 'Loading…' }: { text?: string }) {
  return <div className="state" role="status"><LoaderCircle className="animate-spin" size={18} aria-hidden />{text}</div>
}

export function Failure({ error, retry }: { error: Error; retry?: () => void }) {
  return <div className="state error" role="alert">
    <AlertCircle size={18} aria-hidden /><span>{error.message}</span>
    {retry && <Button onClick={retry}>Try again</Button>}
  </div>
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><h2>{title}</h2>{children && <p>{children}</p>}</div>
}

export function Missing() {
  return <><PageHeading title="Page unavailable" /><section className="panel section"><Empty title="This page could not be found">Open Cases to return to your workspace.</Empty><Link to="/">Back to case queue</Link></section></>
}
