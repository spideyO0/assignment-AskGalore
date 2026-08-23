import { useCallback, useEffect, useMemo, useState } from 'react'
import { INPUT_FILES, REQUIRED, listEntities, loadSample, runPipeline } from './api'
import Inputs from './components/Inputs'
import StatusBanner from './components/StatusBanner'
import Summary from './components/Summary'
import Decisions from './components/Decisions'
import Queues from './components/Queues'
import Findings from './components/Findings'
import Checks from './components/Checks'
import Artifacts from './components/Artifacts'

const TABS = [
  { id: 'summary', label: 'Summary' },
  { id: 'decisions', label: 'Decisions' },
  { id: 'queues', label: 'Review & suspense' },
  { id: 'findings', label: 'Findings' },
  { id: 'checks', label: 'Verification' },
  { id: 'artifacts', label: 'Artifacts' },
]

export default function App() {
  const [files, setFiles] = useState({})
  const [entities, setEntities] = useState([])
  const [entity, setEntity] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('summary')

  useEffect(() => {
    listEntities().then(setEntities)
  }, [])

  const missing = useMemo(() => REQUIRED.filter((n) => !(n in files)), [files])
  const canRun = missing.length === 0 && !busy

  const onSample = useCallback(async () => {
    setError(null)
    try {
      setFiles(await loadSample())
    } catch (e) {
      setError(e.message)
    }
  }, [])

  const onRun = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await runPipeline(files, entity)
      setResult(r)
      if (!r.ok && r.error) setError(r.error)
      setTab('summary')
    } catch (e) {
      setError(e.message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }, [files, entity])

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>COA Mapper</h1>
          <p className="sub">
            Trial balance → chart of accounts, with confidence scoring and
            human-in-the-loop escalation
          </p>
        </div>
        <a
          className="ghost"
          href="https://github.com"
          onClick={(e) => e.preventDefault()}
          title="Same pipeline as `coa-mapper run` — byte-identical artifacts"
        >
          CLI parity
        </a>
      </header>

      <Inputs
        files={files}
        setFiles={setFiles}
        entities={entities}
        entity={entity}
        setEntity={setEntity}
        onSample={onSample}
        onRun={onRun}
        canRun={canRun}
        busy={busy}
        missing={missing}
        spec={INPUT_FILES}
      />

      {error && (
        <div className="alert error">
          <strong>Run failed.</strong> {error}
        </div>
      )}

      {result && result.ok && (
        <>
          <StatusBanner result={result} />
          <nav className="tabs">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={tab === t.id ? 'tab active' : 'tab'}
                onClick={() => setTab(t.id)}
              >
                {t.label}
                {t.id === 'findings' && result.findings.length > 0 && (
                  <span className="pill">{result.findings.length}</span>
                )}
                {t.id === 'queues' &&
                  result.decisions.filter((d) => d.disposition !== 'AUTO_APPLIED').length > 0 && (
                    <span className="pill">
                      {result.decisions.filter((d) => d.disposition !== 'AUTO_APPLIED').length}
                    </span>
                  )}
              </button>
            ))}
          </nav>
          <main className="panel">
            {tab === 'summary' && <Summary result={result} />}
            {tab === 'decisions' && <Decisions result={result} />}
            {tab === 'queues' && <Queues result={result} />}
            {tab === 'findings' && <Findings result={result} />}
            {tab === 'checks' && <Checks result={result} />}
            {tab === 'artifacts' && <Artifacts result={result} />}
          </main>
        </>
      )}

      {!result && !error && (
        <div className="empty">
          <p>
            Load the bundled sample or drop your own files, then run. Nothing is
            uploaded anywhere — the API runs locally and holds no state between
            requests.
          </p>
        </div>
      )}
    </div>
  )
}
