import {
  ArrowLeft,
  Bug,
  Camera,
  CircleStop,
  Eye,
  Pause,
  Play,
  RotateCcw,
  StepForward,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { post, put, useDebug } from "../lib/api"
import type { DebugState, Preview } from "../types"
import { PreviewCanvas } from "./PreviewCanvas"
import { StatusBadge } from "./StatusBadge"

interface DebugRequest {
  runId: string
  eventSequence: number
  function: string
}

export function DebugWorkspace({
  request,
  token,
  initial,
}: {
  request: DebugRequest
  token: string
  initial: DebugState
}) {
  const { data: debug, mutate } = useDebug(initial)
  const loaded = useRef("")
  const [port, setPort] = useState(initial.port || 10783)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<"observation" | "preview">("observation")
  const key = `${request.runId}:${request.eventSequence}:${request.function}`

  useEffect(() => {
    if (loaded.current === key) return
    loaded.current = key
    setError(null)
    void post<DebugState>("/api/debug/load", token, request)
      .then((state) => {
        setPort(state.port || 10783)
        return mutate(state, false)
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load debug target"))
  }, [key, mutate, request, token])

  const target = debug?.target
  const session = debug?.session
  const lines = useMemo(() => target?.source.split("\n") ?? [], [target?.source])
  const breakpoints = new Set(debug?.breakpoints ?? session?.breakpoints ?? [])
  const currentLine = target && session?.currentLine
    ? session.currentLine - target.sourceStartLine + 1
    : null

  async function command(path: string, body: object = {}) {
    setError(null)
    try {
      const state = await post<DebugState>(path, token, body)
      await mutate(state, false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Debugger request failed")
    }
  }

  async function toggleBreakpoint(line: number) {
    const next = breakpoints.has(line)
      ? [...breakpoints].filter((value) => value !== line)
      : [...breakpoints, line]
    setError(null)
    try {
      const state = await put<DebugState>("/api/debug/breakpoints", token, {
        lines: next.sort((left, right) => left - right),
      })
      await mutate(state, false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update breakpoints")
    }
  }

  async function capturePreview() {
    setError(null)
    try {
      const result = await post<{ preview: Preview }>("/api/debug/preview", token)
      setPreview(result.preview)
      setView("preview")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not capture preview")
    }
  }

  const active = ["preparing", "launching", "connecting", "loading", "restarting", "running", "paused"].includes(debug?.status ?? "")
  const runtimeReady = ["running", "paused", "completed", "failed"].includes(debug?.status ?? "")
  const canStop = !["idle", "ready", "error"].includes(debug?.status ?? "idle")
  const observation = session?.observation ?? target?.checkpoint?.observation

  async function refreshObservation() {
    setError(null)
    try {
      await post("/api/debug/observe", token)
      await mutate()
      setView("observation")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not refresh observation")
    }
  }

  return (
    <div className="flex h-svh min-w-0 flex-col overflow-hidden">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
        <a className="icon-button" href="/" aria-label="Back to scenarios">
          <ArrowLeft />
        </a>
        <span className="grid size-7 place-items-center rounded-md bg-muted"><Bug className="size-4" /></span>
        <div className="min-w-0">
          <h1 className="truncate text-sm font-medium">{target?.function ?? request.function}</h1>
          <p className="truncate text-[11px] text-muted-foreground">
            {request.runId} · event {request.eventSequence}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {target && (
            <span className="rounded-full border px-2 py-1 text-[10px] text-muted-foreground">
              {target.mode === "checkpoint"
                ? `Exact checkpoint · ${target.checkpoint?.id}`
                : target.mode === "task-start"
                  ? `Task start · ${target.taskStart?.saveType}`
                  : "Source only · current scenario"}
            </span>
          )}
          <StatusBadge status={debug?.status ?? "loading"} />
          <label className="compact-field">
            Port
            <input
              type="number"
              min={1}
              max={65535}
              value={port}
              onChange={(event) => setPort(Number(event.target.value))}
              disabled={active}
            />
          </label>
          <button
            className="button primary"
            type="button"
            disabled={!target || active}
            onClick={() => void command("/api/debug/start", { port })}
          >
            <Play /> Run
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={debug?.status !== "running"}
            onClick={() => void command("/api/debug/pause")}
          >
            <Pause /> Pause
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={debug?.status !== "paused"}
            onClick={() => void command("/api/debug/continue")}
          >
            <Play /> Continue
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={debug?.status !== "paused"}
            onClick={() => void command("/api/debug/step")}
          >
            <StepForward /> Step
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={!debug?.canRestart}
            onClick={() => void command("/api/debug/restart")}
          >
            <RotateCcw /> Restart
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={!canStop}
            onClick={() => void command("/api/debug/stop")}
          >
            <CircleStop /> Stop
          </button>
        </div>
      </header>

      {(error || debug?.error || session?.error) && (
        <div className="shrink-0 border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error ?? debug?.error ?? session?.error}
        </div>
      )}
      {target?.mode === "source-only" && (
        <div className="shrink-0 border-b bg-amber-50 px-4 py-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          This version has no retained failure checkpoint. Start a scenario first, then run it against that current state.
        </div>
      )}
      {target?.mode === "task-start" && (
        <div className="shrink-0 border-b bg-amber-50 px-4 py-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
          Restores {target.taskStart?.saveType} and applies {target.taskStart?.initCommandCount} task setup commands. Earlier function actions are not replayed.
        </div>
      )}

      <main className="grid min-h-0 flex-1 grid-cols-[minmax(28rem,3fr)_minmax(22rem,2fr)]">
        <section className="min-h-0 overflow-auto border-r bg-code font-mono text-xs leading-5">
          {lines.map((line, index) => {
            const lineNumber = index + 1
            const breakpoint = breakpoints.has(lineNumber)
            const current = currentLine === lineNumber
            return (
              <div
                key={lineNumber}
                className={`grid min-w-max grid-cols-[2rem_3rem_minmax(0,1fr)] ${current ? "bg-amber-200/50 dark:bg-amber-800/30" : ""}`}
              >
                <button
                  type="button"
                  className="grid place-items-center border-r hover:bg-muted"
                  aria-label={`${breakpoint ? "Remove" : "Add"} breakpoint on line ${lineNumber}`}
                  onClick={() => void toggleBreakpoint(lineNumber)}
                >
                  {breakpoint && <span className="size-2.5 rounded-full bg-red-500" />}
                </button>
                <span className="select-none border-r pr-2 text-right text-muted-foreground">{lineNumber}</span>
                <code className="whitespace-pre px-3">{line || " "}</code>
              </div>
            )
          })}
        </section>

        <aside className="grid min-h-0 grid-rows-[minmax(12rem,3fr)_minmax(10rem,2fr)]">
          <section className="flex min-h-0 flex-col border-b">
            <div className="flex h-10 shrink-0 items-center border-b px-2">
              <button className={`tab ${view === "observation" ? "active" : ""}`} type="button" onClick={() => setView("observation")}>
                Observation
              </button>
              <button className={`tab ${view === "preview" ? "active" : ""}`} type="button" onClick={() => setView("preview")}>
                Preview
              </button>
              <div className="ml-auto flex gap-1">
                <button className="icon-button" type="button" disabled={!runtimeReady} onClick={() => void refreshObservation()} aria-label="Refresh observation"><Eye /></button>
                <button className="icon-button" type="button" disabled={!runtimeReady} onClick={() => void capturePreview()} aria-label="Capture game preview"><Camera /></button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              {view === "preview" ? (
                <PreviewCanvas preview={preview} />
              ) : (
                <pre className="json-block">{observation ? JSON.stringify(observation, null, 2) : "No observation captured."}</pre>
              )}
            </div>
          </section>

          <section className="grid min-h-0 grid-cols-2">
            <div className="min-h-0 overflow-auto border-r p-3">
              <h2 className="mb-2 text-xs font-medium">Call stack</h2>
              {session?.stack.length ? session.stack.map((frame, index) => (
                <div key={`${frame.function}:${frame.line}:${index}`} className="mb-1 rounded border px-2 py-1.5 font-mono text-[11px]">
                  {frame.function}<span className="text-muted-foreground">:{frame.line}</span>
                </div>
              )) : <p className="text-xs text-muted-foreground">Available while paused.</p>}
            </div>
            <div className="min-h-0 overflow-auto p-3">
              <h2 className="mb-2 text-xs font-medium">Locals</h2>
              {session && Object.keys(session.locals).length ? Object.entries(session.locals).map(([name, value]) => (
                <div key={name} className="mb-2 text-[11px]">
                  <code className="font-medium">{name}</code>
                  <pre className="mt-0.5 whitespace-pre-wrap break-all text-muted-foreground">{value}</pre>
                </div>
              )) : <p className="text-xs text-muted-foreground">Available while paused.</p>}
            </div>
          </section>
        </aside>
      </main>
    </div>
  )
}
