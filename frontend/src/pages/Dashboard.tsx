import { useEffect, useState } from 'react'
import { api, STATUS_PT } from '../api'

const Bar = ({ pct, label, right, sub, tone, indet }: any) => (
  <div className="pbar">
    <div className="pbar-head"><span>{label}</span><em>{right}</em></div>
    <div className={'progress ' + (tone || '') + (indet ? ' indet' : '')}><i style={indet ? undefined : { width: Math.max(2, Math.min(100, pct || 0)) + '%' }} /></div>
    {sub && <div className="muted small">{sub}</div>}
  </div>
)
const KIND: Record<string, string> = { collect: 'Coleta de vagas', rescore: 'Recalculando notas', prepare_application: 'Preenchendo candidatura', auto_apply: 'Piloto automático', generate_resume: 'Gerando currículo' }
const TIER_ICON: Record<string, string> = { bh: '📍', brazil: '🇧🇷', remote: '🌐' }

function RunProgress({ r }: { r: any }) {
  const d = r.detail || {}, title = KIND[r.kind] || r.kind
  if (r.status === 'pending') return <Bar indet label={`${title} — na fila`} />
  if (d.total) return <Bar pct={(100 * d.done) / d.total} label={`${title}: ${d.label}`} right={`${d.done}/${d.total}${d.new != null ? ` · ${d.new} novas` : ''}`} />
  return <Bar indet label={`${title}…`} />
}

