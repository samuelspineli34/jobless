import { useState } from 'react'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import Profile from './pages/Profile'
import Resumes from './pages/Resumes'
import Applications from './pages/Applications'

const TABS = [
  ['dashboard', 'Painel'], ['jobs', 'Vagas'], ['applications', 'Candidaturas'], ['resumes', 'Currículos'], ['profile', 'Perfil'],
] as const

export default function App() {
  const [tab, setTab] = useState<string>('dashboard')
  const [toast, setToast] = useState<{ msg: string; err?: boolean } | null>(null)
  const notify = (msg: string, err = false) => { setToast({ msg, err }); setTimeout(() => setToast(null), 5000) }
  const props = { notify, go: setTab }
  return (
    <div className="app">
      <header>
        <h1>Job Assistant</h1>
        <nav>{TABS.map(([k, label]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{label}</button>)}</nav>
      </header>
      <main>
        {tab === 'dashboard' && <Dashboard {...props} />}
        {tab === 'jobs' && <Jobs {...props} />}
        {tab === 'applications' && <Applications {...props} />}
        {tab === 'resumes' && <Resumes {...props} />}
        {tab === 'profile' && <Profile {...props} />}
      </main>
      {toast && <div className={'toast' + (toast.err ? ' err' : '')} onClick={() => setToast(null)}>{toast.msg}</div>}
    </div>
  )
}
