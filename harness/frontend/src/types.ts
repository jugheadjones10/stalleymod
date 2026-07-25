export interface ScenarioSummary {
  id: string
  name: string
  description: string
  farmName: string
  saveFile: string
  actionCount: number
  snapshotCount: number
}

export interface SaveSummary {
  name: string
  farmName: string
  uniqueId: number
}

export interface ActionRecord {
  id?: string
  action?: string
  method?: string
  name?: string
  arguments?: string[]
  args?: unknown
  recordedAt?: string
  durationMs?: number
  result?: unknown
  resultRaw?: string | null
  error?: string | null
  index?: number
  [key: string]: unknown
}

export interface Snapshot {
  name: string
  observation?: unknown
  error?: string
  capturedAt?: string | null
  afterAction?: number | null
}

export interface ScenarioAssertion {
  id: string
  source: "observation" | "action"
  actionIndex?: number
  path: string
  operator: "equals" | "notEquals" | "exists" | "notExists" | "contains"
  expected?: unknown
}

export interface ScenarioDetails extends ScenarioSummary {
  expectedStart: Record<string, unknown>
  surroundingsSize: number
  actions: ActionRecord[]
  snapshots: Snapshot[]
  assertions: ScenarioAssertion[]
  assertionsError?: string | null
}

export interface LogEntry {
  time: string
  level: string
  message: string
}

export interface RunState {
  status: string
  scenarioId: string | null
  runtimeSaveName?: string | null
  port?: number
  attached?: boolean
  pid?: number | null
  observation?: unknown
  observationRaw?: string | null
  error?: string | null
  logs: LogEntry[]
  recording?: boolean
  pendingSnapshot?: {
    pending: boolean
    capturedAt: string
    afterAction: number
  } | null
  actionResults?: ActionRecord[]
  replay?: {
    status: string
    nextIndex: number
    total: number
    results: ActionRecord[]
    error?: string | null
  }
  assertionReport?: AssertionReport | null
}

export interface AssertionResult extends ScenarioAssertion {
  passed: boolean
  actual?: unknown
  missing?: boolean
}

export interface AssertionReport {
  passed: boolean
  total: number
  passedCount: number
  failedCount: number
  results: AssertionResult[]
}

export interface Preview {
  pixels: string
  width: number
  height: number
  format: "rgba8"
}

export interface SuiteResult {
  scenarioId: string
  status: "passed" | "failed" | "error"
  durationMs: number
  report?: AssertionReport | null
  error?: string | null
}

export interface SuiteState {
  status: string
  passed: boolean
  scenarioIds: string[]
  currentScenarioId?: string | null
  completedCount: number
  total: number
  results: SuiteResult[]
  error?: string | null
  startedAt?: string | null
  finishedAt?: string | null
}

export interface DebugTarget {
  runId: string
  eventSequence: number
  function: string
  source: string
  sourceStartLine: number
  mode: "checkpoint" | "task-start" | "source-only"
  checkpoint?: {
    id: string
    observation: Record<string, unknown>
  } | null
  taskStart?: {
    task: string
    saveType: string
    initCommandCount: number
  } | null
}

export interface DebugSession {
  status: string
  currentLine?: number | null
  breakpoints: number[]
  stack: Array<{ function: string; line: number }>
  locals: Record<string, string>
  observation?: Record<string, unknown> | null
  error?: string | null
}

export interface DebugState {
  status: string
  target?: DebugTarget | null
  session?: DebugSession | null
  breakpoints: number[]
  port: number
  error?: string | null
  canRestart: boolean
}

export interface Bootstrap {
  token: string
  catalog: {
    scenarios: ScenarioSummary[]
    errors: Array<{ id: string; error: string }>
  }
  saves: SaveSummary[]
  run: RunState
  suite: SuiteState
  debug: DebugState
  capabilities: {
    recording: boolean
    replay: boolean
    snapshots: boolean
    preview: boolean
    assertions: boolean
    suite: boolean
  }
}
