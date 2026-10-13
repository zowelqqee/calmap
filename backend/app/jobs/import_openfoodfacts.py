"""Import a useful Russian subset of the Open Food Facts dump.

The dump is a tab-separated, gzip-compressed CSV. It is read one row at a time so
the full file never has to be loaded into memory on the VPS.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import html
import logging
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Open Food Facts contains long ingredient/category fields. Python's csv module
# defaults to 128 KiB per field, which is too small for a few valid dump rows.
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(2**31 - 1)

DEFAULT_PATH = "/data/openfoodfacts-products.csv.gz"
MAX_KCAL = 1_000.0
MAX_MACRO = 100.0
HTML_TAG_RE = re.compile(r"<[^>]+>")
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def _text(value: str | None) -> str:
    decoded = html.unescape(value or "")
    without_tags = HTML_TAG_RE.sub(" ", decoded)
    return " ".join(without_tags.strip().split())


def _number(value: str | None) -> float | None:
    """Read the first decimal number, tolerating OFF's empty/text values."""
    raw = _text(value).replace(",", ".")
    if not raw:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if match is None:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _bounded_number(value: str | None, *, maximum: float) -> float | None:
    number = _number(value)
    if number is None or number < 0 or number > maximum:
        return None
    return number


def _kcal(row: dict[str, str]) -> float | None:
    kcal = _bounded_number(row.get("energy-kcal_100g"), maximum=MAX_KCAL)
    if kcal is not None and kcal > 0:
        return kcal

    # Some rows only have energy_100g. OFF stores that value in kJ.
    energy_kj = _bounded_number(row.get("energy_100g"), maximum=MAX_KCAL * 4.184)
    if energy_kj is None or energy_kj <= 0:
        return None
    return energy_kj / 4.184


def _is_russian_product(row: dict[str, str]) -> bool:
    countries = " ".join(
        (_text(row.get("countries_en")), _text(row.get("countries_tags")))
    ).lower()
    return any(marker in countries for marker in ("russia", "россия", "ru:russia"))


def _category(value: str | None) -> str:
    categories = _text(value).lower()
    groups = (
        ("meat", ("meat", "мяс")),
        ("poultry", ("poultry", "кур", "chicken")),
        ("fish", ("fish", "рыб", "seafood", "морепродукт")),
        ("dairy", ("dairy", "dair", "молоч", "йогурт", "сыр")),
        ("eggs", ("egg", "яйц")),
        ("grains", ("cereal", "grain", "рис", "греч", "овся")),
        ("bakery", ("bread", "bakery", "хлеб", "выпеч")),
        ("legumes", ("legume", "bean", "чечев", "боб")),
        ("vegetables", ("vegetable", "овощ")),
        ("fruits", ("fruit", "фрукт", "ягод")),
        ("nuts", ("nut", "орех")),
        ("fats", ("oil", "fat", "масл")),
    )
    for category, markers in groups:
        if any(marker in categories for marker in markers):
            return category
    return "packaged"


def _allergens(value: str | None) -> list[str]:
    raw = _text(value).lower()
    mappings = (
        ("gluten", ("gluten", "глютен", "wheat", "пшени")),
        ("lactose", ("milk", "молок", "lactose", "лактоз")),
        ("egg", ("egg", "яйц")),
        ("soy", ("soy", "соя")),
        ("peanuts", ("peanut", "арахис")),
        ("nuts", ("nut", "орех")),
        ("fish", ("fish", "рыб")),
        ("seafood", ("shellfish", "crustacean", "моллюск", "ракообраз")),
    )
    return [code for code, markers in mappings if any(marker in raw for marker in markers)]


