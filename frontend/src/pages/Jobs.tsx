import { useEffect, useState } from 'react'
import { api, LANGS } from '../api'

const TIER: Record<string, string> = { bh: '📍 BH', brazil: '🇧🇷 Brasil', remote: '🌐 Remoto', other: '—' }
const BARS: Record<string, string> = { technical: 'Técnica', experience: 'Experiência', seniority: 'Senioridade', location: 'Local/regime', language: 'Idioma' }

export default function Jobs({ notify, go }: any) {
  const [items, setItems] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [f, setF] = useState({ q: '', source: '', tier: '', min_score: 60, sort: 'score' })
  const [sel, setSel] = useState<any>(null)
  const [lang, setLang] = useState('pt')
  const [adding, setAdding] = useState(false)
  const [m, setM] = useState({ title: '', company: '', url: '', location: '', description: '' })

  const load = () => {
    const p = new URLSearchParams({ q: f.q, source: f.source, tier: f.tier, min_score: String(f.min_score), sort: f.sort })
    api('/jobs?' + p).then((r) => { setItems(r.items); setTotal(r.total) }).catch((e) => notify(e.message, true))
  }
  useEffect(() => { load() }, [f.source, f.tier, f.min_score, f.sort])
  const open = (id: number) => api('/jobs/' + id).then((j) => { setSel(j); if (['pt', 'en', 'es', 'fr', 'de', 'it'].includes(j.language)) setLang(j.language) })
  const run = async (fn: () => Promise<any>, ok: string) => { try { await fn(); notify(ok) } catch (e: any) { notify(e.message, true) } }

  const prepare = (j: any) => run(async () => {
    const a = await api('/applications', { json: { job_id: j.id } })
    await api(`/applications/${a.id}/prepare`, { method: 'POST' })
    open(j.id)
  }, 'Na fila: o navegador abrirá com o formulário preenchido.')

  return (
    <div className="split">
      <div>
        <div className="row filters">
          <input placeholder="Buscar título/empresa" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && load()} />
          <select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}>
            <option value="">Todas as fontes</option>
            {['gupy', 'linkedin', 'greenhouse', 'lever', 'remotive', 'remoteok', 'arbeitnow', 'weworkremotely', 'manual'].map((s) => <option key={s}>{s}</option>)}
          </select>
          <select value={f.tier} onChange={(e) => setF({ ...f, tier: e.target.value })}>
            <option value="">Todas as regiões</option>
            <option value="national">🇧🇷 Nacional (BH + Brasil)</option>
            <option value="bh">📍 Belo Horizonte</option>
            <option value="brazil">🇧🇷 Resto do Brasil</option>
            <option value="remote">🌐 Remoto Internacional</option>
          </select>
          <select value={f.min_score} onChange={(e) => setF({ ...f, min_score: Number(e.target.value) })}>
            {[0, 50, 60, 75].map((n) => <option key={n} value={n}>nota ≥ {n}</option>)}
          </select>
          <select value={f.sort} onChange={(e) => setF({ ...f, sort: e.target.value })}>
            <option value="score">Maior nota</option>
            <option value="recent">Mais recentes</option>
          </select>
          <button onClick={() => setAdding(!adding)}>+ Vaga manual</button>
        </div>
        {adding && (
          <div className="card">
            <p className="muted">Cole qualquer vaga para calcular nota e preencher:</p>
            {(['title', 'company', 'url', 'location'] as const).map((k) => (
              <input key={k} placeholder={{ title: 'Título', company: 'Empresa', url: 'Link', location: 'Local (ex: Belo Horizonte / Remoto)' }[k]} value={m[k]} onChange={(e) => setM({ ...m, [k]: e.target.value })} />
            ))}
            <textarea rows={5} placeholder="Descrição completa da vaga" value={m.description} onChange={(e) => setM({ ...m, description: e.target.value })} />
            <button className="primary" onClick={() => run(async () => {
              const j = await api('/jobs/manual', { json: m })
              setAdding(false); setM({ title: '', company: '', url: '', location: '', description: '' }); load(); setSel(j)
            }, 'Vaga adicionada')}>Adicionar</button>
          </div>
        )}
        <p className="muted">{total} vagas encontradas</p>
        <table className="clickable">
          <thead><tr><th>Nota</th><th>Vaga</th><th>Região</th><th>Fonte</th></tr></thead>
          <tbody>
            {items.map((j) => (
              <tr key={j.id} className={sel?.id === j.id ? 'sel' : ''} onClick={() => open(j.id)}>
                <td><span className={'score ' + (j.score >= 75 ? 'hi' : j.score >= 55 ? 'mid' : 'lo')}>{j.score ?? '—'}</span></td>
                <td><b>{j.title}</b><div className="muted small">{j.company}{j.seniority ? ' · ' + j.seniority : ''}</div></td>
                <td className="small"><b>{TIER[j.tier]}</b><div className="muted">{j.location}</div></td>
                <td className="small">{j.source}{j.auto_lane && <div title="Pode ser enviada automaticamente">⚡ auto</div>}</td>
              </tr>
            ))}
            {!items.length && <tr><td colSpan={4} className="muted">Nenhuma vaga nesta categoria.</td></tr>}
          </tbody>
        </table>
      </div>
      {sel && (
        <aside className="card detail">
          <h2>{sel.title}</h2>
          <p className="muted">{sel.company} · {sel.location} · {sel.language.toUpperCase()}</p>
          <div className="row">
            <a href={sel.url} target="_blank" rel="noreferrer"><button>Abrir vaga ↗</button></a>
            <button onClick={() => run(async () => { await api(`/jobs/${sel.id}/dismiss`, { method: 'POST' }); setSel(null); load() }, 'Vaga dispensada')}>Dispensar</button>
          </div>
          <h3>Nota: {sel.score}{sel.eliminated && ' — ELIMINADA'}</h3>
          {Object.entries(sel.breakdown || {}).map(([k, v]: any) => (
            <div key={k} className="bar"><span>{BARS[k]}</span><div><i style={{ width: v + '%' }} /></div><em>{v}</em></div>
          ))}
          <p className="small">{sel.explanation}</p>
          <div className="chips">
            {sel.matched?.map((x: string) => <span key={x} className="chip ok">✓ {x}</span>)}
            {sel.gaps?.map((x: string) => <span key={x} className="chip gap">✗ {x}</span>)}
          </div>
          <h3>Ações</h3>
          <div className="row">
            <select value={lang} onChange={(e) => setLang(e.target.value)}>
              {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <button onClick={() => run(() => api('/resumes/generate', { json: { language: lang, job_id: sel.id } }), 'Currículo gerado!')}>Gerar currículo sob medida</button>
          </div>
          <div className="row">
            <button className="primary" onClick={() => prepare(sel)}>Preparar Candidatura</button>
            {sel.application_id && <button onClick={() => go('applications')}>Ver em Candidaturas</button>}
          </div>
          <h3>Descrição da Vaga</h3>
          <pre className="desc">{sel.description || '(sem descrição)'}</pre>
        </aside>
      )}
    </div>
  )
}