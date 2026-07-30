import { Import, PlaySquare, Trash2 } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { ActionTimeline } from "./components/ActionTimeline"
import { ConfirmDialog } from "./components/ConfirmDialog"
import { DebugWorkspace } from "./components/DebugWorkspace"
import { ImportDialog, type ImportValues } from "./components/ImportDialog"
import { ScenarioSidebar } from "./components/ScenarioSidebar"
import { ScenarioWorkspace } from "./components/ScenarioWorkspace"
import { SnapshotDialog } from "./components/SnapshotDialog"
import { SuiteDialog } from "./components/SuiteDialog"
import {
  post,
  put,
  refreshCatalog,
  refreshScenario,
  useBootstrap,
  useRun,
  useScenario,
  useSuite,
} from "./lib/api"
import type {
  Preview,
  RunState,
  ScenarioAssertion,
  ScenarioSummary,
  SuiteState,
} from "./types"

function EmptyState({ error }: { error?: string }) {
  return (
    <main className="grid min-w-0 flex-1 place-items-center">
      <div className="max-w-sm text-center">
        <img src="/duck.png" alt="" className="mx-auto size-10 opacity-60 [image-rendering:pixelated]" />
        <h1 className="mt-3 text-sm font-medium">{error ? "The harness could not start" : "Choose a scenario"}</h1>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">{error ?? "Select a fixture from the sidebar, or import a local Stardew save."}</p>
      </div>
    </main>
  )
}

const EMPTY_RUN: RunState = {
  status: "idle",
  scenarioId: null,
  logs: [],
  replay: { status: "idle", nextIndex: 0, total: 0, results: [] },
}

const EMPTY_SUITE: SuiteState = {
  status: "idle",
  passed: false,
  scenarioIds: [],
  completedCount: 0,
  total: 0,
  results: [],
}

