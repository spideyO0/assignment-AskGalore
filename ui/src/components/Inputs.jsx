import { useRef, useState } from 'react'

export default function Inputs({
  files, setFiles, entities, entity, setEntity,
  onSample, onRun, canRun, busy, missing, spec,
}) {
  const [drag, setDrag] = useState(false)
  const inputRef = useRef(null)

  const accept = async (fileList) => {
    const next = { ...files }
    for (const f of fileList) {
      next[f.name] = await f.text()
    }
    setFiles(next)
  }

  const drop = async (e) => {
    e.preventDefault()
    setDrag(false)
    await accept(e.dataTransfer.files)
  }

  const remove = (name) => {
    const next = { ...files }
    delete next[name]
    setFiles(next)
  }

  return (
    <section className="inputs">
      <div
        className={drag ? 'dropzone over' : 'dropzone'}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={drop}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".csv,.json"
          hidden
          onChange={(e) => accept(e.target.files)}
        />
        <strong>Drop input files here</strong>
        <span>or click to browse — .csv and .json, matched by filename</span>
      </div>

      <ul className="filelist">
        {spec.map((s) => {
          const have = s.name in files
          const bytes = have ? new Blob([files[s.name]]).size : 0
          return (
            <li key={s.name} className={have ? 'have' : s.required ? 'need' : 'opt'}>
              <span className="dot" />
              <span className="fname">{s.name}</span>
              <span className="flabel">{s.label}</span>
              <span className="fmeta">
                {have ? `${(bytes / 1024).toFixed(1)} kB` : s.required ? 'required' : 'optional'}
              </span>
              {have && (
                <button className="x" onClick={() => remove(s.name)} title="Remove">
                  ×
                </button>
              )}
            </li>
          )
        })}
      </ul>

      <div className="controls">
        <button className="ghost" onClick={onSample} disabled={busy}>
          Load bundled sample
        </button>
        {entities.length > 0 && (
          <label className="entity">
            Entity policy
            <select value={entity} onChange={(e) => setEntity(e.target.value)}>
              <option value="">base config</option>
              {entities.map((e) => (
                <option key={e} value={e}>{e}</option>
              ))}
            </select>
          </label>
        )}
        <button className="primary" onClick={onRun} disabled={!canRun}>
          {busy ? 'Running…' : 'Run mapping'}
        </button>
        {missing.length > 0 && (
          <span className="hint">missing: {missing.join(', ')}</span>
        )}
      </div>
    </section>
  )
}
