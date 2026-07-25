import { AlertTriangle } from "lucide-react"

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  busy,
  onCancel,
  onConfirm,
}: {
  open: boolean
  title: string
  description: string
  confirmLabel: string
  busy: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  if (!open) return null
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal-card max-w-md" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <header className="modal-header">
          <span className="modal-icon text-amber-600"><AlertTriangle /></span>
          <div>
            <h2 id="confirm-title" className="text-sm font-semibold">{title}</h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
          </div>
        </header>
        <footer className="modal-footer">
          <button type="button" className="button secondary" onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button" className="button danger" onClick={onConfirm} disabled={busy}>{confirmLabel}</button>
        </footer>
      </section>
    </div>
  )
}
