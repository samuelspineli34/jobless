import { useEffect, useState } from 'react'
import { api, STATUS_PT } from '../api'

export default function Applications({ notify }: any) {
  const [apps, setApps] = useState<any[]>([])
  const [ans, setAns] = useState<any[]>([])

  const load = () => {
    api('/applications').then(setApps).catch((e) => notify(e.message, true))
    api('/applications/answers/all').then(setAns).catch(() => {})
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 7000)
    return () => clearInterval(t)
  }, [])

  const patch = async (id: number, body: any) => {
    try {
      await api('/applications/' + id, { method: 'PATCH', json: body })
      load()
    } catch (e: any) {
      notify(e.message, true)
    }
  }

  const prepare = async (id: number) => {
    try {
      await api(`/applications/${id}/prepare`, { method: 'POST' })
      notify('Na fila: o navegador abrirá preenchido para sua revisão')
      load()
    } catch (e: any) {
      notify(e.message, true)
    }
  }

  const saveAns = async (a: any) => {
    try {
      await api('/applications/answers', { json: { pattern: a.pattern, answer: a.answer, approved: true } })
      notify('Resposta aprovada e salva!')
      load()
    } catch (e: any) {
      notify(e.message, true)
    }
  }

  return (
    <>
      <section className="card">
        <h2>Candidaturas em Andamento</h2>
        <p className="muted">
          Revise as candidaturas. Vagas acima de 60 pontos são pré-selecionadas. Se o formulário tiver perguntas novas,
          a IA sugere a resposta abaixo no <b>Banco de Respostas</b> para você aprovar ou editar.
        </p>
        <div className="row">
          <button className="primary" onClick={async () => {
            try {
              const r = await api('/applications/assisted', { json: { count: 5 } })
              notify(`${r.queued} na fila — o navegador vai abrir`)
              load()
            } catch (e: any) {
              notify(e.message, true)
            }
          }}>
            Modo assistido: próximas 5 (≥ 60 pts)
          </button>
          <a href="/api/applications/export.csv"><button>Exportar CSV</button></a>
        </div>
        <table>
          <thead><tr><th>Nota</th><th>Vaga</th><th>Região</th><th>Status</th><th>Notas</th><th>Ação</th></tr></thead>
          <tbody>
            {apps.map((a) => (
              <tr key={a.id}>
                <td><b>{a.score ?? '—'}</b></td>
                <td>
                  <a href={a.url} target="_blank" rel="noreferrer"><b>{a.title}</b></a>
                  <div className="muted small">{a.company} · {a.source}</div>
                  {a.meta?.captcha && <div className="warn small">⚠️ CAPTCHA na tela (resolva no navegador)</div>}
                  {a.meta?.questions_generated && Object.keys(a.meta.questions_generated).length > 0 && (
                    <div className="small muted" style={{ marginTop: 4 }}>
                      🤖 {Object.keys(a.meta.questions_generated).length} respostas geradas por IA (veja no banco abaixo)
                    </div>
                  )}
                </td>
                <td className="small">
                  {{ bh: '📍 BH', brazil: '🇧🇷 Brasil', remote: '🌐 Remoto', other: '—' }[a.tier as string]}
                  <div className="muted">{a.lane === 'auto' ? '⚡ automática' : '✋ manual'}</div>
                </td>
                <td>
                  <select value={a.status} onChange={(e) => patch(a.id, { status: e.target.value })}>
                    {Object.entries(STATUS_PT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </td>
                <td>
                  <textarea rows={2} defaultValue={a.notes} onBlur={(e) => e.target.value !== a.notes && patch(a.id, { notes: e.target.value })} />
                </td>
                <td>
                  {!['submitted', 'submitting', 'interview', 'offer', 'rejected'].includes(a.status) && (
                    <button className="primary" onClick={() => prepare(a.id)}>Preparar</button>
                  )}
                </td>
              </tr>
            ))}
            {!apps.length && <tr><td colSpan={6} className="muted">Nenhuma candidatura registrada.</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>Banco de Respostas (Treinamento & IA)</h2>
        <p className="muted">
          Cada pergunta tem seu campo individual. Respostas geradas por IA ou trazidas de formulários ficam marcadas como <b>Pendente</b>.
          Ao clicar em <b>Aprovar</b>, o sistema memoriza para usar automaticamente em todas as próximas vagas.
        </p>
        <table>
          <thead><tr><th style={{ width: '35%' }}>Pergunta da Vaga</th><th>Sua Resposta (humana ou gerada por IA)</th><th style={{ width: '140px' }}>Ações</th></tr></thead>
          <tbody>
            {ans.map((a, i) => (
              <tr key={a.id}>
                <td className="small">
                  <b>{a.pattern}</b>
                  {!a.approved && <span className="chip gap" style={{ marginLeft: 6 }}>Pendente</span>}
                </td>
                <td>
                  <textarea
                    rows={2}
                    value={a.answer}
                    placeholder="Digite a resposta ou edite a sugestão da IA..."
                    onChange={(e) => setAns(ans.map((x, j) => (j === i ? { ...x, answer: e.target.value } : x)))}
                  />
                </td>
                <td className="row">
                  <button className="primary" onClick={() => saveAns(a)}>Aprovar</button>
                  <button onClick={async () => { await api('/applications/answers/' + a.id, { method: 'DELETE' }); load() }}>×</button>
                </td>
              </tr>
            ))}
            {!ans.length && <tr><td colSpan={3} className="muted">Nenhuma pergunta pendente no banco.</td></tr>}
          </tbody>
        </table>
      </section>
    </>
  )
}