const REQUIRED = ['chart_of_accounts.csv', 'fx_rates.csv', 'trial_balance.csv']
const OPTIONAL = ['prior_period_tb.csv', 'manual_adjustments.json']

export const INPUT_FILES = [
  { name: 'trial_balance.csv', label: 'Trial balance', required: true },
  { name: 'chart_of_accounts.csv', label: 'Chart of accounts', required: true },
  { name: 'fx_rates.csv', label: 'FX rates', required: true },
  { name: 'prior_period_tb.csv', label: 'Prior-period TB', required: false },
  { name: 'manual_adjustments.json', label: 'Manual adjustments', required: false },
]

export { REQUIRED, OPTIONAL }

async function json(res) {
  const text = await res.text()
  try {
    return JSON.parse(text)
  } catch {
    throw new Error(`API returned non-JSON (${res.status}): ${text.slice(0, 200)}`)
  }
}

export async function health() {
  return json(await fetch('/api/health'))
}

export async function loadSample() {
  const data = await json(await fetch('/api/sample'))
  if (!data.ok) throw new Error(data.error ?? 'could not load the bundled sample')
  return data.files
}

export async function listEntities() {
  try {
    const data = await json(await fetch('/api/entities'))
    return data.entities ?? []
  } catch {
    return []
  }
}

export async function runPipeline(files, entity) {
  const res = await fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ files, entity: entity || null }),
  })
  return json(res)
}

export const money = (v) =>
  Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const pct = (v) => `${(Number(v) * 100).toFixed(2)}%`