export default function App() {
  const { data: bootstrap, error: bootstrapError } = useBootstrap()
  const { data: runData, mutate: mutateRun } = useRun(bootstrap?.run)
  const { data: suiteData, mutate: mutateSuite } = useSuite(bootstrap?.suite)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data: scenarioData } = useScenario(selectedId)
  const [selectedActionIndex, setSelectedActionIndex] = useState<number | null>(null)
  const [port, setPort] = useState(10783)
  const [attach, setAttach] = useState(false)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [importBusy, setImportBusy] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [snapshotToDelete, setSnapshotToDelete] = useState<string | null>(null)
  const [suiteOpen, setSuiteOpen] = useState(false)
  const debugRequest = useMemo(() => {
    const query = new URLSearchParams(window.location.search)
    const runId = query.get("run")
    const event = Number(query.get("event"))
    const functionName = query.get("function")
    return runId && Number.isInteger(event) && event >= 0 && functionName
      ? { runId, eventSequence: event, function: functionName }
      : null
  }, [])

  const scenarios = bootstrap?.catalog.scenarios ?? []
  const scenario = scenarioData?.scenario
  const run = runData ?? bootstrap?.run ?? EMPTY_RUN
  const suite = suiteData ?? bootstrap?.suite ?? EMPTY_SUITE

  useEffect(() => {
    if (!selectedId && scenarios.length) setSelectedId(scenarios[0].id)
  }, [scenarios, selectedId])

  useEffect(() => {
    setSelectedActionIndex(null)
    setPreview(null)
  }, [selectedId])

  useEffect(() => {
    if (run.port) setPort(run.port)
    if (typeof run.attached === "boolean") setAttach(run.attached)
  }, [run.attached, run.port])

  useEffect(() => {
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(null), 3600)
    return () => window.clearTimeout(timeout)
  }, [toast])

  const selectedAction = useMemo(() => {
    if (!scenario || selectedActionIndex == null) return null
    const persisted = scenario.actions[selectedActionIndex]
    if (!persisted) return null
    const replay = run.replay?.results.find((result) => result.index === selectedActionIndex)
    return replay ? { ...persisted, replayResult: replay } : persisted
  }, [run.replay?.results, scenario, selectedActionIndex])

  async function call<T>(
    path: string,
    body: object = {},
    options: { refreshScenario?: boolean; catalog?: boolean; method?: "POST" | "PUT" } = {},
  ): Promise<T> {
    if (!bootstrap) throw new Error("Harness is still loading")
    setBusy(true)
    try {
      const result = options.method === "PUT"
        ? await put<T>(path, bootstrap.token, body)
        : await post<T>(path, bootstrap.token, body)
      await mutateRun()
      if (options.refreshScenario && selectedId) await refreshScenario(selectedId)
      if (options.catalog) await refreshCatalog()
      return result
    } catch (error) {
      const message = error instanceof Error ? error.message : "Request failed"
      setToast(message)
      throw error
    } finally {
      setBusy(false)
    }
  }

  function quiet(action: () => Promise<unknown>) {
    void action().catch(() => undefined)
  }

  async function importScenario(values: ImportValues) {
    if (!bootstrap) return
    setImportBusy(true)
    setImportError(null)
    try {
      const result = await post<{ scenario: ScenarioSummary }>("/api/scenarios/import", bootstrap.token, values)
      await refreshCatalog()
      setSelectedId(result.scenario.id)
      setImportOpen(false)
      setToast("Scenario fixture created.")
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "Import failed")
    } finally {
      setImportBusy(false)
    }
  }

  async function deleteScenario() {
    if (!scenario) return
    await call(`/api/scenarios/${encodeURIComponent(scenario.id)}/delete`, { scenarioId: scenario.id }, { catalog: true })
    setDeleteOpen(false)
    setSelectedId(null)
    setToast("Scenario moved to scenarios/.trash.")
  }

  async function sendAction(action: string, arguments_: string[]) {
    await call("/api/run/actions", { action, arguments: arguments_ }, { refreshScenario: Boolean(run.recording) })
  }

  async function saveAssertions(assertions: ScenarioAssertion[]) {
    if (!scenario) return
    await call(
      `/api/scenarios/${encodeURIComponent(scenario.id)}/assertions`,
      { assertions },
      { refreshScenario: true, method: "PUT" },
    )
  }

  async function capturePreview() {
    const response = await call<{ preview: Preview }>("/api/run/preview")
    setPreview(response.preview)
  }

  async function saveSnapshot(name: string) {
    await call("/api/run/snapshots/save", { name }, { refreshScenario: true, catalog: true })
    setToast(`Saved snapshot “${name}”.`)
  }

  async function deleteSnapshot() {
    if (!scenario || !snapshotToDelete) return
    await call(
      `/api/scenarios/${encodeURIComponent(scenario.id)}/snapshots/${encodeURIComponent(snapshotToDelete)}/delete`,
      {},
      { refreshScenario: true, catalog: true },
    )
    setSnapshotToDelete(null)
  }

  async function startSuite(ids: string[]) {
    await call("/api/suite/start", { scenarioIds: ids, port, attach })
    await mutateSuite()
  }

  if (debugRequest && bootstrap) {
    return (
      <DebugWorkspace
        request={debugRequest}
        token={bootstrap.token}
        initial={bootstrap.debug}
      />
    )
  }

  return (
    <div className="flex h-svh min-w-0 overflow-hidden">
      <ScenarioSidebar
        scenarios={scenarios}
        selectedId={selectedId}
        catalogErrors={bootstrap?.catalog.errors.length ?? 0}
        onSelect={setSelectedId}
        onImport={() => { setImportError(null); setImportOpen(true) }}
        onDelete={() => setDeleteOpen(true)}
        onSuite={() => setSuiteOpen(true)}
      />
      {scenario && (
        <ActionTimeline
          actions={scenario.actions}
          runtimeResults={run.replay?.results ?? []}
          nextIndex={run.replay?.nextIndex ?? 0}
          selectedIndex={selectedActionIndex}
          onSelect={setSelectedActionIndex}
        />
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b px-2 md:hidden">
          <label className="sr-only" htmlFor="mobile-scenario">Scenario</label>
          <select
            id="mobile-scenario"
            className="h-8 min-w-0 flex-1 rounded-md border bg-background px-2 text-xs"
            value={selectedId ?? ""}
            onChange={(event) => setSelectedId(event.target.value)}
          >
            {scenarios.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <button type="button" className="icon-button bordered" onClick={() => setSuiteOpen(true)} aria-label="Regression suite"><PlaySquare /></button>
          <button type="button" className="icon-button bordered" onClick={() => setImportOpen(true)} aria-label="Import save fixture"><Import /></button>
          <button type="button" className="icon-button bordered text-red-600" onClick={() => setDeleteOpen(true)} aria-label="Delete selected scenario" disabled={!scenario}><Trash2 /></button>
        </div>
        {scenario ? (
          <ScenarioWorkspace
          scenario={scenario}
          run={run}
          preview={preview}
          selectedAction={selectedAction}
          selectedActionIndex={selectedActionIndex}
          port={port}
          attach={attach}
          busy={busy}
          onPortChange={setPort}
          onAttachChange={setAttach}
          onStart={() => quiet(() => call("/api/run/start", { scenarioId: scenario.id, port, attach }))}
          onReset={() => quiet(() => call("/api/run/reset"))}
          onStop={() => quiet(() => call("/api/run/stop"))}
          onObserve={() => quiet(() => call("/api/run/observe"))}
          onPreview={() => quiet(capturePreview)}
          onSendAction={sendAction}
          onToggleRecording={() => quiet(() => call(
            run.recording ? "/api/run/record/stop" : "/api/run/record/start",
            {},
            { refreshScenario: Boolean(run.recording) },
          ))}
          onRerecord={(index) => quiet(() => call("/api/run/record/start", { fromIndex: index }, { refreshScenario: true, catalog: true }))}
          onReplayStart={() => quiet(() => call("/api/run/replay/start"))}
          onReplayPause={() => quiet(() => call("/api/run/replay/pause"))}
          onReplayResume={() => quiet(() => call("/api/run/replay/resume"))}
          onReplayStep={() => quiet(() => call("/api/run/replay/step"))}
          onReplayStop={() => quiet(() => call("/api/run/replay/stop"))}
          onMarkSnapshot={() => quiet(() => call("/api/run/snapshots/mark"))}
          onDeleteSnapshot={setSnapshotToDelete}
          onSaveAssertions={saveAssertions}
          onRunAssertions={() => quiet(() => call("/api/run/assertions"))}
          />
        ) : (
          <EmptyState error={bootstrapError instanceof Error ? bootstrapError.message : undefined} />
        )}
      </div>

      <ImportDialog open={importOpen} saves={bootstrap?.saves ?? []} busy={importBusy} error={importError} onClose={() => !importBusy && setImportOpen(false)} onSubmit={importScenario} />
      <SnapshotDialog
        open={Boolean(run.pendingSnapshot)}
        busy={busy}
        onCancel={() => quiet(() => call("/api/run/snapshots/cancel"))}
        onSave={(name) => quiet(() => saveSnapshot(name))}
      />
      <ConfirmDialog
        open={deleteOpen}
        title={`Delete ${scenario?.name ?? "scenario"}?`}
        description="The scenario will be moved to scenarios/.trash, so it can be recovered manually. An active scenario must be stopped first."
        confirmLabel="Delete scenario"
        busy={busy}
        onCancel={() => setDeleteOpen(false)}
        onConfirm={() => quiet(deleteScenario)}
      />
      <ConfirmDialog
        open={Boolean(snapshotToDelete)}
        title={`Delete snapshot ${snapshotToDelete ?? ""}?`}
        description="This removes the persisted observation checkpoint from the scenario."
        confirmLabel="Delete snapshot"
        busy={busy}
        onCancel={() => setSnapshotToDelete(null)}
        onConfirm={() => quiet(deleteSnapshot)}
      />
      <SuiteDialog
        open={suiteOpen}
        scenarios={scenarios}
        suite={suite}
        busy={busy}
        onClose={() => setSuiteOpen(false)}
        onStart={(ids) => quiet(() => startSuite(ids))}
        onStop={() => quiet(async () => { await call("/api/suite/stop"); await mutateSuite() })}
      />
      {toast && <div className="fixed bottom-4 left-1/2 z-[70] -translate-x-1/2 rounded-lg bg-foreground px-3 py-2 text-xs font-medium text-background shadow-xl" role="status">{toast}</div>}
    </div>
  )
}
