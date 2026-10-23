import { useEffect, useState } from 'react'
import { api, LANGS } from '../api'

export default function Profile({ notify }: any) {
  const [p, setP] = useState<any>(null)
  const [skills, setSkills] = useState('')
  const [langs, setLangs] = useState('')
  const [tl, setTl] = useState('en')
  const [busy, setBusy] = useState(false)

  const apply = (d: any) => {
    setP(d)
    setSkills(d.skills.map((s: any) => s.name).join(', '))
    setLangs(d.languages.map((l: any) => `${l.code}:${l.level || ''}`).join(', '))
  }
  useEffect(() => { api('/profile').then(apply).catch((e) => notify(e.message, true)) }, [])
  if (!p) return <p>Carregando…</p>

  const set = (k: string, v: any) => setP({ ...p, [k]: v })
  const setPref = (k: string, v: any) => setP({ ...p, preferences: { ...p.preferences, [k]: v } })
  const lst = (k: string) => (p.preferences[k] || []).join(', ')
  const setLst = (k: string, v: string) => setPref(k, v.split(',').map((x) => x.trim()).filter(Boolean))
  const setExp = (i: number, k: string, v: any) => set('experiences', p.experiences.map((e: any, j: number) => (j === i ? { ...e, [k]: v } : e)))

  const save = async () => {
    const preferences = p.preferences
    const body = {
      ...p, preferences,
      skills: skills.split(',').map((s) => s.trim()).filter(Boolean).map((name) => ({ name })),
      languages: langs.split(',').map((s) => s.trim()).filter(Boolean).map((s) => { const [code, ...lv] = s.split(':'); return { code: code.trim(), level: lv.join(':').trim() } }),
    }
    try { apply(await api('/profile', { method: 'PUT', json: body })); notify('Perfil salvo') } catch (e: any) { notify(e.message, true) }
  }
  const importFile = async (file: File) => {
    const fd = new FormData(); fd.append('file', file)
    setBusy(true)
    try { const r = await api('/profile/import', { method: 'POST', body: fd }); apply(r.profile); notify(`Importado: ${r.imported.experiences} experiências, ${r.imported.education} formações, ${r.imported.skills} skills. Revise os dados!`) }
    catch (e: any) { notify(e.message, true) } finally { setBusy(false) }
  }
  const translate = async () => {
    setBusy(true)
    try { const r = await api('/profile/translate/' + tl, { method: 'POST' }); notify(`${r.translated_fields} campos traduzidos para ${LANGS[tl]}`); apply(await api('/profile')) }
    catch (e: any) { notify(e.message, true) } finally { setBusy(false) }
  }

  return (
    <>
      <section className="card">
        <h2>Importar</h2>
        <p className="muted">
          <b>PDF</b> do seu currículo ou do LinkedIn (no LinkedIn: perfil → “Mais” → “Salvar como PDF”) ou o <b>ZIP</b> de “Obter uma cópia dos seus dados” (Configurações → Privacidade de dados) — o ZIP é a opção mais fiel.
          Nada é enviado para a internet: a leitura acontece no seu computador. A importação mescla com o que já existe.
        </p>
        <input type="file" accept=".pdf,.zip" disabled={busy} onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
      </section>

      <section className="card">
        <h2>Dados pessoais</h2>
        <div className="form2">
          {(['full_name', 'email', 'phone', 'location', 'headline'] as const).map((k) => (
            <label key={k}>{{ full_name: 'Nome', email: 'E-mail', phone: 'Telefone', location: 'Localização', headline: 'Título profissional' }[k]}
              <input value={p[k] || ''} onChange={(e) => set(k, e.target.value)} /></label>
          ))}
          <label>LinkedIn<input value={p.links?.linkedin || ''} onChange={(e) => set('links', { ...p.links, linkedin: e.target.value })} /></label>
          <label>GitHub<input value={p.links?.github || ''} onChange={(e) => set('links', { ...p.links, github: e.target.value })} /></label>
          <label>Site/portfólio<input value={p.links?.website || ''} onChange={(e) => set('links', { ...p.links, website: e.target.value })} /></label>
        </div>
        <label>Resumo<textarea rows={4} value={p.summary || ''} onChange={(e) => set('summary', e.target.value)} /></label>
        <label>Idiomas que você fala (código:nível, ex.: pt:Nativo, en:Avançado)<input value={langs} onChange={(e) => setLangs(e.target.value)} /></label>
        <label>Tecnologias (separadas por vírgula) — só o que você realmente domina<textarea rows={3} value={skills} onChange={(e) => setSkills(e.target.value)} /></label>
      </section>

      <section className="card">
        <h2>Experiências</h2>
        {p.experiences.map((e: any, i: number) => (
          <div key={i} className="exp">
            <div className="form2">
              <label>Empresa<input value={e.company} onChange={(ev) => setExp(i, 'company', ev.target.value)} /></label>
              <label>Cargo<input value={e.title} onChange={(ev) => setExp(i, 'title', ev.target.value)} /></label>
              <label>Início (AAAA-MM)<input value={e.start || ''} onChange={(ev) => setExp(i, 'start', ev.target.value)} /></label>
              <label>Fim (vazio = atual)<input value={e.end || ''} onChange={(ev) => setExp(i, 'end', ev.target.value || null)} /></label>
            </div>
            <label>Descrição / realizações (uma por linha)<textarea rows={4} value={e.description} onChange={(ev) => setExp(i, 'description', ev.target.value)} /></label>
            <button className="danger" onClick={() => set('experiences', p.experiences.filter((_: any, j: number) => j !== i))}>Remover</button>
          </div>
        ))}
        <button onClick={() => set('experiences', [...p.experiences, { company: '', title: '', start: '', end: null, description: '', technologies: [], i18n: {} }])}>+ Experiência</button>
        <h2>Formação</h2>
        {p.education.map((e: any, i: number) => (
          <div key={i} className="form2">
            <label>Instituição<input value={e.institution} onChange={(ev) => set('education', p.education.map((x: any, j: number) => (j === i ? { ...x, institution: ev.target.value } : x)))} /></label>
            <label>Curso/grau<input value={e.degree} onChange={(ev) => set('education', p.education.map((x: any, j: number) => (j === i ? { ...x, degree: ev.target.value } : x)))} /></label>
          </div>
        ))}
        <button onClick={() => set('education', [...p.education, { institution: '', degree: '', start: '', end: null, i18n: {} }])}>+ Formação</button>
      </section>

      <section className="card">
        <h2>O que você procura</h2>
        <p className="muted">Isso define quais vagas são buscadas e como a nota é calculada. Separe itens por vírgula.</p>
        <label>Buscar por (cada termo vira uma pesquisa)<input value={lst('queries')} onChange={(e) => setLst('queries', e.target.value)} /></label>
        <label>Cargos que combinam com você (usados na nota)<input value={lst('titles')} onChange={(e) => setLst('titles', e.target.value)} /></label>
        <label>A vaga só entra se o título tiver alguma destas palavras<input value={lst('title_keywords')} onChange={(e) => setLst('title_keywords', e.target.value)} /></label>
        <span className="lbl">Foco da busca (% do esforço e da cota diária — deve somar 100)</span>
        <div className="form2">
          {[['bh', '📍 Belo Horizonte e Grande BH'], ['brazil', '🇧🇷 Resto do Brasil'], ['remote', '🌍 Remoto internacional']].map(([k, n]) => (
            <label key={k}>{n}<input type="number" min={0} max={100} value={p.preferences.focus?.[k] ?? 0} onChange={(e) => setPref('focus', { ...p.preferences.focus, [k]: Number(e.target.value) })} /></label>
          ))}
        </div>
        {Object.values(p.preferences.focus || {}).reduce((x: number, y: any) => x + Number(y), 0) !== 100 && <p className="warn small">⚠ A soma do foco não é 100: os valores serão usados como proporção.</p>}
        <div className="form2">
          <div><span className="lbl">Senioridade desejada</span>
            <div className="row">{[['intern', 'Estágio'], ['junior', 'Júnior'], ['mid', 'Pleno'], ['senior', 'Sênior'], ['lead', 'Lead/Staff']].map(([k, n]) => (
              <label key={k} className="inline"><input type="checkbox" checked={(p.preferences.seniority || []).includes(k)} onChange={(e) => setPref('seniority', e.target.checked ? [...(p.preferences.seniority || []), k] : (p.preferences.seniority || []).filter((x: string) => x !== k))} /> {n}</label>
            ))}</div></div>
          <label>Nota mínima para selecionar vaga automaticamente (0–100)<input type="number" min={0} max={100} value={p.preferences.min_score ?? 60} onChange={(e) => setPref('min_score', Number(e.target.value))} /></label>
          <label>Ignorar vagas com mais de (dias)<input type="number" min={1} value={p.preferences.max_age_days ?? 14} onChange={(e) => setPref('max_age_days', Number(e.target.value))} /></label>
        </div>
        <label>Locais aceitos (ex.: brazil, brasil, remote, belo horizonte)<input value={lst('locations')} onChange={(e) => setLst('locations', e.target.value)} /></label>
        <label className="inline"><input type="checkbox" checked={p.preferences.accept_remote_global !== false} onChange={(e) => setPref('accept_remote_global', e.target.checked)} /> Aceitar vagas remotas de qualquer país (quando não exigirem residência/autorização local)</label>
        <label className="inline"><input type="checkbox" checked={!!p.preferences.hard_location} onChange={(e) => setPref('hard_location', e.target.checked)} /> Descartar vagas fora desses locais</label>
        <label>Descartar se aparecer (ex.: php, sap, estágio)<input value={lst('exclude_keywords')} onChange={(e) => setLst('exclude_keywords', e.target.value)} /></label>
        <label>Empresas bloqueadas<input value={lst('blocked_companies')} onChange={(e) => setLst('blocked_companies', e.target.value)} /></label>
        <div><span className="lbl">Fontes de vagas</span>
          <div className="row">{[['linkedin', 'LinkedIn'], ['gupy', 'Gupy'], ['greenhouse', 'Greenhouse'], ['lever', 'Lever'], ['remotive', 'Remotive'], ['remoteok', 'RemoteOK'], ['arbeitnow', 'Arbeitnow'], ['weworkremotely', 'We Work Remotely']].map(([k, n]) => (
            <label key={k} className="inline"><input type="checkbox" checked={(p.preferences.sources || []).includes(k)} onChange={(e) => setPref('sources', e.target.checked ? [...(p.preferences.sources || []), k] : (p.preferences.sources || []).filter((x: string) => x !== k))} /> {n}</label>
          ))}</div></div>
        <details>
          <summary>Avançado</summary>
          <label>Locais da busca no LinkedIn (ex.: Brazil, Remote)<input value={lst('linkedin_locations')} onChange={(e) => setLst('linkedin_locations', e.target.value)} /></label>
          <label>Empresas no Greenhouse (o nome que aparece em boards.greenhouse.io/<b>nome</b>)<input value={lst('greenhouse_boards')} onChange={(e) => setLst('greenhouse_boards', e.target.value)} /></label>
          <label>Empresas no Lever (jobs.lever.co/<b>nome</b>)<input value={lst('lever_companies')} onChange={(e) => setLst('lever_companies', e.target.value)} /></label>
          <label>Idioma em que o seu perfil está escrito (pt, en…)<input value={p.preferences.content_language || 'pt'} onChange={(e) => setPref('content_language', e.target.value)} /></label>
          <label>Pesos da nota (JSON)<textarea rows={5} className="mono" defaultValue={JSON.stringify(p.preferences.weights || {}, null, 2)} onBlur={(e) => { try { setPref('weights', JSON.parse(e.target.value)) } catch { notify('Pesos: JSON inválido', true) } }} /></label>
        </details>
      </section>

      <div className="row sticky"><button className="primary" onClick={save}>Salvar perfil</button></div>

      <section className="card">
        <h2>Traduzir perfil (opcional)</h2>
        <p className="muted">Gera versões do resumo/descrições em outro idioma via API da Anthropic (requer <code>ANTHROPIC_API_KEY</code> no <code>.env</code>). O prompt proíbe inventar fatos; revise o resultado. Sem a chave, os currículos saem no idioma original do perfil com cabeçalhos traduzidos e um aviso.</p>
        <div className="row">
          <select value={tl} onChange={(e) => setTl(e.target.value)}>{Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <button disabled={busy} onClick={translate}>Traduzir</button>
        </div>
      </section>
    </>
  )
}