export default function Dashboard({ notify, go }: any) {
  const [s, setS] = useState<any>(null)
  const [runs, setRuns] = useState<any[]>([])
  const active = runs.filter((r) => r.status === 'running' || r.status === 'pending')
  const load = () => {
    api('/stats').then(setS).catch((e) => notify(e.message, true))
    api('/runs').then(setRuns).catch(() => {})
  }
  useEffect(() => { load(); const t = setInterval(load, active.length ? 2000 : 5000); return () => clearInterval(t) }, [active.length])
  const act = async (fn: () => Promise<any>, ok: string) => { try { await fn(); notify(ok); load() } catch (e: any) { notify(e.message, true) } }
  const setCtl = (body: any, ok: string) => act(() => api('/control/settings', { json: body }), ok)
  if (!s) return <p>Carregando painel estatístico…</p>

  const a = s.applications || {}, st = s.setup || {}, ctl = s.control || {}, fn = s.funnel || {}
  const steps = [
    { ok: st.profile_ok, t: 'Importe seu perfil', d: 'Envie o ZIP do LinkedIn e/ou currículo em PDF.', btn: 'Abrir Perfil', run: () => go('profile') },
    { ok: ['pt', 'en'].every((l) => st.resume_langs?.includes(l)), t: 'Currículos base (PT e EN)', d: 'Utilizados de base quando necessário.', btn: 'Abrir Currículos', run: () => go('resumes') },
    { ok: st.collected, t: 'Buscar vagas', d: 'Rodando e atualizando automaticamente.', btn: st.collecting ? 'Coletando…' : 'Coletar agora', disabled: st.collecting, run: () => act(() => api('/runs', { json: { kind: 'collect' } }), 'Coleta iniciada') },
  ]
  const done = steps.filter((x) => x.ok).length
  const funnel = [['Selecionadas', fn.shortlisted], ['Preparadas', fn.prepared], ['Enviadas', fn.submitted], ['Com resposta', fn.answered], ['Entrevistas', fn.interview]]

  return (
    <>
      {done < steps.length && (
        <section className="card guide">
          <h2>Primeiros passos <span className="muted">({done}/{steps.length})</span></h2>
          <Bar pct={(100 * done) / steps.length} label="Configuração inicial" right={`${done} de ${steps.length}`} />
          {steps.map((x, i) => (
            <div key={i} className={'step' + (x.ok ? ' done' : '')}>
              <span className="tick">{x.ok ? '✓' : i + 1}</span>
              <div><b>{x.t}</b><div className="muted small">{x.d}</div></div>
              {!x.ok && <button className="primary" disabled={x.disabled} onClick={x.run}>{x.btn}</button>}
            </div>
          ))}
        </section>
      )}

      {active.length > 0 && <section className="card info"><h2>Em andamento</h2>{active.slice(0, 4).map((r) => <RunProgress key={r.id} r={r} />)}</section>}

      {/* PAINEL ESTATÍSTICO & INTELIGÊNCIA PREDITIVA */}
      {s.statistical_model && (
        <section className="card" style={{ borderLeft: '4px solid var(--accent)' }}>
          <h2>Inteligência Estatística</h2>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', marginTop: '12px' }}>
            <div className="stat"><b>{s.statistical_model.bh_opportunity_count}</b><span>Vagas mapeadas em BH/MG</span></div>
            <div className="stat"><b>{s.statistical_model.bh_market_score}%</b><span>Fit Médio Estatístico em BH</span></div>
            <div className="stat"><b>{s.statistical_model.estimated_bh_success_probability}%</b><span>Probabilidade Preditiva de Entrevista</span></div>
            <div className="stat"><b>{s.statistical_model.average_market_score}%</b><span>Fit Global Geral das Vagas</span></div>
          </div>
          <p className="muted small" style={{ marginTop: '10px' }}>
            <b>Recomendação do Modelo:</b> {s.statistical_model.recommendation}
          </p>
        </section>
      )}

      <div className="grid">
        <Stat n={s.jobs_total} t="Vagas ativas" />
        <Stat n={s.jobs_new_24h} t="Novas (24h)" />
        <Stat n={s.jobs_above_min} t="Acima da nota mínima (40)" />
        <Stat n={s.prepared_today} t="Preparadas hoje" />
        <Stat n={(a.submitted || 0) + (a.interview || 0) + (a.offer || 0)} t="Enviadas com sucesso" />
        <Stat n={a.interview || 0} t="Entrevistas" />
        <Stat n={s.response_rate == null ? '0%' : s.response_rate + '%'} t="Taxa de resposta" />
      </div>

      <section className="card">
        <h2>Piloto Automático & Envio Inteligente por IA</h2>
        <div className="row">
          <label className="inline"><input type="checkbox" checked={!!ctl.auto_apply} onChange={(e) => setCtl({ auto_apply: e.target.checked }, e.target.checked ? 'Piloto automático ligado' : 'Piloto desligado')} /> <b>Piloto Automático</b> (coleta → seleciona → preenche com IA)</label>
          <label className="inline"><input type="checkbox" checked={!!ctl.auto_submit} onChange={(e) => setCtl({ auto_submit: e.target.checked }, e.target.checked ? 'Envio automático ligado' : 'Envio automático desligado')} /> <b>Envio Automático</b> (submete na vaga via Brave)</label>
          <label className="inline">Limite diário <input type="number" min={1} max={200} style={{ width: 70 }} defaultValue={ctl.daily_limit} onBlur={(e) => Number(e.target.value) !== ctl.daily_limit && setCtl({ daily_limit: Number(e.target.value) }, 'Limite atualizado')} /></label>
        </div>
        <p className="muted small">
          O sistema preenche os campos com sua chave da Groq em segundo plano. Vagas com nota ≥ 40 em BH, Brasil ou Remoto são processadas autonomamente.
        </p>
        <div className="row">
          {s.paused
            ? <button onClick={() => act(() => api('/control/resume', { method: 'POST' }), 'Retomado')}>▶ Retomar automação</button>
            : <button onClick={() => act(() => api('/control/pause', { method: 'POST' }), 'Pausado')}>⏸ Pausar automação</button>}
          <button className="danger" onClick={() => act(() => api('/control/stop', { method: 'POST' }), 'Interrompido')}>■ PARAR TUDO</button>
          <span className={'badge ' + (s.paused ? 'needs_review' : 'completed')}>{s.paused ? 'pausado' : 'ativo'}</span>
        </div>
      </section>

      <div className="two">
        <section className="card">
          <h2>Cota de hoje <span className="muted small">({s.prepared_today}/{s.daily_limit})</span></h2>
          {s.quota.map((q: any) => (
            <Bar key={q.tier} tone={q.tier} pct={q.target ? (100 * q.done) / q.target : 0} label={`${TIER_ICON[q.tier]} ${q.label} — foco ${q.percent}%`}
              right={`${q.done}/${q.target}`} sub={`${q.available} vagas elegíveis`} />
          ))}
        </section>
        <section className="card">
          <h2>Funil Geral</h2>
          {funnel.map(([n, v]: any) => <Bar key={n} pct={fn.shortlisted ? (100 * v) / fn.shortlisted : 0} label={n} right={v || 0} />)}
        </section>
      </div>

      <section className="card">
        <h2>Aguardando sua revisão <span className="badge needs_review">{s.waiting_manual}</span></h2>
        <p className="muted">Use o <b>modo assistido</b> para abrir as próximas vagas já preenchidas pela IA, uma a uma.</p>
        <div className="row">
          <button className="primary" disabled={!s.waiting_manual} onClick={() => act(() => api('/applications/assisted', { json: { count: 5 } }), 'Modo assistido iniciado')}>Modo assistido: próximas 5</button>
          <button onClick={() => go('applications')}>Ver todas</button>
          <a href="/api/applications/export.csv"><button>Exportar CSV</button></a>
        </div>
      </section>

      <section className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Histórico de Execuções</h2>
          <button className="primary" onClick={() => act(() => api('/runs', { json: { kind: 'collect' } }), 'Coleta enfileirada')}>Coletar agora</button>
        </div>
        <table>
          <thead><tr><th>#</th><th>Tipo</th><th>Estado</th><th>Когда/Quando</th><th>Resultado</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td><td>{KIND[r.kind] || r.kind}</td><td><span className={'badge ' + r.status}>{r.status}</span></td>
                <td>{new Date(r.created_at + 'Z').toLocaleString()}</td>
                <td className="small">{r.status === 'failed' ? <details><summary>{r.detail?.note || 'ver erro'}</summary><pre>{r.log}</pre></details>
                  : r.detail?.new_total != null ? `${r.detail.new_total} novas · ${r.detail.shortlisted ?? 0} selecionadas`
                  : r.detail?.application_status ? STATUS_PT[r.detail.application_status] : ''}
                </td>
              </tr>
            ))}
            {!runs.length && <tr><td colSpan={5} className="muted">Nenhuma execução recente.</td></tr>}
          </tbody>
        </table>
      </section>
    </>
  )
}

const Stat = ({ n, t }: { n: any; t: string }) => <div className="stat"><b>{n}</b><span>{t}</span></div>