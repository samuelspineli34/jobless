export async function api<T = any>(path: string, opts: RequestInit & { json?: any } = {}): Promise<T> {
  const { json, ...rest } = opts
  const init: RequestInit = { ...rest }
  if (json !== undefined) {
    init.method = init.method || 'POST'
    init.headers = { 'Content-Type': 'application/json', ...(init.headers || {}) }
    init.body = JSON.stringify(json)
  }
  const r = await fetch('/api' + path, init)
  if (!r.ok) {
    let msg = r.statusText
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* ignore */ }
    throw new Error(msg)
  }
  return r.json()
}

export const LANGS: Record<string, string> = { pt: 'Português', en: 'English', es: 'Español', fr: 'Français', de: 'Deutsch', it: 'Italiano' }
export const STATUS_PT: Record<string, string> = {
  shortlisted: 'Selecionada', queued: 'Na fila', preparing: 'Preparando', prepared: 'Preparada', needs_review: 'Precisa de revisão',
  submitting: 'Enviando', submitted: 'Enviada', failed: 'Falhou', interview: 'Entrevista', rejected: 'Recusada', offer: 'Oferta', withdrawn: 'Desistência',
}
