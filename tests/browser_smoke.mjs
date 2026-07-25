import { writeFile } from "node:fs/promises"

const debugPort = Number(process.argv[2] ?? 9222)
const pageUrl = process.argv[3] ?? "http://127.0.0.1:8765"
const screenshotPath = process.argv[4] ?? "/tmp/stalleymod-harness.png"
const viewportWidth = Number(process.argv[5] ?? 1440)
const viewportHeight = Number(process.argv[6] ?? 900)
const targets = await fetch(`http://127.0.0.1:${debugPort}/json`).then((response) => response.json())
const target = targets.find((item) => item.type === "page")
if (!target) throw new Error("Chrome has no debuggable page target")

const socket = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true })
  socket.addEventListener("error", reject, { once: true })
})

let nextId = 1
const pending = new Map()
const consoleProblems = []
const networkFailures = []
const events = new Map()

socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data)
  if (message.id) {
    const callback = pending.get(message.id)
    pending.delete(message.id)
    if (message.error) callback?.reject(new Error(message.error.message))
    else callback?.resolve(message.result)
    return
  }
  if (message.method === "Runtime.exceptionThrown") {
    consoleProblems.push(message.params.exceptionDetails.text)
  }
  if (message.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(message.params.type)) {
    consoleProblems.push(`${message.params.type}: ${message.params.args.map((item) => item.value ?? item.description).join(" ")}`)
  }
  if (message.method === "Network.loadingFailed" && !message.params.canceled) {
    networkFailures.push(`${message.params.errorText}: ${message.params.requestId}`)
  }
  for (const resolve of events.get(message.method) ?? []) resolve(message.params)
  events.delete(message.method)
})

function send(method, params = {}) {
  const id = nextId
  nextId += 1
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    socket.send(JSON.stringify({ id, method, params }))
  })
}

function nextEvent(method) {
  return new Promise((resolve) => {
    events.set(method, [...(events.get(method) ?? []), resolve])
  })
}

await Promise.all([
  send("Page.enable"),
  send("Runtime.enable"),
  send("Network.enable"),
  send("Accessibility.enable"),
])
await send("Emulation.setDeviceMetricsOverride", {
  width: viewportWidth,
  height: viewportHeight,
  deviceScaleFactor: 1,
  mobile: false,
})
const loaded = nextEvent("Page.loadEventFired")
await send("Page.navigate", { url: pageUrl })
await loaded
await new Promise((resolve) => setTimeout(resolve, 4000))

const page = await send("Runtime.evaluate", {
  expression: `({
    title: document.title,
    h1: document.querySelector("h1")?.textContent,
    text: document.body.innerText,
    viewportWidth: innerWidth,
    scrollWidth: document.documentElement.scrollWidth
  })`,
  returnByValue: true,
})
const accessibility = await send("Accessibility.getFullAXTree")
const screenshot = await send("Page.captureScreenshot", { format: "png" })
await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"))
socket.close()

const roles = accessibility.nodes
  .filter((node) => ["heading", "button", "textbox", "navigation", "main"].includes(node.role?.value))
  .slice(0, 80)
  .map((node) => ({ role: node.role?.value, name: node.name?.value }))

const result = {
  page: page.result.value,
  consoleProblems,
  networkFailures,
  accessibility: roles,
  screenshotPath,
}
console.log(JSON.stringify(result, null, 2))
if (consoleProblems.length || networkFailures.length || page.result.value.scrollWidth > page.result.value.viewportWidth) {
  process.exitCode = 1
}
