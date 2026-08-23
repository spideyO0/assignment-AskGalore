import { money } from '../api'

export default function Summary({ result }) {
  const { summary, config } = result
  const sources = Object.entries(summary.decisions ?? {})

  return (
    <div className="stack">
      <div className="cards">
        {sources.map(([src, blk]) => {
          const total = Object.values(blk.usd_abs_totals).reduce((a, b) => a + Number(b), 0)
          return (
            <div className="card" key={src}>
              <h3>{src} period</h3>
              <div className="bigrow">
                <div><em>{blk.counts.AUTO_APPLIED}</em><span>auto-applied</span></div>
                <div className={blk.counts.REVIEW ? 'warn' : ''}>
                  <em>{blk.counts.REVIEW}</em><span>review</span>
                </div>
                <div className={blk.counts.SUSPENSE ? 'warn' : ''}>
                  <em>{blk.counts.SUSPENSE}</em><span>suspense</span>
                </div>
              </div>
              <table className="mini">
                <tbody>
                  <tr><td>input rows</td><td className="num">{blk.input_rows}</td></tr>
                  {Object.entries(blk.usd_abs_totals).map(([k, v]) => (
                    <tr key={k}>
                      <td>{k.toLowerCase().replace('_', ' ')}</td>
                      <td className="num">{money(v)}</td>
                    </tr>
                  ))}
                  <tr className="total"><td>total |USD|</td><td className="num">{money(total)}</td></tr>
                </tbody>
              </table>
            </div>
          )
        })}
      </div>

      <section>
        <h3>Inputs consumed</h3>
        <p className="note">
          Hashing is what makes the trail reproducible rather than merely verbose:
          this report provably describes <em>these</em> files.
        </p>
        <table className="grid">
          <thead><tr><th>File</th><th className="num">Rows</th><th>SHA-256</th></tr></thead>
          <tbody>
            {Object.entries(summary.inputs ?? {}).map(([name, meta]) => (
              <tr key={name}>
                <td className="mono">{name}</td>
                <td className="num">{meta.rows}</td>
                <td className="mono dim">{meta.sha256.slice(0, 32)}…</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h3>Policy in force</h3>
        <p className="note">
          Echoed with every run, so an artifact always names the thresholds that
          produced it.
        </p>
        <div className="kv">
          {Object.entries(config).filter(([k]) => k !== 'weights').map(([k, v]) => (
            <div key={k}><span>{k}</span><code>{JSON.stringify(v)}</code></div>
          ))}
        </div>
        <h4>Feature weights</h4>
        <div className="weights">
          {Object.entries(config.weights).map(([k, v]) => (
            <div key={k} className="wrow">
              <span className="wname">{k}</span>
              <div className="wbar"><div style={{ width: `${v * 100}%` }} /></div>
              <span className="num">{v}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
