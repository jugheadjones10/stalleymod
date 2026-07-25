import {
  FlaskConical,
  Import,
  PanelLeftClose,
  PanelLeftOpen,
  PlaySquare,
  Search,
  Trash2,
} from "lucide-react"
import { useMemo, useState } from "react"
import type { ScenarioSummary } from "../types"

interface Props {
  scenarios: ScenarioSummary[]
  selectedId: string | null
  catalogErrors: number
  onSelect: (id: string) => void
  onImport: () => void
  onDelete: () => void
  onSuite: () => void
}

export function ScenarioSidebar({
  scenarios,
  selectedId,
  catalogErrors,
  onSelect,
  onImport,
  onDelete,
  onSuite,
}: Props) {
  const [collapsed, setCollapsed] = useState(false)
  const [query, setQuery] = useState("")
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return scenarios
    return scenarios.filter((scenario) =>
      `${scenario.name} ${scenario.id} ${scenario.farmName}`.toLowerCase().includes(needle),
    )
  }, [query, scenarios])

  return (
    <aside
      className={`hidden h-svh shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground transition-[width] md:flex ${
        collapsed ? "w-12" : "w-64"
      }`}
    >
      <div
        className={`flex h-14 shrink-0 items-center border-b ${
          collapsed ? "justify-center" : "gap-2 px-4"
        }`}
      >
        {!collapsed && (
          <>
            <span className="grid size-6 place-items-center rounded-md bg-foreground text-background">
              <FlaskConical className="size-3.5" />
            </span>
            <span className="text-sm font-semibold">Stalley Harness</span>
          </>
        )}
        <button
          type="button"
          className={`icon-button ${collapsed ? "" : "ml-auto"}`}
          onClick={() => setCollapsed((value) => !value)}
          aria-label={collapsed ? "Expand scenario sidebar" : "Collapse scenario sidebar"}
        >
          {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </button>
      </div>

      {!collapsed && (
        <>
          <div className="border-b p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
              <input
                className="h-8 w-full rounded-md border bg-background pl-8 pr-2 text-xs outline-none focus:ring-2 focus:ring-ring/50"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter scenarios"
                aria-label="Filter scenarios"
              />
            </div>
          </div>
          <div className="flex items-center px-4 pb-1 pt-3">
            <h2 className="text-xs font-medium text-sidebar-foreground/70">Scenarios</h2>
            <span className="ml-auto text-[11px] tabular-nums text-muted-foreground">
              {scenarios.length}
            </span>
          </div>
          <nav className="min-h-0 flex-1 overflow-y-auto p-2" aria-label="Scenarios">
            <div className="flex flex-col gap-1">
              {visible.map((scenario) => {
                const selected = selectedId === scenario.id
                return (
                  <button
                    key={scenario.id}
                    type="button"
                    className={`group rounded-md px-2 py-2 text-left outline-none transition-colors hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring ${
                      selected ? "bg-sidebar-accent" : ""
                    }`}
                    aria-current={selected ? "page" : undefined}
                    onClick={() => onSelect(scenario.id)}
                  >
                    <span className={`block truncate text-sm ${selected ? "font-semibold" : "font-medium"}`}>
                      {scenario.name}
                    </span>
                    <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <span className="truncate">{scenario.farmName}</span>
                      <span aria-hidden="true">·</span>
                      <span className="shrink-0 tabular-nums">{scenario.actionCount} actions</span>
                    </span>
                  </button>
                )
              })}
              {!visible.length && (
                <p className="px-2 py-3 text-xs text-muted-foreground">
                  {scenarios.length ? "No matching scenarios." : "No scenarios yet."}
                </p>
              )}
            </div>
          </nav>
          {catalogErrors > 0 && (
            <p className="border-t px-4 py-2 text-xs text-red-600">
              {catalogErrors} invalid scenario{catalogErrors === 1 ? "" : "s"}
            </p>
          )}
          <div className="grid gap-1 border-t p-2">
            <button type="button" className="button secondary w-full justify-start" onClick={onSuite}>
              <PlaySquare />
              Regression suite
            </button>
            <button type="button" className="button secondary w-full justify-start" onClick={onImport}>
              <Import />
              Import save fixture
            </button>
            <button type="button" className="button ghost-danger w-full justify-start" onClick={onDelete} disabled={!selectedId}>
              <Trash2 />
              Delete selected
            </button>
          </div>
        </>
      )}
    </aside>
  )
}
