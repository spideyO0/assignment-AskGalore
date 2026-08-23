const TONE = { 0: 'clean', 1: 'disclosed', 2: 'hard' }

export default function StatusBanner({ result }) {
  const tone = TONE[result.exit_code] ?? 'hard'
  return (
    <div className={`banner ${tone}`}>
      <div className="banner-main">
        <span className="code">exit {result.exit_code}</span>
        <strong>{result.status}</strong>
      </div>
      <div className="banner-meta">
        <span>sources: {result.sources.join(' + ')}</span>
        {result.entity && <span>entity: {result.entity}</span>}
        <span>
          auto {count(result, 'AUTO_APPLIED')} · review {count(result, 'REVIEW')} · suspense{' '}
          {count(result, 'SUSPENSE')}
        </span>
      </div>
      {result.exit_code === 1 && (
        <p className="banner-note">
          Exceptions were disclosed, not hidden. Nothing was dropped — every input
          row is accounted for in exactly one decision.
        </p>
      )}
    </div>
  )
}

const count = (r, d) => r.decisions.filter((x) => x.disposition === d).length
