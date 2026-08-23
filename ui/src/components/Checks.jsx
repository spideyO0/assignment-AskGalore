export default function Checks({ result }) {
  const failed = result.checks.filter((c) => !c.passed)
  return (
    <div className="stack">
      <p className="note">
        The verifier reloads the raw inputs from disk and recomputes, then compares
        against what the pipeline claimed. It does not re-read the pipeline's own
        conclusions — an agent that checks its own arithmetic with the same
        reasoning reproduces its own blind spots.
      </p>
      <div className={failed.length ? 'alert error' : 'alert ok'}>
        {failed.length
          ? `${failed.length} of ${result.checks.length} checks failed`
          : `All ${result.checks.length} checks passed`}
      </div>
      <table className="grid">
        <thead><tr><th /><th>Check</th><th>Detail</th></tr></thead>
        <tbody>
          {result.checks.map((c) => (
            <tr key={c.name} className={c.passed ? '' : 'rowfail'}>
              <td>{c.passed ? <span className="tick">✓</span> : <span className="cross">✕</span>}</td>
              <td className="mono">{c.name}</td>
              <td className="small dim">{c.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
