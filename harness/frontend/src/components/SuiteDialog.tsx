import { CheckCircle2, CircleStop, FlaskConical, X, XCircle } from "lucide-react"
import type { ScenarioSummary, SuiteState } from "../types"

export function SuiteDialog({
  open,
  scenarios,
  suite,
  busy,
  onClose,
  onStart,
  onStop,
}: {
  open: boolean
  scenarios: ScenarioSummary[]
  suite: SuiteState
  busy: boolean
  onClose: () => void
  onStart: (ids: string[]) => void
  onStop: () => void
}) {
  if (!open) return null
  const running = suite.status === "running"

  function submit(form: HTMLFormElement) {
    const ids = new FormData(form).getAll("scenarioId").map(String)
    onStart(ids)
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal-card max-w-2xl" role="dialog" aria-modal="true" aria-labelledby="suite-title">
        <header className="modal-header">
          <span className="modal-icon"><FlaskConical /></span>
          <div>
            <h2 id="suite-title" className="text-sm font-semibold">Regression suite</h2>
            <p className="mt-1 text-xs text-muted-foreground">Each scenario restores its fixture, replays all actions, then runs assertions.</p>
          </div>
          <button type="button" className="icon-button ml-auto" onClick={onClose} aria-label="Close suite">
            <X />
          </button>
        </header>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            submit(event.currentTarget)
          }}
        >
          <div className="grid max-h-[60vh] gap-4 overflow-auto p-5">
            {!running && (
              <fieldset className="grid gap-2">
                <legend className="mb-2 text-xs font-semibold">Scenarios</legend>
                {scenarios.map((scenario) => (
                  <label key={scenario.id} className="flex items-center gap-3 rounded-md border px-3 py-2 text-xs">
                    <input type="checkbox" name="scenarioId" value={scenario.id} defaultChecked />
                    <span className="min-w-0 flex-1">
                      <strong className="block truncate font-medium">{scenario.name}</strong>
                      <span className="text-muted-foreground">{scenario.actionCount} actions · {scenario.snapshotCount} snapshots</span>
                    </span>
                  </label>
                ))}
              </fieldset>
            )}
            {suite.status !== "idle" && (
              <section>
                <div className="flex items-center text-xs">
                  <strong className="capitalize">{suite.status}</strong>
                  <span className="ml-auto tabular-nums">{suite.completedCount} / {suite.total}</span>
                </div>
                <progress className="suite-progress mt-2" value={suite.completedCount} max={suite.total || 1} />
                {suite.currentScenarioId && <p className="mt-2 text-xs text-muted-foreground">Running {suite.currentScenarioId}…</p>}
                <div className="mt-3 grid gap-2">
                  {suite.results.map((result) => (
                    <div key={result.scenarioId} className="flex items-center gap-2 rounded-md border px-3 py-2 text-xs">
                      {result.status === "passed" ? <CheckCircle2 className="size-4 text-emerald-600" /> : <XCircle className="size-4 text-red-600" />}
                      <strong>{result.scenarioId}</strong>
                      <span className="ml-auto text-muted-foreground">{result.durationMs} ms</span>
                      <span className="capitalize">{result.status}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
          <footer className="modal-footer">
            {running ? (
              <button type="button" className="button danger" onClick={onStop} disabled={busy}><CircleStop />Stop suite</button>
            ) : (
              <button type="submit" className="button primary" disabled={busy || !scenarios.length}><FlaskConical />Run selected</button>
            )}
          </footer>
        </form>
      </section>
    </div>
  )
}
