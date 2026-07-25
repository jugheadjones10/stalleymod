import { Send } from "lucide-react"
import { FormEvent, useState } from "react"

const COMMON_ACTIONS = [
  "move_step",
  "move",
  "move_relative",
  "interact",
  "use",
  "turn",
  "choose_option",
  "choose_item",
  "exit_menu",
  "open_map",
  "navigate",
]

export function ActionComposer({
  disabled,
  onSend,
}: {
  disabled: boolean
  onSend: (action: string, arguments_: string[]) => Promise<void>
}) {
  const [action, setAction] = useState("move_step")
  const [argumentsText, setArgumentsText] = useState('["up"]')
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    try {
      const parsed: unknown = JSON.parse(argumentsText)
      if (!Array.isArray(parsed) || parsed.some((value) => typeof value !== "string")) {
        throw new Error("Arguments must be a JSON array of strings.")
      }
      await onSend(action.trim(), parsed)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send action")
    }
  }

  return (
    <form className="grid gap-2 border-b bg-muted/20 p-3" onSubmit={submit}>
      <div className="flex items-center gap-2">
        <label className="sr-only" htmlFor="action-name">Mod action</label>
        <input
          id="action-name"
          list="common-actions"
          className="h-8 min-w-0 flex-1 rounded-md border bg-background px-2 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/50"
          value={action}
          disabled={disabled}
          pattern="[A-Za-z_][A-Za-z0-9_]*"
          required
          onChange={(event) => setAction(event.target.value)}
          aria-label="Mod action name"
        />
        <datalist id="common-actions">
          {COMMON_ACTIONS.map((name) => <option key={name} value={name} />)}
        </datalist>
        <button type="submit" className="button primary" disabled={disabled}>
          <Send />
          Send
        </button>
      </div>
      <label className="sr-only" htmlFor="action-arguments">Action arguments</label>
      <input
        id="action-arguments"
        className="h-8 rounded-md border bg-background px-2 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/50"
        value={argumentsText}
        disabled={disabled}
        onChange={(event) => setArgumentsText(event.target.value)}
        aria-label="Action arguments as JSON array"
        spellCheck={false}
      />
      <p className={`text-[11px] ${error ? "text-red-600" : "text-muted-foreground"}`}>
        {error ?? 'Arguments use JSON strings, for example ["up"] or ["0","0","down"].'}
      </p>
    </form>
  )
}
