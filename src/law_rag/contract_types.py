"""Contract types, party roles and party-perspective helpers.

Contract types: lease, service, employment, other. Each type except "other" has
two party roles. A request may name the user's role (`party`); unknown or
missing values give a neutral analysis. Role ids are English; the Turkish
labels are what the user sees.
"""

from dataclasses import dataclass

from .models import RiskFinding
from .text_utils import searchable

BOTH = "both"
OTHER = "other"


@dataclass(frozen=True)
class PartyRole:
    id: str
    label: str  # Turkish, shown to the user
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class ContractType:
    id: str
    label: str
    aliases: tuple[str, ...]
    roles: tuple[PartyRole, ...]

    def role(self, role_id: str | None) -> PartyRole | None:
        return next((role for role in self.roles if role.id == role_id), None)

    def other_role(self, role_id: str) -> PartyRole | None:
        return next((role for role in self.roles if role.id != role_id), None)


CONTRACT_TYPES: dict[str, ContractType] = {
    "lease": ContractType(
        id="lease",
        label="kira sözleşmesi",
        aliases=("lease", "rental", "rent", "kira", "kira sozlesmesi", "konut kira", "isyeri kira"),
        roles=(
            PartyRole("tenant", "kiracı", ("tenant", "kiraci", "lessee")),
            PartyRole("landlord", "kiraya veren", ("landlord", "kiraya veren", "ev sahibi", "lessor", "mal sahibi")),
        ),
    ),
    "service": ContractType(
        id="service",
        label="hizmet sözleşmesi",
        aliases=("service", "services", "hizmet", "hizmet sozlesmesi", "hizmet alim", "eser", "yazilim"),
        roles=(
            PartyRole("client", "hizmet alan", ("client", "customer", "hizmet alan", "musteri", "is sahibi")),
            PartyRole("provider", "hizmet veren", ("provider", "supplier", "vendor", "hizmet veren", "yuklenici", "tedarikci")),
        ),
    ),
    "employment": ContractType(
        id="employment",
        label="iş sözleşmesi",
        aliases=("employment", "labor", "labour", "is sozlesmesi", "is", "calisma", "istihdam"),
        roles=(
            PartyRole("employee", "işçi", ("employee", "worker", "isci", "calisan", "personel")),
            PartyRole("employer", "işveren", ("employer", "isveren")),
        ),
    ),
    OTHER: ContractType(id=OTHER, label="sözleşme", aliases=("other", "diger", "general"), roles=()),
}


def _key(value: str) -> str:
    return " ".join(searchable(value).replace("_", " ").replace("-", " ").split())


def normalize_contract_type(value: str | None) -> str | None:
    """Canonical type id, the raw value if unrecognised (behaves as before), or None."""
    if not value or not value.strip():
        return None
    key = _key(value)
    for contract_type in CONTRACT_TYPES.values():
        if key == contract_type.id or key in contract_type.aliases:
            return contract_type.id
    return value.strip()


def normalize_party(contract_type: str | None, party: str | None) -> tuple[str | None, str | None]:
    """Return (contract_type, party_role_id).

    The party is resolved against the given type; when no type was given, an
    unambiguous role alias also infers the type (party "tenant" implies a
    lease). An unrecognised type or party gives None, i.e. a neutral analysis.
    """
    if not party or not party.strip():
        return contract_type, None
    key = _key(party)
    candidates = [
        (type_id, role.id)
        for type_id, definition in CONTRACT_TYPES.items()
        for role in definition.roles
        if key == role.id or key in role.aliases
    ]
    if contract_type in CONTRACT_TYPES:
        for type_id, role_id in candidates:
            if type_id == contract_type:
                return contract_type, role_id
        return contract_type, None
    if contract_type is None and len(candidates) == 1:
        return candidates[0]
    return contract_type, None


def roles_for(contract_type: str | None) -> tuple[PartyRole, ...]:
    definition = CONTRACT_TYPES.get(contract_type or "")
    return definition.roles if definition else ()


def role_label(contract_type: str | None, role_id: str | None) -> str | None:
    definition = CONTRACT_TYPES.get(contract_type or "")
    role = definition.role(role_id) if definition else None
    return role.label if role else None


def normalize_disadvantaged(contract_type: str | None, value: object) -> str | None:
    """Map model output ("kiracı", "tenant", "both", "her ikisi") to a role id."""
    if value is None:
        return None
    key = _key(str(value))
    if key in {"both", "her ikisi", "iki taraf", "ikisi", "taraflar", "mutual"}:
        return BOTH
    for role in roles_for(contract_type):
        if key == role.id or key in role.aliases or key == _key(role.label):
            return role.id
    return None


# Static mapping used by the rule-based analyzer: which side a category usually
# works against. Anything not listed is treated as affecting both sides.
DISADVANTAGE_BY_CATEGORY: dict[str, dict[str, str]] = {
    "lease": {
        "cash_payment": "tenant",
        "deposit_forfeiture": "tenant",
        "penalty_clause": "tenant",
        "unlawful_entry": "tenant",
        "eviction_undertaking": "tenant",
        "rent_increase": "tenant",
        "payment_interest": "tenant",
    },
    "service": {
        "data_protection": "client",
        "intellectual_property": "client",
        "liability": "client",
        "payment_interest": "client",
        "cash_payment": "client",
    },
    "employment": {
        "probation_period": "employee",
        "non_compete": "employee",
        "termination": "employee",
        "penalty_clause": "employee",
        "data_protection": "employee",
        "intellectual_property": "employee",
    },
}


def default_disadvantaged(contract_type: str | None, category: str) -> str | None:
    if contract_type not in CONTRACT_TYPES or contract_type == OTHER:
        return None
    return DISADVANTAGE_BY_CATEGORY.get(contract_type, {}).get(category, BOTH)


def applies_to(finding: RiskFinding, party: str | None) -> bool:
    if party is None:
        return True
    return finding.disadvantaged_party in (None, BOTH, party)


def apply_party(findings: list[RiskFinding], party: str | None) -> list[RiskFinding]:
    """Set `applies_to_user` on each finding for the user's side."""
    return [
        finding.model_copy(update={"applies_to_user": applies_to(finding, party)})
        for finding in findings
    ]


# Keyword guess used only when no contract type was given, so the statutory
# checks and the missing-clause checklist still have a type to work with.
_TYPE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("lease", ("kiraci", "kiraya veren", "kiralanan", "kira bedeli")),
    ("employment", ("isci", "isveren", "is sozlesmesi", "ucret")),
    ("service", ("hizmet", "yuklenici", "hizmet alan", "hizmet veren")),
]


def guess_contract_type(text: str) -> str | None:
    lowered = searchable(text)
    scores = [
        (sum(lowered.count(term) for term in terms), type_id) for type_id, terms in _TYPE_HINTS
    ]
    best_score, best_type = max(scores)
    return best_type if best_score >= 2 else None
