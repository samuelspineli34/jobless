"""Vocabulário de tecnologias, detecção de senioridade, anos exigidos e idioma de um texto."""
import re

# canônico|alias|alias ...   (aliases comparados sem diferenciar maiúsculas)
_RAW = """
python
typescript
javascript|js|ecmascript
node.js|nodejs|node
react|react.js|reactjs
react native
next.js|nextjs
vue|vue.js|vuejs
angular
svelte
html|html5
css|css3
tailwind|tailwindcss
sass|scss
flask
fastapi
django
express|express.js
nestjs|nest.js
spring boot|springboot
spring
java
kotlin
c#|csharp
.net|dotnet|asp.net
c++|cpp
golang
rust
php
laravel
ruby
ruby on rails|rails
swift
scala
sql
postgresql|postgres|psql
mysql
sqlite
mongodb|mongo
redis
elasticsearch|opensearch
kafka
rabbitmq
graphql
rest api|restful|rest apis|api rest|apis rest|apis restful
websockets|websocket
docker
kubernetes|k8s
terraform
ansible
aws|amazon web services
azure
gcp|google cloud
linux
git
github actions
gitlab ci
ci/cd|cicd|ci-cd
jenkins
pytest
jest
cypress
playwright
selenium
sqlalchemy
pydantic
alembic
celery
pandas
numpy
scikit-learn|sklearn
pytorch
tensorflow
machine learning|ml|aprendizado de máquina|aprendizagem de máquina
llm|llms|large language models
langchain
openai
microservices|microsserviços|microservicos
oauth|oauth2
jwt
agile|scrum|kanban|ágil|agil
tdd
airflow
spark|pyspark
dbt
snowflake
bigquery
power bi
figma
jira
devops
nginx
vite
webpack
redux
handsontable
bash|shell script
powershell
flutter
android
ios
"""


def _compile():
    pats = {}
    for line in _RAW.strip().splitlines():
        names = [n.strip().lower() for n in line.split("|") if n.strip()]
        alts = sorted(set(names), key=len, reverse=True)
        body = "|".join(re.escape(a) for a in alts)
        pats[names[0]] = re.compile(rf"(?<![\w+#.])(?:{body})(?![\w+#])", re.I)
    return pats


PATTERNS = _compile()
DISPLAY = {"node.js": "Node.js", "next.js": "Next.js", "c#": "C#", "c++": "C++", ".net": ".NET",
           "aws": "AWS", "gcp": "GCP", "sql": "SQL", "css": "CSS", "html": "HTML", "ci/cd": "CI/CD",
           "tdd": "TDD", "llm": "LLM", "jwt": "JWT", "ios": "iOS", "dbt": "dbt", "php": "PHP",
           "postgresql": "PostgreSQL", "mysql": "MySQL", "sqlite": "SQLite", "mongodb": "MongoDB",
           "graphql": "GraphQL", "fastapi": "FastAPI", "sqlalchemy": "SQLAlchemy", "javascript": "JavaScript",
           "typescript": "TypeScript", "rest api": "REST API", "oauth": "OAuth", "devops": "DevOps"}


def display(name: str) -> str:
    return DISPLAY.get(name, name.title() if name == name.lower() else name)


def extract_skills(text: str) -> list[str]:
    """Nomes canônicos (minúsculos) das tecnologias encontradas no texto."""
    if not text:
        return []
    return sorted(k for k, p in PATTERNS.items() if p.search(text))


def normalize_skill(name: str) -> str:
    n = name.strip()
    for k, p in PATTERNS.items():
        if p.fullmatch(n):
            return k
    return n.lower()


_NICE = re.compile(
    r"(nice[- ]to[- ]have|bonus|a plus|desej[áa]vel|diferenciais|diferencial|preferred|"
    r"good to have|desirable|w[üu]nschenswert|valorizamos)", re.I)


def split_requirements(text: str) -> tuple[str, str]:
    m = _NICE.search(text or "")
    if m and m.start() > 80:
        return text[: m.start()], text[m.start():]
    return text or "", ""


LEVELS = ["intern", "junior", "mid", "senior", "lead"]
_LEVEL_PATTERNS = [
    ("lead", r"\b(staff|principal|lead|head of|especialista|architect|arquiteto|tech lead)\b"),
    ("senior", r"\b(senior|sênior|sr\.?)(?=\W|$)"),
    ("mid", r"\b(mid[- ]?level|mid|pleno|intermediate|(software|developer|engineer)\s+(ii|2))(?=\W|$)"),
    ("junior", r"\b(junior|júnior|jr\.?|entry[- ]level|(software|developer|engineer)\s+(i|1))(?=\W|$)"),
    ("intern", r"\b(intern|internship|estagi[áa]rio|estágio|estagio|trainee)\b"),
]


def detect_seniority(title: str, description: str = "") -> str:
    for text in (title or "", (description or "")[:300]):
        for level, pat in _LEVEL_PATTERNS:
            if re.search(pat, text, re.I):
                return level
    return ""


def level_index(level: str) -> int | None:
    return LEVELS.index(level) if level in LEVELS else None


def years_required(text: str) -> int | None:
    for m in re.finditer(r"(\d{1,2})\s*\+?\s*(?:years?|yrs|anos?)\b", text or "", re.I):
        n = int(m.group(1))
        if 1 <= n <= 20:
            return n
    return None


_STOP = {
    "en": {"the", "and", "with", "you", "for", "are", "will", "our", "team", "have", "your", "work", "experience"},
    "pt": {"para", "com", "você", "uma", "que", "vaga", "equipe", "não", "dos", "das", "são", "nossa", "ser", "experiência"},
    "es": {"para", "con", "una", "que", "equipo", "nuestro", "los", "las", "será", "trabajo", "puesto", "experiencia"},
    "de": {"und", "die", "der", "das", "mit", "für", "sie", "wir", "ein", "eine", "erfahrung", "deine"},
    "fr": {"et", "les", "des", "pour", "avec", "vous", "une", "nous", "expérience", "équipe", "dans"},
}


def detect_language(text: str) -> str:
    words = re.findall(r"[a-zà-ÿ]+", (text or "").lower()[:4000])
    if not words:
        return "en"
    scores = {lang: sum(1 for w in words if w in sw) for lang, sw in _STOP.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else "en"
