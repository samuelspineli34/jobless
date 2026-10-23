# Jobless

Assistente **local** de busca e candidatura a vagas: importa seu currículo/LinkedIn, coleta vagas de várias fontes, dá uma **nota explicável** de compatibilidade, gera currículos sob medida em **vários idiomas** (PDF + DOCX) e **prepara** as candidaturas no navegador com Playwright — com você no controle de cada envio.

Tudo roda no seu computador. Seus dados ficam em `data/` (SQLite por padrão, PostgreSQL opcional) e nunca vão para o git.

```
Perfil (PDF / LinkedIn ZIP)  →  Coleta de vagas  →  Nota + requisitos  →  Currículo PT/EN/ES/FR/DE/IT
        →  Candidatura preparada no navegador  →  você revisa e envia  →  Dashboard / histórico
```

## Recursos

| Área | O que faz |
|---|---|
| **Perfil** | Importa **PDF de currículo**, **PDF do LinkedIn** ("Salvar como PDF") ou o **ZIP de dados do LinkedIn**. Fonte única editável: contato, experiências, formação, tecnologias, idiomas, preferências. |
| **Currículos** | Guarda seus PDFs base por idioma (`resume_pt-BR.pdf`, `resume_en.pdf`…), com histórico. Gera currículos **PT, EN, ES, FR, DE, IT** (PDF + DOCX) a partir do perfil, por vaga ou genéricos. |
| **Sem inventar** | O gerador só **seleciona e reordena** fatos do perfil. Se aparecer tecnologia que o perfil não comprova, o currículo recebe um aviso. Conteúdo sem tradução sai no idioma original, também com aviso. |
| **Tradução (opcional)** | Com `ANTHROPIC_API_KEY`, traduz resumo e descrições para outros idiomas, com prompt que proíbe acrescentar fatos. |
| **Coleta** | LinkedIn (busca pública, sem login), Gupy, Greenhouse, Lever, Remotive, RemoteOK, Arbeitnow, We Work Remotely + **vaga manual** (cole qualquer anúncio de qualquer site). |
| **Compatibilidade** | Regras determinísticas: técnica 40%, experiência 25%, senioridade 15%, local/regime 10%, idioma 10% (pesos editáveis) + **eliminatórios** (palavras, empresas, local). Cada nota guarda requisitos atendidos, lacunas e justificativa. |
| **Foco regional** | Cota **85% Belo Horizonte / 5% resto do Brasil / 10% remoto** (editável em Perfil). Vale para a busca (mais páginas e filtro de cidade para BH), para a nota e para a cota diária; a sobra de uma faixa passa para a seguinte. |
| **Piloto automático** | Depois de cada coleta: seleciona, gera currículo sob medida e **envia sozinho** as vagas de Greenhouse/Lever que cumprirem todas as regras de segurança. Ligado por padrão; desligue no Painel. |
| **Candidatura** | Playwright abre a vaga, preenche dados, anexa o currículo certo, usa o **banco de respostas aprovadas** e para em CAPTCHA/pergunta desconhecida. Envio automático só onde o fluxo é previsível (Greenhouse/Lever); no resto, **modo assistido**. |
| **Fila resiliente** | Estados persistidos no banco (`pending → running → needs_review/completed/failed`). Reiniciou o PC? Retoma sem reenviar candidatura. |
| **Dashboard** | Vagas, notas, candidaturas, erros por fonte, taxa de resposta, limite diário, **Pausar** e **PARAR TUDO**. |

## Instalação e uso

Requisitos: **Python 3.11+** e **Node 18+ (LTS)**.

**Windows — o jeito mais fácil:** dê **duplo clique em `Iniciar.bat`**. Na primeira vez ele cria o ambiente, instala tudo, baixa o Chromium e compila a interface; depois só abre o programa. O navegador abre sozinho em **http://127.0.0.1:8000**. Para encerrar, feche a janela preta.

> Prefere o terminal? No **cmd**: `Iniciar.bat`. No **PowerShell**: `.\Iniciar.bat` (os `.ps1` em `scripts/` só funcionam no PowerShell e podem exigir `Set-ExecutionPolicy -Scope Process Bypass`).

**Linux / macOS / WSL:**
```bash
./scripts/setup.sh   # uma vez
./scripts/run.sh     # sempre que quiser usar → http://127.0.0.1:8000
```

Desenvolvimento (hot reload): `./scripts/dev.sh` → frontend em http://localhost:5173.

