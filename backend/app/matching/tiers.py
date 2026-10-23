"""Faixas de localização com reconhecimento robusto e ampliado para Belo Horizonte e Minas Gerais."""
import re

TIERS = ("bh", "brazil", "remote")
TIER_LABEL = {"bh": "Belo Horizonte", "brazil": "Brasil", "remote": "Remoto", "other": "Outro"}
DEFAULT_FOCUS = {"bh": 40, "brazil": 40, "remote": 20}

# Padrões amplos cobrindo Belo Horizonte, MG e Grande BH
_BH = re.compile(
    r"belo horizonte|\bbh\b|minas gerais|\bmg\b|contagem|betim|nova lima|"
    r"sabar[áa]|santa luzia|lagoa santa|vespasiano|ribeir[ãa]o das neves|pará de minas|sete lagoas", 
    re.I
)
_BR = re.compile(r"\b(brazil|brasil)\b|s[ãa]o paulo|rio de janeiro|curitiba|porto alegre|florian[óo]polis|recife|salvador|bras[íi]lia", re.I)
_UF = re.compile(r"(?:,|\s-|\s)\s*(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b", re.I)
_REMOTE = re.compile(r"remote|remoto|anywhere|worldwide|home ?office|latam|latin america|global", re.I)
_RESTRICTED = re.compile(r"(us only|usa only|u\.s\. only|united states only|uk only|work authorization|authorized to work in the (?:us|united states))", re.I)


def location_tier(location: str = "", title: str = "", remote: bool = False, language: str = "", description: str = "") -> str:
    loc = (location or "").strip()
    blob = f"{loc} {title} {description}".lower()

    if _RESTRICTED.search(blob) and not ("brazil" in blob or "brasil" in blob or "belo horizonte" in blob or "mg" in blob):
        return "other"

    # Prioridade absoluta para Belo Horizonte e Grande BH / MG
    if _BH.search(loc) or _BH.search(title or "") or _BH.search(description[:500] if description else ""):
        return "bh"
    
    if _BR.search(loc) or _UF.search(loc) or "brasil" in loc.lower() or "brazil" in loc.lower():
        return "brazil"
        
    if remote and (language or "").lower().startswith("pt") and not loc:
        return "brazil"

    if remote or _REMOTE.search(loc) or _REMOTE.search(title):
        return "remote"
    
    return "other"


def targets(total: int, focus: dict) -> dict[str, int]:
    s = sum(max(0, focus.get(t, 0)) for t in TIERS) or 1
    shares = {t: total * max(0, focus.get(t, 0)) / s for t in TIERS}
    out = {t: int(shares[t]) for t in TIERS}
    rest = total - sum(out.values())
    for t in sorted(TIERS, key=lambda t: (-(shares[t] - out[t]), TIERS.index(t)))[:max(0, rest)]:
        out[t] += 1
    return out


def allocate(available: dict, focus: dict, limit: int, done: dict | None = None) -> dict[str, int]:
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