import { money } from '../api'

/** The audit view: why this account got this disposition, from the record itself. */
export default function DecisionDetail({ d, onClose }) {
  const feats = Object.entries(d.features ?? {})
  const weights = d.weights_used ?? {}
  const den = feats.reduce((a, [k]) => a + Number(weights[k] ?? 0), 0)

  return (
    <div className="drawer-scrim" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <span className="mono big">{d.account_code}</span>
            <h3>{d.account_name}</h3>
            <span className="dim">{d.source} period</span>
          </div>
          <button className="x" onClick={onClose}>×</button>
        </header>

        <div className="drow">
          <span className={`tag ${d.disposition.toLowerCase()}`}>{d.disposition.replace('_', ' ')}</span>
          <span className="mono dim">{d.tier.toLowerCase()}</span>
          <span className="mono">conf {d.confidence}</span>
          <span className="mono">net {money(d.usd_net)}</span>
        </div>

        {d.mapped_code && (
          <section>
            <h4>{d.disposition === 'AUTO_APPLIED' ? 'Applied mapping' : 'Proposed mapping (not applied)'}</h4>
            <p className="mono">{d.mapped_code} — {d.mapped_name}</p>
            {d.runner_up_code && (
              <p className="dim">
                runner-up {d.runner_up_code} at {d.runner_up_confidence} · margin {d.margin}
              </p>
            )}
          </section>
        )}

        {feats.length > 0 && (
          <section>
            <h4>Feature vector</h4>
            <p className="note">
              The composite is the weighted mean of exactly these values. Weights
              renormalize over whichever features had evidence.
            </p>
            <table className="mini wide">
              <thead><tr><th>Feature</th><th className="num">Value</th><th className="num">Weight</th><th /></tr></thead>
              <tbody>
                {feats.map(([k, v]) => (
                  <tr key={k}>
                    <td className="mono">{k}</td>
                    <td className="num">{Number(v).toFixed(4)}</td>
                    <td className="num dim">{weights[k] ?? '—'}</td>
                    <td className="barcell">
                      <span className="fbar"><span style={{ width: `${Number(v) * 100}%` }} /></span>
                    </td>
                  </tr>
                ))}
                <tr className="total">
                  <td>composite</td>
                  <td className="num">{d.confidence}</td>
                  <td className="num dim">Σw {den.toFixed(2)}</td>
                  <td />
                </tr>
              </tbody>
            </table>
          </section>
        )}

        {(d.flags ?? []).length > 0 && (
          <section>
            <h4>Flags</h4>
            <div className="chips">{d.flags.map((f) => <span key={f} className="chip warn">{f}</span>)}</div>
          </section>
        )}

        <section>
          <h4>Reasons</h4>
          <ul className="reasons">{(d.reasons ?? []).map((r, i) => <li key={i}>{r}</li>)}</ul>
        </section>

        <section>
          <h4>Lineage</h4>
          <p className="note">Every source row this balance came from.</p>
          <div className="chips">{(d.row_ids ?? []).map((r) => <span key={r} className="chip mono">{r}</span>)}</div>
          {(d.rate_notes ?? []).length > 0 && (
            <>
              <h4>FX applied</h4>
              <div className="chips">
                {d.rate_notes.map((r) => (
                  <span key={r} className={`chip mono ${r.includes('fallback') ? 'warn' : ''}`}>{r}</span>
                ))}
              </div>
            </>
          )}
        </section>
      </aside>
    </div>
  )
}
