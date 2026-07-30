import { Highlight, type PrismTheme } from "prism-react-renderer"

const gruvboxDark: PrismTheme = {
  plain: {
    color: "#ebdbb2",
    backgroundColor: "#282828",
  },
  styles: [
    {
      types: ["comment", "prolog", "doctype", "cdata"],
      style: { color: "#928374", fontStyle: "italic" },
    },
    {
      types: ["keyword", "atrule", "important"],
      style: { color: "#fb4934" },
    },
    {
      types: ["builtin", "class-name", "type"],
      style: { color: "#fabd2f" },
    },
    {
      types: ["function"],
      style: { color: "#b8bb26" },
    },
    {
      types: ["string", "char", "attr-value", "regex"],
      style: { color: "#b8bb26" },
    },
    {
      types: ["number", "boolean", "constant", "symbol"],
      style: { color: "#d3869b" },
    },
    {
      types: ["operator", "entity", "url"],
      style: { color: "#8ec07c" },
    },
    {
      types: ["variable", "parameter"],
      style: { color: "#83a598" },
    },
    {
      types: ["punctuation"],
      style: { color: "#a89984" },
    },
    {
      types: ["decorator", "annotation"],
      style: { color: "#fe8019" },
    },
  ],
}

export function PythonCode({
  source,
  breakpoints,
  currentLine,
  onToggleBreakpoint,
}: {
  source: string
  breakpoints: Set<number>
  currentLine: number | null
  onToggleBreakpoint: (line: number) => void
}) {
  // Prism exposes one token array per source line, which keeps debugger gutters aligned.
  // Source: https://github.com/FormidableLabs/prism-react-renderer#children-function
  return (
    <Highlight theme={gruvboxDark} code={source} language="python">
      {({ className, style, tokens, getLineProps, getTokenProps }) => (
        <pre
          className={`${className} debug-code`}
          style={style}
          aria-label="Python source code"
        >
          {tokens.map((line, index) => {
            const lineNumber = index + 1
            const breakpoint = breakpoints.has(lineNumber)
            return (
              <span
                key={lineNumber}
                {...getLineProps({
                  line,
                  className: `debug-code-line ${currentLine === lineNumber ? "current" : ""}`,
                })}
                aria-current={currentLine === lineNumber ? "step" : undefined}
              >
                <button
                  type="button"
                  className="debug-breakpoint"
                  aria-label={`${breakpoint ? "Remove" : "Add"} breakpoint on line ${lineNumber}`}
                  onClick={() => onToggleBreakpoint(lineNumber)}
                >
                  {breakpoint && <span className="debug-breakpoint-dot" />}
                </button>
                <span className="debug-line-number">{lineNumber}</span>
                <code className="debug-line-content">
                  {line.map((token, tokenIndex) => (
                    <span key={tokenIndex} {...getTokenProps({ token })} />
                  ))}
                </code>
              </span>
            )
          })}
        </pre>
      )}
    </Highlight>
  )
}
