import { Circle, LoaderCircle } from "lucide-react"

export function StatusBadge({ status }: { status: string }) {
  const busy = ["preparing", "launching", "connecting", "loading", "restarting"].includes(status)
  const tone =
    ["ready", "completed"].includes(status)
      ? "text-emerald-700 bg-emerald-50 ring-emerald-600/20 dark:bg-emerald-950 dark:text-emerald-300"
      : ["error", "failed"].includes(status)
        ? "text-red-700 bg-red-50 ring-red-600/20 dark:bg-red-950 dark:text-red-300"
        : busy
          ? "text-amber-700 bg-amber-50 ring-amber-600/20 dark:bg-amber-950 dark:text-amber-300"
          : "text-muted-foreground bg-muted ring-border"

  return (
    <span
      className={`inline-flex h-5 items-center gap-1 rounded-full px-2 text-[11px] font-medium capitalize ring-1 ring-inset ${tone}`}
    >
      {busy ? <LoaderCircle className="size-3 animate-spin" /> : <Circle className="size-2 fill-current" />}
      {status}
    </span>
  )
}
