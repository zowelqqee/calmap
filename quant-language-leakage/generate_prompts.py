#!/usr/bin/env python3
"""Generate the benchmark prompt dataset for the quantization language-leakage experiment.

Four categories:
  A. pure_ru          - fully Russian, no Latin script at all (clean control)
  B. ru_en            - Russian + English technical terms
  C. ru_json_code     - Russian + JSON / Python / config / identifiers
  D. ru_en_json_long  - Russian + English terms + JSON/code, longer context

Hard rules enforced by this script:
  * every prompt contains an explicit "answer in Russian" instruction;
  * no CJK / Hiragana / Katakana / Hangul characters anywhere in a prompt
    (otherwise the leakage detector could not tell expected from unexpected
    Han characters);
  * pure_ru prompts contain no Latin letters at all;
  * output is deterministic for a given --seed.

Usage:
    python generate_prompts.py --out prompts.jsonl --n-per-category 25
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
from pathlib import Path

# --------------------------------------------------------------------------
# Slot pools
# --------------------------------------------------------------------------

RU_SERVICES = [
    "сервис выгрузки",
    "модуль расчёта тарифов",
    "очередь фоновых задач",
    "подсистема уведомлений",
    "шлюз платежей",
    "хранилище отчётов",
    "планировщик заданий",
    "сборщик метрик",
]

RU_ENVS = ["тестовом стенде", "предпродакшене", "боевом окружении", "локальном стенде"]

RU_ARTIFACTS = [
    "итоговый отчёт",
    "сводная таблица",
    "журнал прогона",
    "протокол приёмки",
    "сводка по инцидентам",
]

RU_ROLES = [
    "команде эксплуатации",
    "смежной команде",
    "руководителю направления",
    "дежурному инженеру",
    "аналитику",
]

EN_SERVICES = [
    "ingest-worker",
    "billing-gateway",
    "report-exporter",
    "search-indexer",
    "auth-proxy",
    "metrics-collector",
    "notification-dispatcher",
    "session-store",
]

EN_TERMS = [
    "retry policy",
    "circuit breaker",
    "backpressure",
    "connection pool",
    "graceful shutdown",
    "rolling update",
    "cold start",
    "read replica lag",
    "cache invalidation",
    "rate limiting",
]

EN_STAGES = ["staging", "production", "canary", "pre-prod", "sandbox"]

EN_METRICS = [
    "p95 latency",
    "error rate",
    "throughput",
    "queue depth",
    "timeout ratio",
    "retry count",
    "memory footprint",
]

FIELDS = [
    "timing",
    "incident_metrics",
    "run_mode",
    "attempts",
    "started_at",
    "finished_at",
    "peak_rss_mb",
    "dropped_events",
]

IDENTIFIERS = [
    "run_id",
    "batch_id",
    "tenant_id",
    "shard_key",
    "trace_id",
    "job_name",
    "checkpoint_path",
]

PY_FUNCS = [
    "collect_incident_metrics",
    "flush_pending_batch",
    "rebuild_search_index",
    "resolve_tariff_plan",
    "export_daily_report",
    "reconcile_payments",
]

CONFIG_KEYS = [
    "max_in_flight",
    "flush_interval_ms",
    "retry_backoff_ms",
    "worker_concurrency",
    "shard_count",
    "request_timeout_ms",
]

NUMBERS = ["2", "3", "4", "8", "12", "16", "24", "32", "64", "120", "250", "500"]

# Varied phrasings of "answer in Russian" so the model cannot latch onto one
# memorised construction.
RU_ONLY = [
    "Ответь на русском языке.",
    "Ответ дай на русском.",
    "Сформулируй ответ по-русски.",
    "Пиши ответ на русском языке.",
    "Изложи это на русском языке.",
    "Ответ должен быть на русском языке.",
    "Отвечай по-русски.",
    "Дай формулировку на русском языке.",
]

# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------

# A. pure_ru - no Latin letters allowed here.
T_PURE_RU = [
    "Второй полный прогон сейчас выполняется; {artifact} должен включать замеры времени и статистику инцидентов по всем режимам. Сформулируй статус одним предложением. {ru_only}",
    "{service_ru} на {env_ru} за ночь дважды перезапускался. Опиши в трёх пунктах, что стоит проверить в первую очередь. {ru_only}",
    "Нужно объяснить {role_ru}, почему повторная обработка занимает примерно вдвое больше времени, чем первая. Уложись в четыре предложения. {ru_only}",
    "Составь короткое сообщение о том, что {artifact} за прошлую неделю готов, но по двум режимам данные неполные. Не больше трёх предложений. {ru_only}",
    "Опиши разницу между полным и частичным прогоном для {service_ru} так, чтобы это было понятно {role_ru}. {ru_only}",
    "Сформулируй одно предложение о том, что задержка выросла примерно в {num} раза после переноса на {env_ru}. {ru_only}",
    "Напиши краткий вывод: очередь разобрана, потерь нет, но время ожидания в пике держалось около {num} минут. {ru_only}",
    "Объясни коротко, почему повторный запуск {service_ru} нельзя начинать до завершения текущего. Два-три предложения. {ru_only}",
    "Подготовь заметку для {role_ru}: {artifact} будет готов позже запланированного примерно на {num} часа. Укажи причину и новый срок. {ru_only}",
    "Перечисли пять признаков того, что {service_ru} на {env_ru} работает нестабильно. Только перечисление, без пояснений. {ru_only}",
    "Опиши одним абзацем, что именно нужно измерять при сравнении двух режимов работы {service_ru}. {ru_only}",
    "Сформулируй запрос {role_ru}: требуется доступ к журналам {service_ru} за последние {num} суток. Вежливо и кратко. {ru_only}",
    "Напиши короткое резюме встречи: решили отложить перенос {service_ru} на {env_ru} до конца недели, ответственный назначен. {ru_only}",
    "Объясни в двух предложениях, почему усреднённое время ответа скрывает редкие длинные задержки. {ru_only}",
]

# B. ru_en - Russian narrative with English technical terms.
T_RU_EN = [
    "Второй full quality run сейчас в процессе; нужно свести timing и incident metrics по всем режимам. Сформулируй статус одним предложением. {ru_only}",
    "На {stage} у {en_service} выросла {metric}, при этом {term} ведёт себя штатно. Опиши вероятную причину в трёх пунктах. {ru_only}",
    "Объясни разницу между {term} и {term2} на примере {en_service}. Четыре-пять предложений. {ru_only}",
    "После rolling update у {en_service} на {stage} появился cold start примерно на {num} секунд. Напиши короткий комментарий для дежурного. {ru_only}",
    "Нужно описать, как {term} влияет на {metric} в {en_service}. Уложись в три предложения. {ru_only}",
    "Сводка для команды: canary deploy {en_service} остановлен, rollback выполнен, {metric} вернулась к baseline. Оформи это одним абзацем. {ru_only}",
    "Опиши, какие health checks и readiness probes стоит добавить в {en_service}, чтобы {term} срабатывал корректно. {ru_only}",
    "У {en_service} на {stage} наблюдается read replica lag около {num} секунд. Объясни, чем это грозит отчётности. {ru_only}",
    "Сравни два подхода к {term} для {en_service}: fail fast и retry with backoff. По два аргумента на каждый. {ru_only}",
    "Напиши короткое объяснение для аналитика, почему {metric} на {stage} и в production отличаются в {num} раза. {ru_only}",
    "Сформулируй acceptance criteria для задачи «включить {term} в {en_service}». Списком, не более пяти пунктов. {ru_only}",
    "Опиши сценарий инцидента: {en_service} исчерпал connection pool, {metric} ушла за порог, автоматический failover не сработал. {ru_only}",
    "Объясни, почему graceful shutdown в {en_service} важнее, чем ускорение старта, если включён {term}. {ru_only}",
]

# C. ru_json_code - Russian + JSON / Python / config / identifiers.
T_RU_JSON_CODE = [
    'Итоговый JSON должен содержать поля "{field}", "{field2}" и "{ident}". Опиши назначение каждого поля по одному предложению. {ru_only}',
    'Проверь структуру и скажи, чего не хватает: {{"{ident}": "r-{num}", "{field}": null, "status": "running"}}. {ru_only}',
    "Функция `{func}()` возвращает пустой список, если {ident} не задан. Объясни, почему это плохая идея, и предложи замену. {ru_only}",
    "В конфиге выставлено `{cfg}: {num}`, а `{cfg2}: {num2}`. Объясни, к чему приведёт такое сочетание. {ru_only}",
    'Опиши схему ответа: {{"{ident}": str, "{field}": float, "{field2}": int}}. Нужен короткий комментарий к каждому полю. {ru_only}',
    "Напиши, что делает этот код, и укажи одну проблему:\n```python\ndef {func}(items):\n    return [x for x in items if x.get(\"{field}\")]\n```\n{ru_only}",
    'Нужно добавить в payload поле "{field}" рядом с "{field2}". Сформулируй описание изменения для changelog. {ru_only}',
    "Объясни, чем `{cfg}` отличается от `{cfg2}` в настройках воркера. Два предложения на каждый параметр. {ru_only}",
    'Валидация падает на записи {{"{ident}": "", "{field}": 0}}. Опиши, какое правило проверки здесь нарушено. {ru_only}',
    "Опиши в трёх пунктах, как безопасно переименовать `{ident}` в `{ident2}` в уже опубликованном API. {ru_only}",
    "Дан фрагмент лога: `{func} failed: {cfg}={num} exceeded`. Объясни, что произошло, и что смотреть дальше. {ru_only}",
    'Составь короткое описание для поля "{field}" в документации схемы: тип, единицы измерения, поведение по умолчанию. {ru_only}',
    "Объясни, почему `{cfg}: {num}` нельзя менять на лету без перезапуска, если внутри используется `{func}()`. {ru_only}",
]

# D. ru_en_json_long - longer, Russian + English terms + JSON/code.
T_RU_EN_JSON_LONG = [
    (
        "Второй full quality run сейчас в процессе; это нужно только для того, чтобы итоговый JSON "
        'включал timing и incident metrics для всех режимов. Схема примерно такая: '
        '{{"{ident}": "run-{num}", "mode": "full", "{field}": {{"started_at": null, "finished_at": null}}, '
        '"{field2}": []}}. '
        "Первый прогон отработал на {stage} без ошибок, второй запущен на том же датасете, но с включённым {term}. "
        "Сформулируй статус для дежурного инженера одним предложением, а затем перечисли три поля, "
        "которые обязательно должны быть заполнены до закрытия задачи. {ru_only}"
    ),
    (
        "У {en_service} на {stage} за последние сутки {metric} выросла примерно в {num} раза. "
        "В конфиге стоит `{cfg}: {num2}`, {term} включён, retry policy оставлена по умолчанию. "
        'Из мониторинга приходит такой объект: {{"{ident}": "{ident2}-17", "{field}": {num}, "{field2}": {num2}}}. '
        "Опиши: что скорее всего происходит, какие два параметра стоит поменять в первую очередь "
        "и как проверить гипотезу за один прогон. Ответ структурируй тремя короткими разделами. {ru_only}"
    ),
    (
        "Готовим постмортем по инциденту в {en_service}. Известно: сработал {term}, "
        "{metric} держалась выше порога около {num} минут, часть задач ушла в dead letter queue. "
        "Функция `{func}()` в это время писала записи вида "
        '{{"{ident}": "...", "{field}": null, "attempts": {num2}}}. '
        "Напиши раздел «Хронология и причина» на пять-шесть предложений, затем два пункта "
        "«Что делаем дальше». Без markdown-заголовков, просто текст и список. {ru_only}"
    ),
    (
        "Нужно описать миграцию {en_service} с {stage} на production. Сейчас в конфиге "
        "`{cfg}: {num}` и `{cfg2}: {num2}`, включены {term} и {term2}. "
        'Формат события: {{"{ident}": str, "{field}": int, "{field2}": bool}}. '
        "Объясни, какие значения параметров придётся пересчитать под другой объём трафика, "
        "какой риск возникает при rolling update, и какой rollback-план предложить. "
        "Уложись в один абзац плюс список из четырёх пунктов. {ru_only}"
    ),
    (
        "Собираем сводный отчёт по трём режимам работы {en_service}: baseline, {stage} и полный прогон. "
        "Для каждого режима нужны {metric} и количество повторов. "
        "Черновик схемы:\n"
        "```python\n"
        "def {func}(runs):\n"
        '    return {{r["{ident}"]: r["{field}"] for r in runs}}\n'
        "```\n"
        "Объясни, какие поля потеряются при такой агрегации, предложи исправленную структуру "
        "результата и опиши, как в неё добавить {field2}. Три коротких абзаца. {ru_only}"
    ),
    (
        "Дежурный передаёт смену. Состояние: {en_service} на {stage} работает, {term} активен, "
        "{metric} в норме, но `{cfg}` был временно поднят до {num} и обратно не возвращён. "
        'В очереди лежит {num2} задач вида {{"{ident}": "...", "{field}": "pending"}}. '
        "Напиши текст передачи смены: что сделано, что не сделано, что нужно проверить "
        "в ближайший час. Пять-семь предложений, деловой тон. {ru_only}"
    ),
    (
        "Ревью изменения в {en_service}. Автор добавил в payload поля \"{field}\" и \"{field2}\", "
        "переименовал `{ident}` в `{ident2}` и выставил `{cfg}: {num}`. "
        "Обратной совместимости в описании нет, {term} не упомянут. "
        "Сформулируй три конкретных комментария к ревью и один вопрос автору. "
        "Каждый комментарий - одно-два предложения. {ru_only}"
    ),
]

TEMPLATES = {
    "pure_ru": T_PURE_RU,
    "ru_en": T_RU_EN,
    "ru_json_code": T_RU_JSON_CODE,
    "ru_en_json_long": T_RU_EN_JSON_LONG,
}

# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

CJK_LIKE = re.compile(
    "["
    "⺀-⻿"  # CJK radicals supplement
    "⼀-⿟"  # Kangxi radicals
    "　-〿"  # CJK symbols and punctuation
    "぀-ゟ"  # Hiragana
    "゠-ヿ"  # Katakana
    "㄀-ㄯ"  # Bopomofo
    "㄰-㆏"  # Hangul compatibility jamo
    "㐀-䶿"  # CJK ext A
    "一-鿿"  # CJK unified ideographs
    "ꥠ-꥿"  # Hangul jamo extended-A
    "가-힣"  # Hangul syllables
    "豈-﫿"  # CJK compatibility ideographs
    "＀-￯"  # Halfwidth/fullwidth forms
    "]"
)

LATIN = re.compile("[A-Za-z]")


def validate(prompt: str, category: str) -> None:
    hit = CJK_LIKE.search(prompt)
    if hit:
        raise ValueError(
            f"CJK-like character {hit.group()!r} "
            f"(U+{ord(hit.group()):04X} {unicodedata.name(hit.group(), '?')}) in prompt: {prompt[:80]!r}"
        )
    if category == "pure_ru" and LATIN.search(prompt):
        raise ValueError(f"Latin letter in pure_ru prompt: {prompt[:80]!r}")
    if not any(marker in prompt for marker in ("русск", "по-русски")):
        raise ValueError(f"Prompt has no Russian-language instruction: {prompt[:80]!r}")


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


def two_distinct(rng: random.Random, pool: list[str]) -> tuple[str, str]:
    a, b = rng.sample(pool, 2)
    return a, b


def fill(template: str, rng: random.Random) -> str:
    term, term2 = two_distinct(rng, EN_TERMS)
    field, field2 = two_distinct(rng, FIELDS)
    ident, ident2 = two_distinct(rng, IDENTIFIERS)
    cfg, cfg2 = two_distinct(rng, CONFIG_KEYS)
    num, num2 = two_distinct(rng, NUMBERS)
    slots = {
        "service_ru": rng.choice(RU_SERVICES),
        "env_ru": rng.choice(RU_ENVS),
        "artifact": rng.choice(RU_ARTIFACTS),
        "role_ru": rng.choice(RU_ROLES),
        "en_service": rng.choice(EN_SERVICES),
        "stage": rng.choice(EN_STAGES),
        "metric": rng.choice(EN_METRICS),
        "func": rng.choice(PY_FUNCS),
        "term": term,
        "term2": term2,
        "field": field,
        "field2": field2,
        "ident": ident,
        "ident2": ident2,
        "cfg": cfg,
        "cfg2": cfg2,
        "num": num,
        "num2": num2,
        "ru_only": rng.choice(RU_ONLY),
    }
    return template.format(**slots)


def build(n_per_category: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    out: list[dict] = []
    for category, templates in TEMPLATES.items():
        seen: set[str] = set()
        prompts: list[str] = []
        attempts = 0
        while len(prompts) < n_per_category:
            attempts += 1
            if attempts > 400 * n_per_category:
                raise RuntimeError(
                    f"could not build {n_per_category} unique prompts for {category}; "
                    "add more templates or slot values"
                )
            template = templates[len(prompts) % len(templates)]
            text = fill(template, rng)
            if text in seen:
                continue
            validate(text, category)
            seen.add(text)
            prompts.append(text)
        for i, text in enumerate(prompts, start=1):
            out.append(
                {
                    "prompt_id": f"{category}_{i:03d}",
                    "category": category,
                    "prompt": text,
                    "n_chars": len(text),
                }
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="prompts.jsonl", help="output JSONL path")
    ap.add_argument("--n-per-category", type=int, default=25, help="prompts per category (4 categories)")
    ap.add_argument("--seed", type=int, default=20260811, help="RNG seed (dataset is reproducible)")
    args = ap.parse_args()

    records = build(args.n_per_category, args.seed)

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    by_cat: dict[str, list[int]] = {}
    for rec in records:
        by_cat.setdefault(rec["category"], []).append(rec["n_chars"])
    print(f"wrote {len(records)} prompts -> {path}")
    for cat, lens in by_cat.items():
        print(f"  {cat:<16} n={len(lens):<4} chars min={min(lens)} mean={sum(lens)//len(lens)} max={max(lens)}")
    print("validation: no CJK/Kana/Hangul in any prompt; every prompt asks for a Russian answer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
