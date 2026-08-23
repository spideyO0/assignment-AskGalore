import { money } from '../api'

export default function Queues({ result }) {
  const review = result.decisions.filter((d) => d.disposition === 'REVIEW')
  const susp = result.decisions.filter((d) => d.disposition === 'SUSPENSE')

  return (
    <div className="stack">
      <section>
        <h3>Review queue <span className="pill">{review.length}</span></h3>
        <p className="note">
          Scored above the review floor but below <code>auto_min</code>, or blocked
          by a veto. These need a human decision before they post.
        </p>
        {review.length === 0 ? <p className="dim">Nothing awaiting sign-off.</p> : (
          <table className="grid">
            <thead>
              <tr>
                <th>Source</th><th>Account</th><th className="num">Net USD</th>
                <th>Proposed</th><th className="num">Conf</th><th>Runner-up</th>
                <th className="num">Margin</th><th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {review.map((d) => (
                <tr key={`${d.source}:${d.account_code}`}>
                  <td className="dim">{d.source}</td>
                  <td><span className="mono">{d.account_code}</span> {d.account_name}</td>
                  <td className="num">{money(d.usd_net)}</td>
                  <td><span className="mono">{d.mapped_code}</span> {d.mapped_name}</td>
                  <td className="num mono">{d.confidence}</td>
                  <td className="mono dim">{d.runner_up_code} ({d.runner_up_confidence})</td>
                  <td className="num mono">{d.margin}</td>
                  <td className="dim small">
                    {Object.entries(d.features ?? {})
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 2)
                      .map(([k, v]) => `${k} ${Number(v).toFixed(2)}`)
                      .join(' · ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h3>Suspense <span className="pill">{susp.length}</span></h3>
        <p className="note">
          Excluded from applied mappings and <strong>never dropped</strong> — each
          carries its dollar amount and the reason it could not be resolved.
        </p>
        {susp.length === 0 ? <p className="dim">Nothing held in suspense.</p> : (
          <table className="grid">
            <thead>
              <tr><th>Source</th><th>Account</th><th className="num">Net USD</th><th>Why</th></tr>
            </thead>
            <tbody>
              {susp.map((d) => (
                <tr key={`${d.source}:${d.account_code}`}>
                  <td className="dim">{d.source}</td>
                  <td><span className="mono">{d.account_code}</span> {d.account_name}</td>
                  <td className="num">{money(d.usd_net)}</td>
                  <td className="small">{(d.reasons ?? [])[0]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
