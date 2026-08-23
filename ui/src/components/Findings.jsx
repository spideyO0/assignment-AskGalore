const ORDER = ['ERROR', 'WARN', 'INFO']

export default function Findings({ result }) {
  return (
    <div className="stack">
      <p className="note">
        Every defect the run detected in the source data, with severity. ERROR
        forces exit 2; WARN and INFO are disclosed and the run continues.
      </p>
      {ORDER.map((sev) => {
        const items = result.findings.filter((f) => f.severity === sev)
        if (!items.length) return null
        return (
          <section key={sev}>
            <h3>
              <span className={`tag sev-${sev.toLowerCase()}`}>{sev}</span>
              <span className="pill">{items.length}</span>
            </h3>
            <ul className="findings">
              {items.map((f, i) => (
                <li key={i}>
                  <code>{f.code}</code>
                  <p>{f.message}</p>
                  {f.refs.length > 0 && (
                    <div className="chips">
                      {f.refs.map((r) => <span key={r} className="chip mono small">{r}</span>)}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )
      })}
      {result.findings.length === 0 && <p className="dim">No findings — the inputs are clean.</p>}
    </div>
  )
}
