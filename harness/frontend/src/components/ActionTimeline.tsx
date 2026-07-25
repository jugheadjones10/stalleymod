import {
  AlertCircle,
  CheckCircle2,
  CircleDashed,
  MousePointerClick,
} from "lucide-react"
import type { ActionRecord } from "../types"

function actionName(action: ActionRecord, index: number) {
  const value = action.action ?? action.method ?? action.name
  return typeof value === "string" ? value : `Action ${index + 1}`
}

function argumentsLabel(action: ActionRecord) {
  const value = action.arguments ?? action.args
  if (value == null) return "No arguments"
  const encoded = JSON.stringify(value)
  return encoded.length > 72 ? `${encoded.slice(0, 69)}…` : encoded
}

export function ActionTimeline({
  actions,
  runtimeResults,
  nextIndex,
  selectedIndex,
  onSelect,
}: {
  actions: ActionRecord[]
  runtimeResults: ActionRecord[]
  nextIndex: number
  selectedIndex: number | null
  onSelect: (index: number) => void
}) {
  return (
    <aside className="hidden h-svh w-72 shrink-0 flex-col border-r bg-background xl:flex" aria-label="Action timeline">
      <div className="flex h-14 shrink-0 items-center border-b px-4">
        <h2 className="text-xs font-semibold">Action timeline</h2>
        <span className="ml-2 text-xs tabular-nums text-muted-foreground">{actions.length}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {!actions.length ? (
          <div className="grid h-full place-items-center p-6 text-center">
            <div>
              <CircleDashed className="mx-auto size-5 text-muted-foreground" />
              <p className="mt-2 text-xs font-medium">No actions recorded</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Start the fixture, enable recording, then issue actions from the workspace.
              </p>
            </div>
          </div>
        ) : (
          <ol className="flex flex-col gap-1 p-2">
            {actions.map((action, index) => {
              const selected = selectedIndex === index
              const runtime = runtimeResults.find((result) => result.index === index)
              const failed = Boolean(runtime?.error ?? action.error)
              const completed = Boolean(runtime) || index < nextIndex
              return (
                <li key={index}>
                  <button
                    type="button"
                    className={`flex w-full min-w-0 flex-col rounded-md px-2 py-2 text-left outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring ${
                      selected ? "bg-muted" : ""
                    }`}
                    aria-current={selected ? "step" : undefined}
                    onClick={() => onSelect(index)}
                  >
                    <span className="flex min-w-0 items-center gap-1.5 text-xs font-medium">
                      {failed ? (
                        <AlertCircle className="size-3.5 shrink-0 text-red-600" />
                      ) : completed ? (
                        <CheckCircle2 className="size-3.5 shrink-0 text-emerald-600" />
                      ) : (
                        <MousePointerClick className="size-3.5 shrink-0 text-muted-foreground" />
                      )}
                      <span className="truncate">{actionName(action, index)}</span>
                    </span>
                    <span className="mt-1 flex min-w-0 items-center gap-2 pl-5 text-[11px] text-muted-foreground">
                      <span className="shrink-0 tabular-nums">#{index + 1}</span>
                      <span className="truncate font-mono">{argumentsLabel(action)}</span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </aside>
  )
}
