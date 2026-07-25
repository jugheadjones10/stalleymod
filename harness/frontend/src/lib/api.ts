import useSWR, { mutate } from "swr"
import type { Bootstrap, DebugState, RunState, ScenarioDetails, SuiteState } from "../types"

async function readResponse<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(body?.error ?? `${response.status} ${response.statusText}`)
  }
  return body as T
}

const fetcher = <T,>(url: string) =>
  fetch(url).then((response) => readResponse<T>(response))

export function useBootstrap() {
  return useSWR<Bootstrap>("/api/bootstrap", fetcher<Bootstrap>)
}

export function useScenario(scenarioId: string | null) {
  return useSWR<{ scenario: ScenarioDetails }>(
    scenarioId ? `/api/scenarios/${encodeURIComponent(scenarioId)}` : null,
    fetcher<{ scenario: ScenarioDetails }>,
  )
}

export function useRun(initial?: RunState) {
  return useSWR<RunState>("/api/run", fetcher<RunState>, {
    fallbackData: initial,
    refreshInterval: (run) =>
      run && ["preparing", "launching", "connecting", "loading", "ready"].includes(run.status)
        ? 500
        : 2500,
  })
}

export function useSuite(initial?: SuiteState) {
  return useSWR<SuiteState>("/api/suite", fetcher<SuiteState>, {
    fallbackData: initial,
    refreshInterval: (suite) => suite?.status === "running" ? 500 : 2500,
  })
}

export function useDebug(initial?: DebugState) {
  return useSWR<DebugState>("/api/debug", fetcher<DebugState>, {
    fallbackData: initial,
    refreshInterval: (debug) =>
      debug && ["preparing", "launching", "connecting", "loading", "restarting", "running", "paused"].includes(debug.status)
        ? 300
        : 1500,
  })
}

export async function request<T>(
  path: string,
  token: string,
  body: object = {},
  method = "POST",
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Harness-Token": token,
    },
    body: JSON.stringify(body),
  })
  return readResponse<T>(response)
}

export const post = <T,>(path: string, token: string, body: object = {}) =>
  request<T>(path, token, body, "POST")

export const put = <T,>(path: string, token: string, body: object = {}) =>
  request<T>(path, token, body, "PUT")

export async function refreshCatalog() {
  await mutate("/api/bootstrap")
}

export async function refreshScenario(scenarioId: string) {
  await mutate(`/api/scenarios/${encodeURIComponent(scenarioId)}`)
}
