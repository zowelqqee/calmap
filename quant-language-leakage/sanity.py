#!/usr/bin/env python3
"""Cheap, conservative semantic-collapse detector.

The question it answers is narrow and specific:

    is this "a normal Russian answer that happens to contain a foreign token"
    or "the model fell apart and there is a Han character somewhere in the rubble"?

That distinction decides whether a Han intrusion is evidence about *language selection*
or merely evidence that the model is broken. No LLM judge, no embeddings — only cheap
character/word statistics.

Three-state on purpose. `uncertain` is a real answer, not a fallback: anything that
cannot be judged confidently (too short, mostly code, contradictory signals) stays
`uncertain` rather than being declared sane or collapsed. Only the `sane` bucket is
treated as evidence in the main analysis.

Signals: replacement chars, control/private-use chars, punctuation+symbol density,
markdown/underscore noise, digit density, alphabetic density, Cyrillic share of letters,
longest identical-character run, word-level repetition (distinct-word ratio and repeated
4-grams), Shannon character entropy, mean word length, response length, plus four
word-shape signals — share of 1-2 character words, words mixing letters and digits,
words without a vowel, and characters inside hyphen/underscore chains. The word-shape
group exists because lexically diverse Cyrillic nonsense
("ар-ад-прелиест-нап-на-нау-на eBay-2-22_") passes every density and entropy test.

Answering in the wrong language is reported separately as `wrong_output_language`
rather than as a collapse: an English-only answer is a compliance failure, not rubble.
It still never counts as `sane`.

Code blocks and inline code are stripped before the *linguistic* signals are computed,
because `ru_json_code` prompts legitimately invite JSON and Python in the answer; the
structural signals still see the whole response.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

FENCE_RE = re.compile(r"```.*?(?:```|$)", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}")
WORD_RE = re.compile(r"\w+", re.UNICODE)
CYRILLIC_RE = re.compile(r"[Ѐ-ӿԀ-ԯ]")
LATIN_RE = re.compile(r"[A-Za-z]")
MARKDOWN_NOISE = set("_*#`~|<>[]{}\\/^=+")

# --- thresholds -----------------------------------------------------------
# Hard collapse: any one of these is sufficient. Deliberately extreme, so that a
# merely unusual answer lands in `uncertain` instead.
HARD = {
    "replacement_ratio": 0.01,
    "weird_control_ratio": 0.01,
    "max_char_run": 15,
    "repeated_4gram_ratio": 0.60,      # with >= 24 words
    "distinct_word_ratio": 0.20,       # with >= 25 words
    "char_entropy": 2.2,               # with >= 60 chars
    "punct_symbol_ratio": 0.55,        # with code stripped
    "alpha_ratio": 0.30,               # with code stripped
    "cyrillic_ratio": 0.10,            # with >= 40 letters
    "short_word_ratio": 0.70,          # with >= 20 words
    "hyphen_chain_ratio": 0.50,
    "alnum_mixed_word_ratio": 0.30,    # with >= 20 words
}

# Sane: ALL of these must hold.
#
# min_cyrillic_ratio is deliberately well below 1.0: the `ru_en` and `ru_json_code`
# categories ASK for English technical terms, so a healthy answer such as
# "Второй full quality run в процессе; timing и incident metrics собираются"
# legitimately sits near 0.50 Cyrillic. An English-only or Chinese-only answer still
# falls far below the threshold.
SANE = {
    "min_chars": 60,
    "min_prose_letters": 40,
    "max_char_run": 8,
    "min_distinct_word_ratio": 0.45,
    "max_repeated_4gram_ratio": 0.25,
    "min_char_entropy": 3.2,
    "max_punct_symbol_ratio": 0.35,
    "min_alpha_ratio": 0.45,
    "min_cyrillic_ratio": 0.35,
    "min_mean_word_len": 2.0,
    "max_mean_word_len": 14.0,
    "max_garbage_score": 0.25,
    # word-shape signals: lexically diverse Cyrillic nonsense
    # ("ар-ад-прелиест-нап-на-нау-на eBay-2-22_") passes every ratio above, because it is
    # made of many distinct short fragments glued with hyphens/underscores. These three
    # catch it without touching normal prose.
    "max_short_word_ratio": 0.45,
    "max_hyphen_chain_ratio": 0.18,
    "max_alnum_mixed_word_ratio": 0.15,
    "max_no_vowel_word_ratio": 0.18,
}

RU_EN_VOWELS = set("аеёиоуыэюяaeiouy")
# a run of >= 3 fragments joined by hyphens or underscores, e.g. "прел-прел-прегль"
HYPHEN_CHAIN_RE = re.compile(r"\w+(?:[-_]\w+){2,}", re.UNICODE)


def _entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _max_run(text: str) -> int:
    best = run = 0
    prev = None
    for ch in text:
        run = run + 1 if ch == prev else 1
        prev = ch
        best = max(best, run)
    return best


def _repeated_ngram_ratio(words: list[str], n: int = 4) -> float:
    if len(words) < n + 1:
        return 0.0
    grams = [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]
    return 1.0 - len(set(grams)) / len(grams)


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def signals(response: str) -> dict:
    text = response or ""
    n_chars = len(text)

    stripped = FENCE_RE.sub(" ", text)
    stripped = INLINE_CODE_RE.sub(" ", stripped)
    prose = JSON_BLOCK_RE.sub(" ", stripped)
    code_char_ratio = 1.0 - (len(prose.strip()) / n_chars) if n_chars else 0.0

    nonspace = [c for c in prose if not c.isspace()]
    n_nonspace = len(nonspace)
    letters = [c for c in prose if c.isalpha()]
    n_letters = len(letters)

    weird = sum(
        1 for c in text
        if unicodedata.category(c) in ("Cc", "Cf", "Co", "Cs") and c not in "\n\t\r"
    )
    punct_symbol = sum(1 for c in nonspace if unicodedata.category(c)[0] in "PS")
    digits = sum(1 for c in nonspace if c.isdigit())
    md_noise = sum(1 for c in nonspace if c in MARKDOWN_NOISE)

    words = WORD_RE.findall(prose)
    n_words = len(words)
    lowered = [w.lower() for w in words]

    short_words = sum(1 for w in words if len(w) <= 2)
    alnum_mixed = sum(1 for w in words if any(c.isdigit() for c in w) and any(c.isalpha() for c in w))
    alpha_words = [w for w in lowered if w.isalpha()]
    no_vowel = sum(1 for w in alpha_words if len(w) >= 3 and not (set(w) & RU_EN_VOWELS))
    hyphen_chain_chars = sum(len(m.group()) for m in HYPHEN_CHAIN_RE.finditer(prose))

    return {
        "n_chars": n_chars,
        "code_char_ratio": round(code_char_ratio, 4),
        "prose_chars": len(prose.strip()),
        "prose_letters": n_letters,
        "n_words": n_words,
        "replacement_ratio": round(text.count("�") / n_chars, 5) if n_chars else 0.0,
        "weird_control_ratio": round(weird / n_chars, 5) if n_chars else 0.0,
        "punct_symbol_ratio": round(punct_symbol / n_nonspace, 4) if n_nonspace else 0.0,
        "markdown_noise_ratio": round(md_noise / n_nonspace, 4) if n_nonspace else 0.0,
        "digit_ratio": round(digits / n_nonspace, 4) if n_nonspace else 0.0,
        "alpha_ratio": round(n_letters / n_nonspace, 4) if n_nonspace else 0.0,
        "cyrillic_ratio": round(len(CYRILLIC_RE.findall(prose)) / n_letters, 4) if n_letters else 0.0,
        "latin_ratio": round(len(LATIN_RE.findall(prose)) / n_letters, 4) if n_letters else 0.0,
        "max_char_run": _max_run(text),
        "distinct_word_ratio": round(len(set(lowered)) / n_words, 4) if n_words else 0.0,
        "repeated_4gram_ratio": round(_repeated_ngram_ratio(lowered), 4),
        "char_entropy": round(_entropy(text), 4),
        "mean_word_len": round(sum(len(w) for w in words) / n_words, 3) if n_words else 0.0,
        "short_word_ratio": round(short_words / n_words, 4) if n_words else 0.0,
        "alnum_mixed_word_ratio": round(alnum_mixed / n_words, 4) if n_words else 0.0,
        "no_vowel_word_ratio": round(no_vowel / len(alpha_words), 4) if alpha_words else 0.0,
        "hyphen_chain_ratio": round(hyphen_chain_chars / len(prose.strip()), 4) if prose.strip() else 0.0,
    }


def garbage_score(s: dict) -> tuple[float, dict]:
    """Transparent 0..1 garbage score: the mean of individually clipped penalties."""
    components = {
        "replacement": _clip01(s["replacement_ratio"] * 10),
        "control_chars": _clip01(s["weird_control_ratio"] * 10),
        "punct_density": _clip01((s["punct_symbol_ratio"] - 0.30) / 0.40),
        "low_alpha": _clip01((0.60 - s["alpha_ratio"]) / 0.45),
        "low_cyrillic": _clip01((0.75 - s["cyrillic_ratio"]) / 0.60),
        "word_variety": _clip01((0.55 - s["distinct_word_ratio"]) / 0.45),
        "ngram_repetition": _clip01((s["repeated_4gram_ratio"] - 0.20) / 0.50),
        "low_entropy": _clip01((3.6 - s["char_entropy"]) / 1.6),
        "char_runs": _clip01((s["max_char_run"] - 6) / 12),
        "short_words": _clip01((s["short_word_ratio"] - 0.35) / 0.35),
        "hyphen_chains": _clip01((s["hyphen_chain_ratio"] - 0.10) / 0.30),
        "alnum_mixed_words": _clip01((s["alnum_mixed_word_ratio"] - 0.03) / 0.20),
        "no_vowel_words": _clip01((s["no_vowel_word_ratio"] - 0.12) / 0.25),
    }
    score = sum(components.values()) / len(components)
    return round(score, 4), {k: round(v, 3) for k, v in components.items()}


def assess(response: str) -> dict:
    """Full assessment. Returns verdict in {sane, uncertain, collapsed} plus evidence."""
    s = signals(response)
    score, components = garbage_score(s)

    collapse_reasons: list[str] = []
    if s["replacement_ratio"] > HARD["replacement_ratio"]:
        collapse_reasons.append(f"replacement_ratio={s['replacement_ratio']} > {HARD['replacement_ratio']}")
    if s["weird_control_ratio"] > HARD["weird_control_ratio"]:
        collapse_reasons.append(f"weird_control_ratio={s['weird_control_ratio']} > {HARD['weird_control_ratio']}")
    if s["max_char_run"] >= HARD["max_char_run"]:
        collapse_reasons.append(f"max_char_run={s['max_char_run']} >= {HARD['max_char_run']}")
    if s["n_words"] >= 24 and s["repeated_4gram_ratio"] >= HARD["repeated_4gram_ratio"]:
        collapse_reasons.append(f"repeated_4gram_ratio={s['repeated_4gram_ratio']} >= {HARD['repeated_4gram_ratio']}")
    if s["n_words"] >= 25 and s["distinct_word_ratio"] < HARD["distinct_word_ratio"]:
        collapse_reasons.append(f"distinct_word_ratio={s['distinct_word_ratio']} < {HARD['distinct_word_ratio']}")
    if s["n_chars"] >= 60 and s["char_entropy"] < HARD["char_entropy"]:
        collapse_reasons.append(f"char_entropy={s['char_entropy']} < {HARD['char_entropy']}")
    if s["code_char_ratio"] < 0.30 and s["punct_symbol_ratio"] > HARD["punct_symbol_ratio"]:
        collapse_reasons.append(f"punct_symbol_ratio={s['punct_symbol_ratio']} > {HARD['punct_symbol_ratio']}")
    if s["code_char_ratio"] < 0.30 and s["prose_chars"] >= 40 and s["alpha_ratio"] < HARD["alpha_ratio"]:
        collapse_reasons.append(f"alpha_ratio={s['alpha_ratio']} < {HARD['alpha_ratio']}")
    if s["n_words"] >= 20 and s["short_word_ratio"] > HARD["short_word_ratio"]:
        collapse_reasons.append(f"short_word_ratio={s['short_word_ratio']} > {HARD['short_word_ratio']}")
    if s["hyphen_chain_ratio"] > HARD["hyphen_chain_ratio"]:
        collapse_reasons.append(f"hyphen_chain_ratio={s['hyphen_chain_ratio']} > {HARD['hyphen_chain_ratio']}")
    if s["n_words"] >= 20 and s["alnum_mixed_word_ratio"] > HARD["alnum_mixed_word_ratio"]:
        collapse_reasons.append(
            f"alnum_mixed_word_ratio={s['alnum_mixed_word_ratio']} > {HARD['alnum_mixed_word_ratio']}")

    # Answering in the wrong language is a compliance failure, not a collapse. Keep the
    # two apart so `collapsed` keeps meaning "the output is rubble"; such a response still
    # fails the Cyrillic requirement below and therefore never lands in `sane`.
    wrong_language = (
        s["prose_letters"] >= 40
        and s["cyrillic_ratio"] < HARD["cyrillic_ratio"]
        and not collapse_reasons
    )

    if collapse_reasons:
        verdict, reasons = "collapsed", collapse_reasons
    else:
        fails: list[str] = []
        if s["n_chars"] < SANE["min_chars"]:
            fails.append(f"too short to judge (n_chars={s['n_chars']} < {SANE['min_chars']})")
        if s["prose_letters"] < SANE["min_prose_letters"]:
            fails.append(f"too little prose to judge (prose_letters={s['prose_letters']})")
        if s["max_char_run"] > SANE["max_char_run"]:
            fails.append(f"max_char_run={s['max_char_run']}")
        if s["n_words"] >= 12 and s["distinct_word_ratio"] < SANE["min_distinct_word_ratio"]:
            fails.append(f"distinct_word_ratio={s['distinct_word_ratio']}")
        if s["repeated_4gram_ratio"] > SANE["max_repeated_4gram_ratio"]:
            fails.append(f"repeated_4gram_ratio={s['repeated_4gram_ratio']}")
        if s["char_entropy"] < SANE["min_char_entropy"]:
            fails.append(f"char_entropy={s['char_entropy']}")
        if s["punct_symbol_ratio"] > SANE["max_punct_symbol_ratio"]:
            fails.append(f"punct_symbol_ratio={s['punct_symbol_ratio']}")
        if s["alpha_ratio"] < SANE["min_alpha_ratio"]:
            fails.append(f"alpha_ratio={s['alpha_ratio']}")
        if s["cyrillic_ratio"] < SANE["min_cyrillic_ratio"]:
            fails.append(f"cyrillic_ratio={s['cyrillic_ratio']}")
        if not (SANE["min_mean_word_len"] <= s["mean_word_len"] <= SANE["max_mean_word_len"]):
            fails.append(f"mean_word_len={s['mean_word_len']}")
        if s["short_word_ratio"] > SANE["max_short_word_ratio"]:
            fails.append(f"short_word_ratio={s['short_word_ratio']}")
        if s["hyphen_chain_ratio"] > SANE["max_hyphen_chain_ratio"]:
            fails.append(f"hyphen_chain_ratio={s['hyphen_chain_ratio']}")
        if s["alnum_mixed_word_ratio"] > SANE["max_alnum_mixed_word_ratio"]:
            fails.append(f"alnum_mixed_word_ratio={s['alnum_mixed_word_ratio']}")
        if s["no_vowel_word_ratio"] > SANE["max_no_vowel_word_ratio"]:
            fails.append(f"no_vowel_word_ratio={s['no_vowel_word_ratio']}")
        if score > SANE["max_garbage_score"]:
            fails.append(f"garbage_score={score}")
        verdict = "sane" if not fails else "uncertain"
        reasons = fails

    return {
        "sanity_verdict": verdict,
        "likely_global_collapse": verdict == "collapsed",
        "wrong_output_language": wrong_language,
        "garbage_score": score,
        "garbage_components": components,
        "sanity_reasons": reasons,
        "sanity_signals": s,
    }


if __name__ == "__main__":  # tiny self-check
    import json as _json
    samples = {
        "normal_ru": "Второй полный прогон выполняется; итоговый отчёт будет включать замеры "
                     "времени и статистику инцидентов по всем режимам работы сервиса.",
        "normal_ru_with_han": "Второй 第二个 полный прогон выполняется; итоговый отчёт будет включать "
                              "замеры времени и статистику инцидентов по всем режимам работы.",
        "collapsed_repeat": "не не не не не не не не не не не не не не не не не не не не не не не не не "
                            "не не не не не не не не",
        "collapsed_garbage": "___ ___ 不吃 |||| ### ___ ~~~~ {{{{ }}}} ____ **** ---- ____ ++++ ____ ||||",
        "short": "Готово.",
    }
    for name, text in samples.items():
        a = assess(text)
        print(f"{name:<22} {a['sanity_verdict']:<10} garbage={a['garbage_score']:<7} {a['sanity_reasons'][:2]}")
    print(_json.dumps(assess(samples["normal_ru"])["sanity_signals"], indent=2, ensure_ascii=False)[:400])
