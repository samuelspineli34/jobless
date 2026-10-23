"""Faixas de localização (foco da busca) e distribuição de cotas.
bh = Belo Horizonte e Grande BH · brazil = resto do Brasil · remote = remoto fora do Brasil."""
import re

TIERS = ("bh", "brazil", "remote")           # também é a ordem de prioridade
TIER_LABEL = {"bh": "Belo Horizonte", "brazil": "Brasil", "remote": "Remoto", "other": "Outro"}
DEFAULT_FOCUS = {"bh": 85, "brazil": 5, "remote": 10}

_BH = re.compile(r"belo horizonte|\bbh\b|contagem|betim|nova lima|sabar[áa]|santa luzia|lagoa santa|vespasiano|ribeir[ãa]o das neves", re.I)
_BR = re.compile(r"\b(brazil|brasil)\b|minas gerais|s[ãa]o paulo|rio de janeiro|curitiba|porto alegre|florian[óo]polis|recife|"
                 r"fortaleza|salvador|bras[íi]lia|campinas|goi[âa]nia|vit[óo]ria|uberl[âa]ndia|juiz de fora", re.I)
_UF = re.compile(r"(?:,|\s-|\s)\s*(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\s*$")
_GENERIC_REMOTE = re.compile(r"^\W*(remote|remoto|anywhere|worldwide|home ?office|latam|latin america|global)?\W*$", re.I)


def location_tier(location: str = "", title: str = "", remote: bool = False, language: str = "") -> str:
    loc = (location or "").strip()
    if _BH.search(loc) or _BH.search(title or ""):
        return "bh"
    if _BR.search(loc) or _UF.search(loc):
        return "brazil"
    if remote:
        # vaga remota em português e sem país estrangeiro explícito: provavelmente brasileira
        return "brazil" if language == "pt" and _GENERIC_REMOTE.match(loc) else "remote"
    return "other"


def targets(total: int, focus: dict) -> dict[str, int]:
    """Cota inteira por faixa (maior resto): total=20, 85/5/10 -> bh 17, brazil 1, remote 2."""
    s = sum(max(0, focus.get(t, 0)) for t in TIERS) or 1
    shares = {t: total * max(0, focus.get(t, 0)) / s for t in TIERS}
    out = {t: int(shares[t]) for t in TIERS}
    rest = total - sum(out.values())
    for t in sorted(TIERS, key=lambda t: (-(shares[t] - out[t]), TIERS.index(t)))[:max(0, rest)]:
        out[t] += 1
    return out


def allocate(available: dict, focus: dict, limit: int, done: dict | None = None) -> dict[str, int]:
    """Quantas vagas pegar de cada faixa. Respeita a cota do foco (descontando o que já foi feito hoje);
    a cota que sobra numa faixa sem vagas suficientes é redistribuída na ordem bh > brazil > remote."""
    done = done or {}
    remaining = max(0, limit - sum(done.get(t, 0) for t in TIERS))
    quota = {t: max(0, tg - done.get(t, 0)) for t, tg in targets(limit, focus).items()}
    take = {t: min(available.get(t, 0), quota[t]) for t in TIERS}
    left = remaining - sum(take.values())
    for t in TIERS:
        if left <= 0:
            break
        extra = min(left, available.get(t, 0) - take[t])
        take[t] += extra
        left -= extra
    over = sum(take.values()) - remaining
    for t in reversed(TIERS):
        if over <= 0:
            break
        cut = min(over, take[t])
        take[t] -= cut
        over -= cut
    return take