### PostgreSQL (opcional)
```bash
docker compose up -d db
# no .env:
DATABASE_URL=postgresql+psycopg://jobs:jobs@localhost:5432/jobs
```

## Primeiros passos

0. Ao abrir, siga o quadro **Primeiros passos** no Painel: ele mostra o que falta e leva você a cada tela.
1. **Perfil → Importar**: envie o ZIP do LinkedIn (*Configurações → Privacidade de dados → Obter uma cópia dos seus dados*, marque Perfil/Posições/Formação/Competências/Idiomas) e/ou seu PDF. **Revise tudo**: a leitura de PDF é heurística; o ZIP é bem mais fiel.
2. **Perfil → O que você procura**: cargos, senioridade, locais, palavras a evitar, fontes e nota mínima (tudo em formulário).
3. **Currículos**: envie seus PDFs base (um por idioma).
4. **Painel → Coletar vagas agora** (depois roda sozinho a cada `COLLECT_INTERVAL_HOURS`).
5. **Vagas**: veja a nota e a justificativa, gere o currículo sob medida e clique **Preparar no navegador**.
6. Revise o formulário que abriu, envie você mesmo e marque como **Enviada** em *Candidaturas*.

## Segurança e termos de uso — leia

- **Envio automático ligado por padrão (chave no Painel)**, mas só para Greenhouse/Lever, com nota ≥ mínima, sem pergunta desconhecida, sem CAPTCHA, dentro do limite diário e sem candidatura recente na mesma empresa. O restante fica em *Aguardando você* (modo assistido).
- **LinkedIn**: o perfil é lido pelo **seu export/PDF**, não por scraping. A busca de vagas usa o endpoint público sem login, com poucas páginas e pausas; ele é frágil e o LinkedIn restringe scraping nos termos de uso — **não use sua conta logada** para raspar. O **Easy Apply nunca é automatizado** (risco real de bloqueio da conta): essas vagas abrem para você aplicar manualmente.
- **Indeed, Glassdoor e similares** não estão incluídos (bloqueio ativo/termos). Use *Vaga manual* para trazer anúncios deles ao fluxo.
- Gupy, Remotive, Himalayas e Jobicy usam endpoints públicos de portal; respeite os termos e limites de cada fonte. APIs não documentadas podem mudar — uma fonte quebrada **não derruba** as outras (o erro aparece no Painel).
- CAPTCHA e verificação de identidade **nunca são contornados**: a automação para e marca *needs_review*.
- A API escuta só em `127.0.0.1`. Não exponha na rede. O perfil do navegador (`data/browser-profile`) guarda cookies/logins que você fizer nele — está no `.gitignore`.
- Respeite `DAILY_APPLICATION_LIMIT`. Candidaturas em massa e genéricas funcionam mal e podem queimar sua reputação com recrutadores.

## Estrutura

```
backend/app/
  collectors/    # um coletor por fonte (REGISTRY)
  services/      # skills, importação PDF/LinkedIn, perfil, coleta+dedupe, tradução
  matching/      # scorer.py: nota explicável + eliminatórios
  resumes/       # builder.py: conteúdo multi-idioma, DOCX, PDF, validação
  automation/    # filler.py: Playwright
  scheduler/     # worker.py: fila persistente + APScheduler
  routes/        # FastAPI
frontend/        # React + TypeScript + Vite
data/            # banco, PDFs, currículos gerados (ignorado pelo git)
```

## Testes

```bash
cd backend && python -m pytest -q      # lógica central + fluxo da API (SQLite temporário)
cd frontend && npm run typecheck && npm run build
```

## Limitações conhecidas

- A importação de PDF depende do layout; sempre revise Experiências e datas.
- O reconhecimento de tecnologias usa um vocabulário (`services/skills.py`) — acrescente o que faltar. As respostas abertas agora são sugestões baseadas no perfil; perguntas pessoais/legais sem dados explícitos ficam vazias para revisão.
- Os adaptadores de formulário são genéricos (+ detecção Greenhouse/Lever); sites com formulários muito customizados vão cair em *needs_review*.
- As tabelas são criadas com `create_all` (sem Alembic ainda). Para evoluir o esquema em produção, adicione migrações.
- Defaults de `greenhouse_boards`/`lever_companies` são exemplos; troque pelas empresas que te interessam.

## Publicar no GitHub

```bash
git init && git add . && git commit -m "feat: Jobless"
git branch -M main
git remote add origin git@github.com:SEU_USUARIO/job-assistant.git
git push -u origin main
```
Confira antes que `git status` **não** lista `.env` nem `data/`.

Licença: MIT.
