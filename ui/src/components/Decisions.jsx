import { useMemo, useState } from 'react'
import { money } from '../api'
import DecisionDetail from './DecisionDetail'

const DISPOSITIONS = ['ALL', 'AUTO_APPLIED', 'REVIEW', 'SUSPENSE']

export default function Decisions({ result }) {
  const [disp, setDisp] = useState('ALL')
  const [src, setSrc] = useState('ALL')
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(null)

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return result.decisions.filter((d) => {
      if (disp !== 'ALL' && d.disposition !== disp) return false
      if (src !== 'ALL' && d.source !== src) return false
      if (!needle) return true
      return (
        d.account_code.toLowerCase().includes(needle) ||
        d.account_name.toLowerCase().includes(needle) ||
        (d.mapped_code ?? '').toLowerCase().includes(needle) ||
        (d.mapped_name ?? '').toLowerCase().includes(needle)
      )
    })
  }, [result.decisions, disp, src, q])

  const sources = [...new Set(result.decisions.map((d) => d.source))]

  return (
    <div className="stack">
      <div className="toolbar">
        <div className="segmented">
          {DISPOSITIONS.map((d) => (
            <button key={d} className={disp === d ? 'on' : ''} onClick={() => setDisp(d)}>
              {d === 'ALL' ? 'All' : d.replace('_', ' ').toLowerCase()}
              <span className="n">
                {d === 'ALL'
                  ? result.decisions.length
                  : result.decisions.filter((x) => x.disposition === d).length}
              </span>
            </button>
          ))}
        </div>
        {sources.length > 1 && (
          <div className="segmented">
            <button className={src === 'ALL' ? 'on' : ''} onClick={() => setSrc('ALL')}>both</button>
            {sources.map((s) => (
              <button key={s} className={src === s ? 'on' : ''} onClick={() => setSrc(s)}>{s}</button>
            ))}
          </div>
        )}
        <input
          className="search"
          placeholder="filter by code or name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <span className="hint">{rows.length} shown</span>
      </div>

      <table className="grid rows">
        <thead>
          <tr>
            <th>Source</th><th>Account</th><th>Name</th>
            <th>Tier</th><th className="num">Confidence</th>
            <th>Applied →</th><th className="num">Net USD</th><th>Disposition</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={`${d.source}:${d.account_code}`} onClick={() => setOpen(d)} className="clickable">
              <td className="dim">{d.source}</td>
              <td className="mono">{d.account_code}</td>
              <td>{d.account_name}</td>
              <td className="mono dim">{d.tier.toLowerCase()}</td>
              <td className="num"><Confidence v={Number(d.confidence)} /></td>
              <td className="mono">
                {d.disposition === 'AUTO_APPLIED'
                  ? d.mapped_code
                  : <span className="dim">— {d.mapped_code ? `(proposed ${d.mapped_code})` : ''}</span>}
              </td>
              <td className="num">{money(d.usd_net)}</td>
              <td><span className={`tag ${d.disposition.toLowerCase()}`}>{d.disposition.replace('_', ' ')}</span></td>
            </tr>
          ))}
        </tbody>
      </table>

      {open && <DecisionDetail d={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

function Confidence({ v }) {
  const tone = v >= 0.9 ? 'ok' : v >= 0.6 ? 'mid' : 'low'
  return (
    <span className={`conf ${tone}`}>
      <span className="cbar"><span style={{ width: `${v * 100}%` }} /></span>
      {v.toFixed(4)}
    </span>
  )
}
