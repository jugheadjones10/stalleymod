import { ImageOff } from "lucide-react"
import { useEffect, useRef } from "react"
import type { Preview } from "../types"

function decodeBase64(value: string) {
  const binary = window.atob(value)
  const bytes = new Uint8ClampedArray(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return bytes
}

export function PreviewCanvas({ preview }: { preview: Preview | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !preview) return
    canvas.width = preview.width
    canvas.height = preview.height
    const context = canvas.getContext("2d")
    if (!context) return
    context.putImageData(
      new ImageData(decodeBase64(preview.pixels), preview.width, preview.height),
      0,
      0,
    )
  }, [preview])

  if (!preview) {
    return (
      <div className="grid h-full place-items-center p-8 text-center">
        <div>
          <ImageOff className="mx-auto size-6 text-muted-foreground" />
          <p className="mt-2 text-xs font-medium">No game preview captured</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Capture a frame when the scenario is ready.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="grid min-h-full place-items-center bg-black p-3">
      <canvas
        ref={canvasRef}
        className="max-h-full max-w-full object-contain [image-rendering:auto]"
        aria-label={`Stardew Valley preview, ${preview.width} by ${preview.height}`}
      />
    </div>
  )
}
