import { useState } from 'react'

export default function Artifacts({ result }) {
  const names = Object.keys(result.artifacts).sort()
  const [sel, setSel] = useState(names[0])
  const content = result.artifacts[sel] ?? ''

  const download = (name) => {
    const blob = new Blob([result.artifacts[name]], { type: 'text/plain' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = name
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="stack">
      <p className="note">
        Exactly the files <code>coa-mapper run</code> writes to <code>output/</code> —
        byte-identical, same pipeline.
      </p>
      <div className="toolbar">
        <div className="segmented wrap">
          {names.map((n) => (
            <button key={n} className={sel === n ? 'on' : ''} onClick={() => setSel(n)}>{n}</button>
          ))}
        </div>
        <button className="ghost" onClick={() => download(sel)}>Download {sel}</button>
      </div>
      <pre className="artifact">{content}</pre>
    </div>
  )
}
