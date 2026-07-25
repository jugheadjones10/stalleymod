import { Import, X } from "lucide-react"
import { FormEvent, useEffect, useState } from "react"
import type { SaveSummary } from "../types"

function slug(value: string) {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
}

export interface ImportValues {
  saveName: string
  scenarioId: string
  name: string
  description: string
}

export function ImportDialog({
  open,
  saves,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  open: boolean
  saves: SaveSummary[]
  busy: boolean
  error: string | null
  onClose: () => void
  onSubmit: (values: ImportValues) => void
}) {
  const [name, setName] = useState("")
  const [scenarioId, setScenarioId] = useState("")
  const [idEdited, setIdEdited] = useState(false)

  useEffect(() => {
    if (!open) {
      setName("")
      setScenarioId("")
      setIdEdited(false)
    }
  }, [open])

  if (!open) return null

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    onSubmit({
      saveName: String(form.get("saveName") ?? ""),
      scenarioId,
      name,
      description: String(form.get("description") ?? ""),
    })
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4" role="presentation">
      <section
        className="w-full max-w-lg rounded-xl border bg-background shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-title"
      >
        <div className="flex items-start gap-3 border-b p-5">
          <span className="grid size-9 place-items-center rounded-lg bg-muted">
            <Import className="size-4" />
          </span>
          <div>
            <h2 id="import-title" className="text-sm font-semibold">Import save fixture</h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Copies a local Stardew save into a new, isolated scenario.
            </p>
          </div>
          <button type="button" className="icon-button ml-auto" onClick={onClose} aria-label="Close">
            <X />
          </button>
        </div>
        <form onSubmit={submit}>
          <div className="grid gap-4 p-5">
            <label className="field">
              <span>Local save</span>
              <select name="saveName" required disabled={!saves.length || busy}>
                {!saves.length && <option value="">No local saves detected</option>}
                {saves.map((save) => (
                  <option key={save.name} value={save.name}>
                    {save.farmName} — {save.uniqueId}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Scenario name</span>
              <input
                required
                maxLength={120}
                value={name}
                disabled={busy}
                onChange={(event) => {
                  setName(event.target.value)
                  if (!idEdited) setScenarioId(slug(event.target.value))
                }}
                placeholder="Ordinary level-up"
              />
            </label>
            <label className="field">
              <span>Scenario ID</span>
              <input
                required
                pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                value={scenarioId}
                disabled={busy}
                onChange={(event) => {
                  setScenarioId(event.target.value)
                  setIdEdited(Boolean(event.target.value))
                }}
                placeholder="ordinary-level-up"
              />
              <small>Lowercase kebab-case; this becomes the fixture folder name.</small>
            </label>
            <label className="field">
              <span>Description</span>
              <textarea
                name="description"
                maxLength={2000}
                rows={3}
                disabled={busy}
                placeholder="What game state and behavior does this reproduce?"
              />
            </label>
            {error && <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">{error}</p>}
          </div>
          <div className="flex justify-end gap-2 border-t bg-muted/30 p-4">
            <button type="button" className="button secondary" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="button primary" disabled={!saves.length || busy}>
              {busy ? "Importing…" : "Import fixture"}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
