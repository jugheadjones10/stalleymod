import { Camera, X } from "lucide-react"
import { FormEvent, useEffect, useRef, useState } from "react"

export function SnapshotDialog({
  open,
  busy,
  onCancel,
  onSave,
}: {
  open: boolean
  busy: boolean
  onCancel: () => void
  onSave: (name: string) => void
}) {
  const [name, setName] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setName("")
      window.setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [open])

  if (!open) return null

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSave(name)
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal-card max-w-md" role="dialog" aria-modal="true" aria-labelledby="snapshot-title">
        <header className="modal-header">
          <span className="modal-icon"><Camera /></span>
          <div>
            <h2 id="snapshot-title" className="text-sm font-semibold">Name this checkpoint</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              The exact observation was captured when you pressed the shortcut.
            </p>
          </div>
          <button type="button" className="icon-button ml-auto" onClick={onCancel} aria-label="Discard checkpoint">
            <X />
          </button>
        </header>
        <form onSubmit={submit}>
          <div className="p-5">
            <label className="field">
              <span>Snapshot name</span>
              <input
                ref={inputRef}
                required
                maxLength={80}
                pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                value={name}
                disabled={busy}
                onChange={(event) => setName(event.target.value)}
                placeholder="level-up-menu-visible"
              />
              <small>Lowercase kebab-case. Existing snapshots are never overwritten.</small>
            </label>
          </div>
          <footer className="modal-footer">
            <button type="button" className="button secondary" onClick={onCancel} disabled={busy}>Discard</button>
            <button type="submit" className="button primary" disabled={busy}>Save checkpoint</button>
          </footer>
        </form>
      </section>
    </div>
  )
}
