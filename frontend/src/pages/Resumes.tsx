import { useEffect, useState } from 'react'
import { api, LANGS } from '../api'

export default function Resumes({ notify }: any) {
  const [list, setList] = useState<any[]>([])
  const [lang, setLang] = useState('pt')
  const [imp, setImp] = useState(false)
  const [gl, setGl] = useState('en')
  const load = () => api('/resumes').then(setList).catch((e) => notify(e.message, true))
  useEffect(() => { load() }, [])

  const upload = async (file: File) => {
    const fd = new FormData(); fd.append('file', file); fd.append('language', lang); fd.append('import_to_profile', String(imp))
    try { await api('/resumes/upload', { method: 'POST', body: fd }); notify('Currículo base salvo'); load() } catch (e: any) { notify(e.message, true) }
  }
  const gen = async () => { try { await api('/resumes/generate', { json: { language: gl } }); notify('Currículo gerado a partir do perfil'); load() } catch (e: any) { notify(e.message, true) } }
  const del = async (id: number) => { if (confirm('Apagar este currículo?')) { await api('/resumes/' + id, { method: 'DELETE' }); load() } }

  const base = list.filter((r) => r.kind === 'base'), gen_ = list.filter((r) => r.kind === 'generated')
  const Row = ({ r }: any) => (
    <tr>
      <td>{LANGS[r.language] || r.language}</td>
      <td>{r.label}{r.kind === 'base' && !r.is_active && <span className="muted"> (anterior)</span>}
        {r.meta?.warnings?.length > 0 && <div className="warn small">⚠ sem tradução para: {r.meta.warnings.join(', ')} (saiu no idioma original)</div>}
        {r.meta?.unverified_skills?.length > 0 && <div className="warn small">⚠ tecnologias não comprovadas no perfil: {r.meta.unverified_skills.join(', ')}</div>}
      </td>
      <td className="small">{new Date(r.created_at + 'Z').toLocaleString()}</td>
      <td className="row"><a href={`/api/resumes/${r.id}/download`}>PDF</a>{r.has_docx && <a href={`/api/resumes/${r.id}/download?fmt=docx`}>DOCX</a>}<button onClick={() => del(r.id)}>×</button></td>
    </tr>
  )
  return (
    <>
      <section className="card">
        <h2>Currículos base (seus PDFs)</h2>
        <p className="muted">Guarde um PDF por idioma (ex.: <code>resume_pt-BR.pdf</code>, <code>resume_en.pdf</code>). Na candidatura, o sistema usa o currículo gerado para a vaga e, se não houver, o base no idioma da vaga.</p>
        <div className="row">
          <select value={lang} onChange={(e) => setLang(e.target.value)}>{Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <label className="inline"><input type="checkbox" checked={imp} onChange={(e) => setImp(e.target.checked)} /> também importar para o Perfil</label>
          <input type="file" accept=".pdf" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </div>
        <table><tbody>{base.map((r) => <Row key={r.id} r={r} />)}{!base.length && <tr><td className="muted">Nenhum currículo base enviado.</td></tr>}</tbody></table>
      </section>
      <section className="card">
        <h2>Gerar a partir do perfil</h2>
        <div className="row">
          <select value={gl} onChange={(e) => setGl(e.target.value)}>{Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <button className="primary" onClick={gen}>Gerar PDF + DOCX</button>
        </div>
        <p className="muted">Currículos específicos de vaga são gerados na tela <b>Vagas</b>. O gerador só reordena e seleciona fatos do perfil e avisa se algo não tem comprovação.</p>
        <table><tbody>{gen_.map((r) => <Row key={r.id} r={r} />)}{!gen_.length && <tr><td className="muted">Nada gerado ainda.</td></tr>}</tbody></table>
      </section>
    </>
  )
}
