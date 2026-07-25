import {
  Activity,
  Bug,
  Camera,
  CircleStop,
  Database,
  FileJson2,
  FlaskConical,
  Image,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  ScrollText,
  SkipForward,
  StepForward,
  Terminal,
  Trash2,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import type {
  ActionRecord,
  Preview,
  RunState,
  ScenarioAssertion,
  ScenarioDetails,
} from "../types"
import { ActionComposer } from "./ActionComposer"
import { AssertionsPanel } from "./AssertionsPanel"
import { PreviewCanvas } from "./PreviewCanvas"
import { StatusBadge } from "./StatusBadge"

type InspectorTab = "action" | "snapshots" | "assertions" | "logs"
type ViewTab = "observation" | "preview"

function JsonBlock({ value, empty }: { value: unknown; empty: string }) {
  if (value == null) {
    return (
      <div className="grid h-full place-items-center p-8 text-center">
        <div>
          <FileJson2 className="mx-auto size-6 text-muted-foreground" />
          <p className="mt-2 text-xs font-medium">{empty}</p>
          <p className="mt-1 text-xs text-muted-foreground">Start the scenario to inspect the normal agent payload.</p>
        </div>
      </div>
    )
  }
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>
}

function selectedObservation(run: RunState) {
  if (run.observation != null) return run.observation
  if (!run.observationRaw) return null
  try {
    return JSON.parse(run.observationRaw)
  } catch {
    return run.observationRaw
  }
}

function actionLabel(action: ActionRecord | null, index: number | null) {
  if (!action || index == null) return "No action selected"
  return action.action ?? action.method ?? action.name ?? `Action ${index + 1}`
}

interface Props {
  scenario: ScenarioDetails
  run: RunState
  preview: Preview | null
  selectedAction: ActionRecord | null
  selectedActionIndex: number | null
  port: number
  attach: boolean
  busy: boolean
  onPortChange: (port: number) => void
  onAttachChange: (attach: boolean) => void
  onStart: () => void
  onReset: () => void
  onStop: () => void
  onObserve: () => void
  onPreview: () => void
  onSendAction: (action: string, arguments_: string[]) => Promise<void>
  onToggleRecording: () => void
  onRerecord: (index: number) => void
  onReplayStart: () => void
  onReplayPause: () => void
  onReplayResume: () => void
  onReplayStep: () => void
  onReplayStop: () => void
  onMarkSnapshot: () => void
  onDeleteSnapshot: (name: string) => void
  onSaveAssertions: (assertions: ScenarioAssertion[]) => Promise<void>
  onRunAssertions: () => void
}

export function ScenarioWorkspace(props: Props) {
  const {
    scenario, run, preview, selectedAction, selectedActionIndex, port, attach, busy,
    onPortChange, onAttachChange, onStart, onReset, onStop, onObserve, onPreview,
    onSendAction, onToggleRecording, onRerecord, onReplayStart, onReplayPause,
    onReplayResume, onReplayStep, onReplayStop, onMarkSnapshot, onDeleteSnapshot,
    onSaveAssertions, onRunAssertions,
  } = props
  const [tab, setTab] = useState<InspectorTab>("action")
  const [view, setView] = useState<ViewTab>("observation")
  const logsRef = useRef<HTMLDivElement>(null)
  const active = ["preparing", "launching", "connecting", "loading", "ready"].includes(run.status)
  const starting = ["preparing", "launching", "connecting", "loading"].includes(run.status)
  const ready = run.status === "ready"
  const canReset = Boolean(run.scenarioId) && ["ready", "error"].includes(run.status)
  const replayStatus = run.replay?.status ?? "idle"
  const replayActive = ["running", "paused", "stepping"].includes(replayStatus)
  const replayExecuting = ["running", "stepping"].includes(replayStatus)
  const observation = useMemo(() => selectedObservation(run), [run])

  useEffect(() => {
    if (tab === "logs" && logsRef.current) logsRef.current.scrollTop = logsRef.current.scrollHeight
  }, [run.logs, tab])

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null
      if (target?.matches("input, textarea, select")) return
      if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "s") {
        event.preventDefault()
        if (ready && !busy && !replayExecuting && !run.pendingSnapshot) onMarkSnapshot()
      }
    }
    window.addEventListener("keydown", shortcut)
    return () => window.removeEventListener("keydown", shortcut)
  }, [busy, onMarkSnapshot, ready, replayExecuting, run.pendingSnapshot])

  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <header className="flex min-h-14 shrink-0 flex-wrap items-center gap-2 border-b px-3 py-2">
        <div className="min-w-32 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-sm font-semibold">{scenario.name}</h1>
            <StatusBadge status={run.status} />
          </div>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{scenario.description || scenario.id}</p>
        </div>
        <label className="compact-field">
          <span>Port</span>
          <input type="number" min={1} max={65535} value={port} disabled={active || busy} onChange={(event) => onPortChange(Number(event.target.value))} />
        </label>
        <label className="flex h-8 items-center gap-2 rounded-md border px-2 text-xs">
          <input type="checkbox" checked={attach} disabled={active || busy} onChange={(event) => onAttachChange(event.target.checked)} />
          <Bug className="size-3.5 text-muted-foreground" />
          Attach
        </label>
        <button type="button" className="button primary" onClick={onStart} disabled={active || busy}><Play />{starting ? "Starting…" : "Start"}</button>
        <button type="button" className="button secondary" onClick={onReset} disabled={!canReset || busy}><RotateCcw />Reset</button>
        <button type="button" className="icon-button bordered" onClick={onStop} disabled={!active || busy} aria-label="Stop run"><CircleStop /></button>
      </header>

      <div className="flex shrink-0 flex-wrap items-center gap-1 border-b bg-muted/30 px-3 py-2">
        <div className="mr-2 hidden items-center gap-4 xl:flex">
          <span className="stat"><Database /><span>fixture</span><strong>{scenario.farmName}</strong></span>
          <span className="stat"><Activity /><span>actions</span><strong>{scenario.actions.length}</strong></span>
          <span className="stat"><Camera /><span>snapshots</span><strong>{scenario.snapshots.length}</strong></span>
        </div>
        <button type="button" className={`button ${run.recording ? "recording" : "secondary"}`} disabled={!ready || replayActive || busy} onClick={onToggleRecording}>
          <span className="size-2 rounded-full bg-current" />{run.recording ? "Stop recording" : "Record"}
        </button>
        <span className="mx-1 h-5 border-l" />
        {replayStatus === "running" ? (
          <button type="button" className="button secondary" onClick={onReplayPause} disabled={busy}><Pause />Pause</button>
        ) : replayStatus === "paused" ? (
          <button type="button" className="button secondary" onClick={onReplayResume} disabled={busy}><Play />Resume</button>
        ) : (
          <button type="button" className="button secondary" onClick={onReplayStart} disabled={!ready || !scenario.actions.length || run.recording || busy}><SkipForward />Run all</button>
        )}
        <button type="button" className="button secondary" onClick={onReplayStep} disabled={!ready || replayStatus === "running" || !scenario.actions.length || run.recording || busy}><StepForward />Step</button>
        <button type="button" className="icon-button" onClick={onReplayStop} disabled={!replayActive || busy} aria-label="Stop replay"><CircleStop /></button>
        <span className="text-[11px] text-muted-foreground">{run.replay?.nextIndex ?? 0}/{run.replay?.total ?? scenario.actions.length}</span>
        <button type="button" className="button secondary ml-auto" onClick={onMarkSnapshot} disabled={!ready || replayExecuting || Boolean(run.pendingSnapshot) || busy} title="⌘/Ctrl+Shift+S"><Camera />Snapshot</button>
      </div>

      {run.error && <div className="border-b bg-red-50 px-4 py-2 text-xs text-red-700 dark:bg-red-950 dark:text-red-300">{run.error}</div>}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <section className="flex min-h-64 min-w-0 flex-1 flex-col">
          <div className="flex h-11 shrink-0 items-end border-b px-2">
            <button type="button" className={`tab ${view === "observation" ? "active" : ""}`} onClick={() => setView("observation")}><FileJson2 />Observation</button>
            <button type="button" className={`tab ${view === "preview" ? "active" : ""}`} onClick={() => setView("preview")}><Image />Game preview</button>
            {view === "observation" ? (
              <button type="button" className="button secondary mb-1 ml-auto" onClick={onObserve} disabled={!ready || replayExecuting || busy}><RefreshCw />Refresh</button>
            ) : (
              <button type="button" className="button secondary mb-1 ml-auto" onClick={onPreview} disabled={!ready || replayExecuting || busy}><Camera />Capture frame</button>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-auto bg-code">
            {view === "observation" ? <JsonBlock value={observation} empty="No live observation" /> : <PreviewCanvas preview={preview} />}
          </div>
        </section>

        <aside className="flex max-h-[46vh] min-h-64 shrink-0 flex-col border-t lg:max-h-none lg:w-[410px] lg:border-l lg:border-t-0">
          <div className="flex h-11 shrink-0 items-end overflow-x-auto border-b px-2">
            {([
              ["action", ScrollText, "Action"],
              ["snapshots", Camera, "Snapshots"],
              ["assertions", FlaskConical, "Assertions"],
              ["logs", Terminal, "Logs"],
            ] as const).map(([id, Icon, label]) => (
              <button key={id} type="button" className={`tab ${tab === id ? "active" : ""}`} onClick={() => setTab(id)}>
                <Icon />{label}
                {id === "snapshots" && <span>{scenario.snapshots.length}</span>}
                {id === "assertions" && <span>{scenario.assertions.length}</span>}
                {id === "logs" && <span>{run.logs.length}</span>}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {tab === "action" && (
              <>
                <ActionComposer disabled={!ready || busy || replayActive} onSend={onSendAction} />
                <div className="p-4">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{selectedActionIndex == null ? "Timeline selection" : `Action ${selectedActionIndex + 1}`}</p>
                  <div className="mt-1 flex items-center gap-2">
                    <h3 className="min-w-0 flex-1 truncate text-sm font-semibold">{actionLabel(selectedAction, selectedActionIndex)}</h3>
                    {selectedActionIndex != null && (
                      <button type="button" className="button secondary" disabled={!ready || busy || replayActive} onClick={() => onRerecord(selectedActionIndex)}>
                        Re-record here
                      </button>
                    )}
                  </div>
                  {selectedAction ? (
                    <>
                      <pre className="mt-4 overflow-auto rounded-lg border bg-code p-3 text-[11px] leading-5">{JSON.stringify(selectedAction, null, 2)}</pre>
                      {scenario.snapshots.filter((snapshot) => snapshot.afterAction === selectedActionIndex! + 1).map((snapshot) => (
                        <div key={snapshot.name} className="mt-2 rounded-md border px-3 py-2 text-xs">
                          <Camera className="mr-2 inline size-3.5 text-muted-foreground" />
                          Checkpoint: <strong>{snapshot.name}</strong>
                        </div>
                      ))}
                    </>
                  ) : (
                    <p className="mt-3 text-xs leading-5 text-muted-foreground">Select an action to inspect its arguments, recorded result, timing, and error.</p>
                  )}
                </div>
              </>
            )}
            {tab === "snapshots" && (
              <div className="grid gap-2 p-3">
                {!scenario.snapshots.length && <p className="p-3 text-xs leading-5 text-muted-foreground">No saved checkpoints. Press Snapshot or ⌘/Ctrl+Shift+S while the run is ready.</p>}
                {scenario.snapshots.map((snapshot) => (
                  <article key={snapshot.name} className="rounded-lg border bg-card">
                    <div className="flex items-center px-3 py-1.5 text-xs font-medium">
                      <span>{snapshot.name}</span>
                      <button type="button" className="icon-button ml-auto" aria-label={`Delete snapshot ${snapshot.name}`} onClick={() => onDeleteSnapshot(snapshot.name)}><Trash2 /></button>
                    </div>
                    <details className="border-t">
                      <summary className="cursor-pointer px-3 py-2 text-[11px] text-muted-foreground">View observation</summary>
                      <pre className="max-h-96 overflow-auto border-t bg-code p-3 text-[11px] leading-5">{snapshot.error ?? JSON.stringify(snapshot.observation, null, 2)}</pre>
                    </details>
                  </article>
                ))}
              </div>
            )}
            {tab === "assertions" && (
              <AssertionsPanel assertions={scenario.assertions} report={run.assertionReport} busy={busy} ready={ready} error={scenario.assertionsError} onSave={onSaveAssertions} onRun={onRunAssertions} />
            )}
            {tab === "logs" && (
              <div ref={logsRef} className="h-full overflow-auto bg-code p-3 font-mono">
                {!run.logs.length && <p className="text-xs text-muted-foreground">Harness and SMAPI output will appear here.</p>}
                {run.logs.map((entry, index) => (
                  <p key={`${entry.time}-${index}`} className={`log-line ${entry.level}`}><time>{entry.time ? entry.time.slice(11, 19) : "--:--:--"}</time><strong>{entry.level.toUpperCase()}</strong><span>{entry.message}</span></p>
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>
    </main>
  )
}
