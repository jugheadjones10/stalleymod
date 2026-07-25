import { CheckCircle2, FlaskConical, Plus, Trash2, XCircle } from "lucide-react"
import { FormEvent, useState } from "react"
import type { AssertionReport, ScenarioAssertion } from "../types"

export function AssertionsPanel({
  assertions,
  report,
  busy,
  ready,
  error,
  onSave,
  onRun,
}: {
  assertions: ScenarioAssertion[]
  report?: AssertionReport | null
  busy: boolean
  ready: boolean
  error?: string | null
  onSave: (assertions: ScenarioAssertion[]) => Promise<void>
  onRun: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    const form = new FormData(event.currentTarget)
    const operator = String(form.get("operator")) as ScenarioAssertion["operator"]
    const source = String(form.get("source")) as ScenarioAssertion["source"]
    const assertion: ScenarioAssertion = {
      id: String(form.get("id")),
      source,
      path: String(form.get("path")),
      operator,
    }
    if (source === "action") assertion.actionIndex = Number(form.get("actionIndex"))
    if (!["exists", "notExists"].includes(operator)) {
      try {
        assertion.expected = JSON.parse(String(form.get("expected")))
      } catch {
        setFormError("Expected value must be valid JSON, such as \"LevelUpMenu\" or true.")
        return
      }
    }
    try {
      await onSave([...assertions, assertion])
      setAdding(false)
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : "Could not save assertion")
    }
  }

  return (
    <div className="grid gap-3 p-3">
      <div className="flex items-center gap-2">
        <div>
          <h3 className="text-xs font-semibold">Regression assertions</h3>
          <p className="mt-1 text-[11px] text-muted-foreground">JSON Pointer paths check stable fields only.</p>
        </div>
        <button type="button" className="button secondary ml-auto" onClick={() => setAdding(true)} disabled={busy}>
          <Plus />
          Add
        </button>
        <button type="button" className="button primary" onClick={onRun} disabled={!ready || busy}>
          <FlaskConical />
          Run
        </button>
      </div>

      {(error || formError) && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">
          {error || formError}
        </p>
      )}

      {report && (
        <div className={`rounded-md border px-3 py-2 text-xs ${report.passed ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200" : "bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200"}`}>
          <strong>{report.passed ? "Passed" : "Failed"}</strong>
          <span className="ml-2">{report.passedCount} passed · {report.failedCount} failed</span>
        </div>
      )}

      {adding && (
        <form className="grid gap-3 rounded-lg border bg-muted/20 p-3" onSubmit={add}>
          <div className="grid grid-cols-2 gap-2">
            <label className="field">
              <span>ID</span>
              <input name="id" required pattern="[a-z0-9]+(?:-[a-z0-9]+)*" placeholder="menu-type" />
            </label>
            <label className="field">
              <span>Source</span>
              <select name="source" defaultValue="observation">
                <option value="observation">Observation</option>
                <option value="action">Action result</option>
              </select>
            </label>
          </div>
          <div className="grid grid-cols-[1fr_6rem] gap-2">
            <label className="field">
              <span>JSON Pointer</span>
              <input name="path" required placeholder="/CurrentMenuData/type" />
            </label>
            <label className="field">
              <span>Action #</span>
              <input name="actionIndex" type="number" min={0} defaultValue={0} />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="field">
              <span>Operator</span>
              <select name="operator" defaultValue="equals">
                <option value="equals">equals</option>
                <option value="notEquals">not equals</option>
                <option value="contains">contains</option>
                <option value="exists">exists</option>
                <option value="notExists">does not exist</option>
              </select>
            </label>
            <label className="field">
              <span>Expected JSON</span>
              <input name="expected" defaultValue="null" className="font-mono" />
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="button secondary" onClick={() => setAdding(false)}>Cancel</button>
            <button type="submit" className="button primary" disabled={busy}>Save assertion</button>
          </div>
        </form>
      )}

      {!assertions.length && !adding && (
        <p className="rounded-lg border border-dashed p-4 text-center text-xs leading-5 text-muted-foreground">
          No assertions yet. Add one for a stable observation field or action result.
        </p>
      )}

      {assertions.map((assertion) => {
        const outcome = report?.results.find((result) => result.id === assertion.id)
        return (
          <article key={assertion.id} className="rounded-lg border bg-card p-3">
            <div className="flex items-start gap-2">
              {outcome?.passed === true && <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />}
              {outcome?.passed === false && <XCircle className="mt-0.5 size-4 shrink-0 text-red-600" />}
              <div className="min-w-0">
                <h4 className="truncate text-xs font-semibold">{assertion.id}</h4>
                <p className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
                  {assertion.source}{assertion.source === "action" ? `[${assertion.actionIndex}]` : ""}{assertion.path || "/"} {assertion.operator}
                </p>
                {"expected" in assertion && (
                  <pre className="mt-2 overflow-auto text-[11px]">expected {JSON.stringify(assertion.expected)}</pre>
                )}
                {outcome && (
                  <pre className="mt-1 overflow-auto text-[11px]">actual {JSON.stringify(outcome.actual)}</pre>
                )}
              </div>
              <button
                type="button"
                className="icon-button ml-auto"
                aria-label={`Delete assertion ${assertion.id}`}
                disabled={busy}
                onClick={() => {
                  void onSave(assertions.filter((item) => item.id !== assertion.id))
                    .catch((reason) => setFormError(reason instanceof Error ? reason.message : "Could not delete assertion"))
                }}
              >
                <Trash2 />
              </button>
            </div>
          </article>
        )
      })}
    </div>
  )
}