def normalize_row(row: dict[str, str]) -> dict[str, object] | None:
    """Convert one OFF row to the fields accepted by ``products``."""
    code = _text(row.get("code"))
    localized_name = _text(row.get("product_name_ru"))
    name = localized_name or _text(row.get("product_name"))
    if not code.isdigit() or not 8 <= len(code) <= 14 or not name:
        return None
    # Do not fill the Russian catalogue with an arbitrary English/technical name
    # when the localized OFF field is empty. Known brands with a localized name
    # (even in Latin characters) are still allowed.
    if not localized_name and CYRILLIC_RE.search(name) is None:
        return None
    if not _is_russian_product(row):
        return None

    kcal = _kcal(row)
    if kcal is None:
        return None

    def macro(column: str) -> float:
        return _bounded_number(row.get(column), maximum=MAX_MACRO) or 0.0

    return {
        "slug": f"off_{code}",
        "name": name[:255],
        "category": _category(row.get("categories_en") or row.get("categories")),
        "barcode": code,
        "kcal_per_100g": round(kcal, 2),
        "protein_per_100g": round(macro("proteins_100g"), 2),
        "fat_per_100g": round(macro("fat_100g"), 2),
        "carbs_per_100g": round(macro("carbohydrates_100g"), 2),
        "fiber_per_100g": round(macro("fiber_100g"), 2),
        "tags": [],
        "allergens": _allergens(row.get("allergens_tags")),
        "source": "openfoodfacts",
        "is_active": True,
    }


async def _upsert_batch(session: AsyncSession, rows: Iterable[dict[str, object]]) -> int:
    values = list(rows)
    if not values:
        return 0

    statement = insert(Product).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["slug"],
        set_={
            "name": statement.excluded.name,
            "category": statement.excluded.category,
            "barcode": statement.excluded.barcode,
            "kcal_per_100g": statement.excluded.kcal_per_100g,
            "protein_per_100g": statement.excluded.protein_per_100g,
            "fat_per_100g": statement.excluded.fat_per_100g,
            "carbs_per_100g": statement.excluded.carbs_per_100g,
            "fiber_per_100g": statement.excluded.fiber_per_100g,
            "allergens": statement.excluded.allergens,
            "source": statement.excluded.source,
            "is_active": statement.excluded.is_active,
            "updated_at": func.now(),
        },
    )
    await session.execute(statement)
    await session.commit()
    return len(values)


async def import_file(
    path: Path, *, limit: int, batch_size: int, dry_run: bool, replace: bool
) -> tuple[int, int]:
    if not path.is_file():
        raise FileNotFoundError(path)

    scanned = imported = 0
    batch: dict[str, dict[str, object]] = {}
    async with SessionLocal() as session:
        if replace and not dry_run:
            # Hide rows from an earlier import first. Valid rows are activated again
            # by the upsert below; this also removes stale English/technical rows.
            await session.execute(
                update(Product)
                .where(Product.source == "openfoodfacts")
                .values(is_active=False)
            )
            await session.commit()
        with gzip.open(
            path, mode="rt", encoding="utf-8-sig", errors="replace", newline=""
        ) as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            for row in reader:
                scanned += 1
                normalized = normalize_row(row)
                if normalized is None:
                    continue
                batch[str(normalized["slug"])] = normalized
                if len(batch) < batch_size:
                    continue

                remaining = limit - imported if limit else None
                values = list(batch.values())[:remaining]
                if not dry_run:
                    imported += await _upsert_batch(session, values)
                else:
                    imported += len(values)
                batch.clear()
                if limit and imported >= limit:
                    break
                if scanned % 100_000 == 0:
                    logger.info("scanned=%s imported=%s", scanned, imported)

            if batch and (not limit or imported < limit):
                remaining = limit - imported if limit else None
                values = list(batch.values())[:remaining]
                if not dry_run:
                    imported += await _upsert_batch(session, values)
                else:
                    imported += len(values)

    return scanned, imported


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path(DEFAULT_PATH))
    parser.add_argument(
        "--limit",
        type=int,
        default=50_000,
        help="maximum number of valid products to import; 0 means the whole dump",
    )
    parser.add_argument("--batch-size", type=int, default=1_000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="deactivate old Open Food Facts rows before importing the cleaned set",
    )
    args = parser.parse_args()
    if args.limit < 0 or args.batch_size < 1:
        parser.error("--limit must be >= 0 and --batch-size must be >= 1")
    return args


async def main() -> None:
    args = _parse_args()
    scanned, imported = await import_file(
        args.path,
        limit=args.limit,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        replace=args.replace,
    )
    mode = "проверено" if args.dry_run else "импортировано"
    logger.info(
        "Готово: просмотрено строк: %s, %s товаров: %s",
        scanned,
        mode,
        imported,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
