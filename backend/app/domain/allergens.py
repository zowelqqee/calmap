"""Allergen vocabulary shared by the questionnaire and the catalogue.

The questionnaire speaks the user's language ("Арахис", "Морепродукты"); the
catalogue tags products with a smaller set of codes. Mapping errs on the side of
exclusion: a dish wrongly hidden costs variety, a dish wrongly shown can cost health.
"""

from __future__ import annotations

from collections.abc import Iterable

#: Questionnaire code → catalogue allergen codes that must be excluded.
USER_TO_CATALOGUE: dict[str, frozenset[str]] = {
    "gluten": frozenset({"gluten"}),
    "lactose": frozenset({"lactose"}),
    "nuts": frozenset({"nuts", "peanut"}),
    "peanut": frozenset({"peanut", "nuts"}),
    "seafood": frozenset({"shellfish", "molluscs"}),
    "molluscs": frozenset({"molluscs", "shellfish"}),
    "fish": frozenset({"fish"}),
    "egg": frozenset({"egg"}),
    "soy": frozenset({"soy"}),
    "sesame": frozenset({"sesame", "seeds"}),
}

#: Accepted spellings in the questionnaire (codes and Russian labels).
ALIASES: dict[str, str] = {
    "глютен": "gluten",
    "лактоза": "lactose",
    "орехи": "nuts",
    "морепродукты": "seafood",
    "яйца": "egg", "яйцо": "egg", "eggs": "egg",
    "соя": "soy",
    "арахис": "peanut",
    "кунжут": "sesame",
    "рыба": "fish",
    "моллюски": "molluscs",
    **{code: code for code in USER_TO_CATALOGUE},
}


def normalise(values: Iterable[str]) -> list[str]:
    """Return sorted questionnaire codes; raise ValueError on an unknown allergen."""
    out: set[str] = set()
    for value in values:
        key = value.strip().lower()
        if not key:
            continue
        if key not in ALIASES:
            raise ValueError(f"unknown allergen: {value}")
        out.add(ALIASES[key])
    return sorted(out)


def catalogue_exclusions(user_allergens: Iterable[str] | None) -> frozenset[str]:
    """Catalogue codes to exclude for the stored questionnaire answers.

    Unknown legacy values are kept as-is so older profiles never lose a restriction.
    """
    excluded: set[str] = set()
    for code in user_allergens or ():
        excluded |= USER_TO_CATALOGUE.get(code, frozenset({code}))
    return frozenset(excluded)
