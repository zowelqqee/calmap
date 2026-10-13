# quant-language-leakage

Local, reproducible experiment on a MacBook Air M1 / 8 GB: **does low-bit quantization
increase the probability of unintended Chinese/CJK intrusions in Russian answers**,
especially when the prompt mixes Russian with English technical terms, JSON and code?

### Hypothesis under test (not an assumption)

> Low-bit quantization may preserve coarse semantic representations while reducing the
> margin that keeps lexical realizations separated by language. In multilingual /
> code-switched contexts this could increase unintended foreign-script token selection
> without destroying semantic coherence.

The motivating observation was an output of the form:

> «第二个 full quality run 正в процессе; это нужно только для того, чтобы итоговый JSON
> включал timing и incident metrics для всех режимов…»

The Chinese fragments are *semantically correct* for the surrounding Russian
(`第二个` ≈ «второй», `正` ≈ «как раз / сейчас»), which is what makes this failure mode
interesting: the semantics survive, the surface language does not.

**Nothing in this repository claims that quantization causes occurrence-level leakage —
the data collected so far says the opposite for that specific signal.** `analyze.py`
refuses to dress up small event counts as significance and says so explicitly in its
report. See "Current status and results" below for what has actually been run and found;
short version: occurrence-level Han leakage was essentially never observed at any tested
precision, but a logit-level language-selection margin does shrink and go negative at low
precision — inside models whose generation output was also already collapsing, so the two
effects were not cleanly separated in this run.

### Mixed-precision variants: what MLX actually does

`mlx_lm.convert --quant-predicate` ships four recipes. Read out of the installed
`mlx_lm/convert.py` (`mixed_quant_predicate_builder`), all four share one structure:

```
use_more_bits(layer) = layer < L/8  or  layer >= 7L/8  or  (layer - L/8) % 3 == 2
    v_proj  in such a layer -> high_bits
    down_proj in such a layer -> high_bits
    lm_head (any layer)       -> high_bits
    everything else           -> low_bits
```

with `(low, high)` = `(2,6)`, `(3,4)`, `(3,6)`, `(4,6)`. It is the llama.cpp Q4_K_M-style
heuristic. For Qwen3-4B (L=36) `use_more_bits` is true for 18 of 36 layers:
`0-3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 31-35`.

Two consequences specific to this model, both verified rather than assumed:

* **`tie_word_embeddings=true`, so there is no `lm_head` module at all.** The recipe's
  `lm_head -> high_bits` rule can never fire, and the tied `embed_tokens` — which *is*
  the output head, 389M params, 9.7% of the model — falls through to `low_bits`.
  Under `mixed_2_6` the output head is therefore 2-bit.
* **Only `mixed_2_6` lands between q3 and q2.** `mixed_3_4` -> 3.62, `mixed_3_6` -> 3.87,
  `mixed_4_6` -> higher; all sit *above* uniform q3 (3.501) and are useless for probing
  the region below it.

`inspect_quant_plan.py` computes any of this before a conversion is spent:

```bash
python inspect_quant_plan.py --ref models/qwen3-4b-instruct-2507-q2 --recipe mixed_2_6
```

`quantize_mixed.py` builds a variant, measures it (disk size, MLX-reported effective
bits/weight, per-bit parameter split, group size, predicate) and registers it in
`models/config.json` automatically:

```bash
python quantize_mixed.py --recipe mixed_2_6                 # stock recipe
python quantize_mixed.py --recipe mixed_2_6 --embed-bits 6  # + higher-precision output head
python quantize_mixed.py --recipe mixed_3_2                 # local scheme, see below
```

`mixed_3_2` is the one local scheme: a 3-bit floor (identical to uniform q3) except
`gate_proj`/`up_proj` inside the layers **MLX's own recipe** classifies as
low-sensitivity, which drop to 2-bit. The layer classification is queried from
`mixed_quant_predicate_builder` rather than re-derived.

### Current status and results

Variants measured so far, all converted from the same upstream bf16 checkpoint with
`group_size=64`, `q_mode=affine`. Effective bits/weight is what `mlx_lm` itself reports
(`compute_bits_per_weight`); the +0.5 over the nominal width is the fp16 scale+bias stored
per group of 64.

| variant | scheme | eff. bits/w | size | 2-bit share of weights | benchmark | sane share |
|---|---|---|---|---|---|---|
| `q8` | uniform 8-bit **(baseline)** | 8.500 | 4.0 GB | 0% | 400/400 | 99.0% |
| `q3` | uniform 3-bit | 3.501 | 1.6 GB | 0% | 400/400 | 97.5% |
| `mixed_3_2` | gate+up @ 2-bit, 18 low-sensitivity layers | 3.278 | 1.55 GiB | 22.3% | 249/400 | 85.9% |
| `mixed_3_2_gud` | + `down_proj` in the same 18 layers | 3.166 | 1.49 GiB | 33.4% | 64 (smoke) | 79.7% |
| `mixed_3_2_gudvk` | + `v_proj`,`k_proj` in the same 18 layers | 3.143 | 1.48 GiB | 35.8% | 64 (smoke) | 65.6% |
| `mixed_3_2_gudqo` | + `q_proj`,`o_proj` in the same 18 layers | 3.072 | 1.45 GiB | 42.8% | 43 (smoke) | 20.9% — **transition** |
| `mixed_3_2_all` | gate+up @ 2-bit, but in *every* layer | 3.055 | 1.44 GiB | 44.6% | 36 (smoke) | 0% — **collapsed** |
| `mixed_2_6` | stock MLX recipe | 2.993 | 1.41 GiB | 87.7% | 32 (smoke) | 0% — collapsed |
| `q2` | uniform 2-bit | 2.501 | 1.2 GB | 100% | 94 (partial) | 0% — collapsed |

The five `mixed_3_2*` rows are a deliberate bisection: starting from the healthy
`mixed_3_2` point and the collapsed `mixed_3_2_all` point, each step adds one more module
pair to the 2-bit set **within the same 18 MLX-classified low-sensitivity layers** (never
widening the layer scope — that's what `mixed_3_2_all` tests separately), pushing
effective bits down by ~0.02-0.11 per step.

Two structural points, both load-bearing for how to read the results below:

1. **Average bits/weight does not predict collapse; the *pattern* of which weights sit at
   2-bit does.** `mixed_3_2` (22.3% of weights at 2-bit, confined to `gate_proj`/`up_proj`
   in MLX's own "low-sensitivity" layers) is 86% sane at 3.28 eff. bits. `mixed_3_2_all`
   (44.6% at 2-bit — same modules, but *every* layer) is fully collapsed at 3.05 eff. bits,
   a precision *higher* than uniform q3 (3.50) would suggest is dangerous by bit-count
   alone. `mixed_2_6` collapses at 2.99 bits by putting 87.7% of weights — including the
   tied output head, since `tie_word_embeddings=true` means the recipe's `lm_head` rule
   never fires — at 2-bit.
2. **The collapse is gradual and sits inside a narrow band, not a cliff at one point.**
   Sane share falls 86% → 80% → 66% → **21%** → 0% across
   3.278 → 3.166 → 3.143 → 3.072 → 3.055 eff. bits/weight — a real transition zone
   (`mixed_3_2_gudqo`, 3.072 bits) exists between "mostly healthy" and "fully collapsed,"
   not just a boundary between two states.

### Occurrence-level Han leakage: essentially absent in every variant that still answers

Across **1,382 responses over 9 variants**, only **2 responses contained a Han
character at all** — one in `mixed_2_6` (`uncertain`, garbage-adjacent), one in `q2`
(`collapsed`). **Zero Han characters appeared in any `sane` response, in any variant,
including every point on the bisection** (`mixed_3_2` through `mixed_3_2_gudqo`, 316 sane
responses combined; `q3`, 390; `q8`, 396). The Cochran-Armitage trend test over all
responses is not significant (z = -1.29, p = 0.196), and with only 2 total events the
report itself flags the analysis as underpowered — correctly, since 2 events cannot
establish a trend either way.

This null result matters for interpreting the motivating example
(`第二个 ... 正в процессе ...`): it does **not** replicate at any precision level tested
here as a *sampling-frequency* phenomenon in 100-token answers. Either it needs longer
generations, a different prompt distribution, more samples per cell than the 3 seeds used
here, or it is intrinsically much rarer than intuition from one anecdote suggests.

### Logit-level language margin: flat across the entire alive→collapsed bisection

The occurrence detector asks "did leakage happen in a sample"; the margin probe asks
"how much probability mass would it take." Sequence log-probability margin between the
Russian and the (tokenization-correct, multi-token-aware) Chinese realization of the same
concept, averaged over 7 probes, mean/median/min in nats (positive = Russian preferred):

| variant | eff. bits/w | sane share | mean margin | median margin | min margin | probes negative |
|---|---|---|---|---|---|---|
| `q8` | 8.500 | 99.0% | +8.58 | +8.50 | +6.06 | 0 / 7 |
| `q3` | 3.501 | 97.5% | +9.19 | +9.50 | +6.28 | 0 / 7 |
| `mixed_3_2` | 3.278 | 85.9% | +8.14 | +8.09 | +5.12 | 0 / 7 |
| `mixed_3_2_gud` | 3.166 | 79.7% | +8.93 | +9.36 | +0.65 | 0 / 7 |
| `mixed_3_2_gudvk` | 3.143 | 65.6% | +8.12 | +7.90 | +5.28 | 0 / 7 |
| `mixed_3_2_gudqo` | 3.072 | **20.9%** | **+9.70** | +10.56 | +5.57 | 0 / 7 |
| `mixed_3_2_all` | 3.055 | 0% | +6.09 | +6.83 | -0.50 | 1 / 7 |
| `mixed_2_6` | 2.993 | 0% | +0.96 | -0.05 | -12.32 | 4 / 7 |
| `q2` | 2.500 | 0% | +1.45 | +2.28 | -13.00 | 2 / 7 |

Full per-probe matrix in [`results/analysis/logit_margin_matrix.csv`](results/analysis/logit_margin_matrix.csv).

This is the actual finding of the bisection, and it is a clean null result for the
fine-grained hypothesis, not a confirmation of it:

* **The margin does not track the sanity collapse at all through the transition zone.**
  Sane share falls from 86% to 21% across `mixed_3_2` → `mixed_3_2_gudqo`
  (3.278 → 3.072 eff. bits) — a real, steep degradation in generation quality — while the
  mean RU-ZH margin stays in the +8 to +9.7 range throughout, with **zero negative probes
  anywhere in that range**. At `mixed_3_2_gudqo`, where four in five generated responses
  are already incoherent or repetitive garbage, the forced-decision-point margin is
  actually the *highest* of the whole bisection (+9.70).
* **The margin only degrades at the one point where generation is already 100% collapsed**
  (`mixed_3_2_all`, 3.055 bits, 0% sane) and further below. Even there it's mild (mean
  +6.09, one probe out of seven dips to -0.50). It only becomes consistently unstable
  (multiple negative probes, magnitude to -13) at `mixed_2_6` and `q2`, both already fully
  collapsed on generation.
* Read together: **within this quantization scheme, there is no bit-width region where
  the language-selection margin narrows ahead of general semantic competence.** They don't
  even move together loosely — sanity degrades gradually and substantially (86%→80%→66%→
  21%→0%) while the margin stays flat until sanity has already hit exactly 0%. The
  fine-grained version of the hypothesis (a language-selection-specific margin that erodes
  *before* general coherence does, producing coherent Russian with an isolated
  semantically-correct Chinese substitution) is **not supported by this bisection** — five
  points spanning the entire alive-to-collapsed range found no such intermediate state.

**What this does and does not rule out.** It rules out the mechanism operating at *this*
single forced decision point, under *this* quantization scheme (uniform-affine, module-
and-layer-selective 2/3-bit mixing), on *this* model. It does not rule out the mechanism
existing under different quantization approaches (calibration-aware methods like
`mlx_lm.dwq`/`awq`/`gptq` compress information differently than round-to-nearest affine
quantization), at a different point in a 100+-token generation where local context has
drifted, or for token choices further from the specific five concepts probed here. The
motivating anecdote's failure mode was not reproduced or explained by this sweep — that is
worth taking at face value rather than explaining away.

### Where to push next

* **Different quantization approach, not more bisection.** Five points across the entire
  alive→collapsed range showed a flat margin; further bisection inside this scheme has
  strongly diminishing returns. Calibration-aware quantization (`mlx_lm.dwq`) compresses
  based on what actually matters for the model's outputs on a calibration set, rather than
  round-to-nearest per block — a fundamentally different compression mechanism that could
  plausibly separate language-margin loss from general coherence loss where affine RTN did
  not.
* **Longer generations and different decision points.** The benchmark caps
  `max_tokens=160`, and the probe measures one forced decision per concept. The motivating
  anecdote's leakage happened well into a longer, more heavily code-switched span of text —
  the margin may behave differently at token 200 with more code-switched context already
  in the KV cache than at a clean sentence-initial position.
* **The `mixed_3_2_gudqo` transition zone (20.9% sane) is itself worth a full 400-run
  benchmark**, not just a 43-response smoke: it is the one point in this whole sweep where
  the model is neither clearly healthy nor clearly collapsed, so it's the best place to
  look for genuinely intermediate, partially-coherent failure modes (including but not
  limited to language leakage) rather than clean pass/fail.

### Files

```
README.md              this file
requirements.txt       mlx-lm pin; analysis is stdlib-only
generate_prompts.py    builds prompts.jsonl (4 categories, validated, reproducible)
prompts.jsonl          100 benchmark prompts
quantize_models.sh     one upstream checkpoint -> uniform q8/q6/q4/q3/q2 via mlx_lm.convert
inspect_quant_plan.py  what a recipe does to THIS model, before spending a conversion
quantize_mixed.py      build + measure + auto-register a mixed-precision variant
models/config.json     variant registry used by run_benchmark.py and logit_probe.py
run_benchmark.py       generation loop (resumable, one model in memory at a time)
sanity.py              semantic-collapse detector (sane / uncertain / collapsed)
analyze.py             leakage detector + sanity split + Wilson / Fisher / Cochran-Armitage
logit_probe.py         sequence-level ru/en/zh language-margin probe
logit_report.py        summarises the margin probe across variants
results/               raw.jsonl, intrusions*.jsonl, logit_probe.jsonl, analysis/
```

---

## 1. Model choice

**`Qwen/Qwen3-4B-Instruct-2507`**, converted locally to several bit widths from the
*same* upstream bf16 checkpoint.

Why this one:

| criterion | reasoning |
|---|---|
| multilingual, strong ru/en/zh | Qwen3 is trained heavily on Chinese *and* Russian, so both lexical spaces genuinely compete — that competition is the object of study. A model with weak Chinese would trivially never leak. |
| size | 4.0B params (3.6B non-embedding). At 8-bit that is ~4.3 GB of weights, which fits in 8 GB unified memory with room for the OS and a 2048-token KV cache. |
| non-thinking | `Qwen3-4B-Instruct-2507` emits no `<think>` blocks, so `max_tokens` maps directly to answer length and runs stay short. |
| MLX support | Qwen3 is a first-class architecture in `mlx-lm`; conversion and quantization work with the stock `mlx_lm.convert`. |
| one checkpoint, many precisions | every variant is produced by `mlx_lm.convert` from this single repo, so architecture, tokenizer and training data are held constant and **bit width is the only variable**. |

Alternatives considered: `Qwen2.5-3B-Instruct` (smaller, would allow a true bf16 baseline
at ~6.2 GB — but 6.2 GB of weights on an 8 GB machine means swap, and its multilingual
quality is meaningfully lower); Gemma-3-4B (multilingual but weaker Chinese, and a
different tokenizer story); anything ≥7B (does not fit).

### No bf16/fp16 baseline — deliberate

4.02B × 2 bytes ≈ **8.1 GB** of weights alone, on a machine with 8 GB of *total* unified
memory. That is guaranteed swap thrashing, which would also contaminate the latency
numbers. **The 8-bit variant is the highest-precision baseline in this study** and every
comparison is made against it. This is a documented limitation, not an oversight: an
effect measured against an 8-bit baseline is a *lower bound* on the effect against bf16.

### What MLX actually supports (verified against `mlx 0.32.0` / `mlx-lm 0.31.3`)

* `--q-mode affine` (the default) supports **bits ∈ {2, 3, 4, 5, 6, 8}**. There is no
  7-bit. 2-bit exists but destroys a 4B model, so it is not part of the default sweep.
* Other modes exist and are *not* bit-width sweeps: `mxfp4`, `nvfp4` (4-bit float
  formats, fixed bit width), `mxfp8`.
* Mixed-bit recipes exist via `--quant-predicate {mixed_2_6, mixed_3_4, mixed_3_6, mixed_4_6}`.
  They are intentionally **not** used here: mixing bit widths per layer would add a second
  variable. Learned quantization (`mlx_lm.dwq`, `mlx_lm.awq`, `mlx_lm.gptq`) is likewise
  out of scope for the baseline experiment — see "calibration-aware quantization" below.
* `mlx-lm` quantizes uniformly and skips any layer whose last dimension is not divisible
  by `--q-group-size`; it prints the achieved bits-per-weight. Group size is fixed at 64
  for every variant.

### Footprint on this machine

| variant | bits | ~weights on disk / in RAM | fits in 8 GB? |
|---|---|---|---|
| (upstream bf16) | 16 | ~8.1 GB | no — not used |
| `q8` **baseline** | 8 | ~4.3 GB | yes |
| `q6` | 6 | ~3.3 GB | yes |
| `q4` | 4 | ~2.4 GB | yes |
| `q3` | 3 | ~1.9 GB | yes |

Plus ≲0.3 GB of KV cache at the 2048-token context cap. Models are loaded **one at a
time** and explicitly released (`del` + `gc.collect()` + `mx.clear_cache()`) before the
next variant.

**Disk:** the four variants total ~12 GB, and the upstream bf16 checkpoint occupies a
further ~8 GB in the HuggingFace cache during conversion. Have **~21 GB free** before
you start; `quantize_models.sh` prints free space and tells you how to reclaim the cache
afterwards.

---

## 2. Setup (macOS zsh, copy-paste)

The venv already exists — just activate it. To rebuild from scratch:

```bash
cd quant-language-leakage
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Python 3.11 is used deliberately: the system default here is 3.14, and the MLX /
transformers wheel matrix is not guaranteed for it.

Verify MLX sees the GPU:

```bash
python -c "import mlx.core as mx; print(mx.default_device()); import mlx_lm; print(mlx_lm.__version__)"
```

## 3. Download + convert + quantize (one source checkpoint → four variants)

```bash
source .venv/bin/activate
chmod +x quantize_models.sh
./quantize_models.sh
```

This downloads `Qwen/Qwen3-4B-Instruct-2507` once (~8 GB) and writes
`models/qwen3-4b-instruct-2507-q{8,6,4,3}`. It skips variants that already exist, so it
is safe to re-run. To build a subset:

```bash
./quantize_models.sh 4 3
```

Reclaim the upstream cache once every variant exists:

```bash
rm -rf ~/.cache/huggingface/hub/models--Qwen--Qwen3-4B-Instruct-2507
```

## 3b. Mixed-precision variants (between q3 and q2)

```bash
source .venv/bin/activate
# check what a recipe does to this model before spending a conversion on it
python inspect_quant_plan.py --ref models/qwen3-4b-instruct-2507-q2 --recipe mixed_2_6

# build it, measure it (disk size, MLX-reported effective bits/weight, per-bit param
# split), and auto-register it in models/config.json
python quantize_mixed.py --recipe mixed_2_6
python quantize_mixed.py --recipe mixed_3_2          # local scheme, see below
```

`--ref` just needs to be any already-converted variant of the same architecture (module
paths and shapes are identical across bit widths) — it does not need the 8 GB bf16
checkpoint. See "Mixed-precision variants: what MLX actually does" below for what the
four stock MLX recipes and the one local scheme (`mixed_3_2`) actually do to this model,
and "Current status and results" for what was found at each point.

## 4. Generate the prompt dataset

```bash
source .venv/bin/activate
python generate_prompts.py --out prompts.jsonl --n-per-category 25
```

100 prompts, 25 per category. `prompts.jsonl` is committed, so this step is only needed
if you want to change the size or the seed.

## 5. Smoke test (do this before the full run)

```bash
source .venv/bin/activate
python run_benchmark.py --smoke
python analyze.py --input results/smoke.jsonl --output-dir results/analysis_smoke --intrusions results/intrusions_smoke.jsonl
```

3 prompts × 2 variants × (1 greedy + 1 sampled) × 64 tokens — a couple of minutes,
enough to prove the pipeline end to end.

## 6. Full benchmark

```bash
source .venv/bin/activate
python run_benchmark.py \
  --models models/config.json \
  --prompts prompts.jsonl \
  --output results/raw.jsonl
```

Defaults: all four variants, 100 prompts, `deterministic` (greedy) + `sampling`
(temp 0.7 / top_p 0.95) with 3 fixed seeds, `max_tokens=160`.
→ **400 responses per variant, 1600 total.**

The run is **resumable**: it appends to `results/raw.jsonl` and skips
`(variant, prompt_id, mode, seed)` combinations already present. Interrupt with `Ctrl-C`
and re-run the identical command. It prints a live tok/s figure and an ETA after the
first prompts, so you can measure the actual cost instead of guessing it — if the ETA is
unacceptable, kill it and lower `--sampling-seeds` or `--max-prompts`.

Cheaper first pass:

```bash
python run_benchmark.py --max-prompts 10 --sampling-seeds 2 --output results/raw_quick.jsonl
```

More statistical power on the rare event (longer, run it overnight):

```bash
python run_benchmark.py --sampling-seeds 8 --output results/raw.jsonl
```

Since leakage is a rare stochastic event, **sampling mode is where the signal is**;
greedy decoding mainly serves as a fully deterministic control.

## 7. Analysis

```bash
source .venv/bin/activate
python analyze.py --input results/raw.jsonl --output-dir results/analysis
```

Writes `results/analysis/report.md`, three summary CSVs, `comparisons.csv`,
`annotated.jsonl`, and `results/intrusions.jsonl`.

```bash
cat results/analysis/report.md
```

## 8. Inspect contaminated outputs by hand

```bash
python -c "
import json
for r in map(json.loads, open('results/intrusions.jsonl', encoding='utf-8')):
    print(f\"[{r['quantization']}] {r['prompt_id']} {r['mode']} seed={r['seed']} han={r['han_char_count']}\")
    for s in r['segments']:
        print('   ', s['context'])
    print()
"
```

Or just:

```bash
wc -l results/intrusions.jsonl
```

Chinese fragments are **not** machine-translated anywhere in this project — the raw
material plus a ±60-character context window is kept for manual semantic analysis.

## 9. Language-selection margin probe (sequence-level, multi-token safe)

```bash
source .venv/bin/activate
python logit_probe.py --variants q8,q3,mixed_3_2,mixed_2_6,q2 --output results/logit_probe.jsonl
python logit_report.py --input results/logit_probe.jsonl --output-dir results/analysis
```

For each of 7 probes (concepts: второй/second/第二个, сейчас/now/现在, выполняется/running/运行,
завершён/finished/完成, ошибка/error/错误 — each in both a pure-Russian and a code-switched
context), the script builds the normal chat prompt, forces a Russian assistant prefix that
stops right before the target word, and scores every candidate as a full sequence:
`log P(candidate | context) = Σ log P(token_i | context, token_<i)`. Candidates are
tokenized first — a 4-token Russian word (`завершён` → `зав|ер|ш|ён`) is compared honestly
against a 1-token English one, never truncated to "first token only". `logit_report.py`
turns the raw JSONL into a per-probe margin matrix and a per-variant summary
(`results/analysis/logit_margin_matrix.csv`, `logit_margin_by_variant.csv`).

Variants not currently on disk can be converted on the fly and deleted again afterward —
useful for probing q8/q3 without keeping a permanent 4 GB copy around:

```bash
python logit_probe.py --variants q8,q3 --transient q8,q3 --output results/logit_probe.jsonl
```

`--transient` only ever deletes a directory it created in that same run. The script is
resumable: results already in `--output` for a `(variant, probe_id)` pair are kept, and
only missing pairs are computed, so probing variants one at a time across several
invocations is safe.

This is the more sensitive of the two signals in this repo — see "Logit-level language
margin" above for what it found. It is a diagnostic, not a replacement for the generation
benchmark: a shrinking margin only means something if it can be related to whether the
model is still producing coherent output, which is what `sanity.py` is for.

---

## Experimental controls

Held constant across every variant: prompt set, system prompt, chat template, tokenizer,
architecture, source checkpoint, seed list, `temperature`, `top_p`, `max_tokens`, context
cap, and decode loop. The only intended difference between runs is quantization bit width.

Two decoding modes:

* **deterministic** — `temp=0` (greedy, `make_sampler(temp=0.0)` → argmax). One run per
  prompt. Any difference here cannot be sampling noise.
* **sampling** — `temp=0.7`, `top_p=0.95`, seeds `1000, 1001, 1002` (`mx.random.seed()` is
  set immediately before each generation). Same seeds for every variant.

Caveat, stated honestly: identical seeds do **not** guarantee identical token sequences
across variants — different weights produce different distributions, so trajectories
diverge after the first differing sample regardless of the RNG. Seeding removes RNG-state
variance between variants, not trajectory divergence. That is why the comparison relies on
aggregate rates over 400 responses per variant rather than on paired per-response diffs.

## Output schema — `results/raw.jsonl`

```json
{
  "model": "Qwen/Qwen3-4B-Instruct-2507",
  "variant": "q4",
  "quantization": "affine-4bit-g64",
  "bits": 4,
  "model_path": "models/qwen3-4b-instruct-2507-q4",
  "prompt_id": "ru_en_json_long_007",
  "category": "ru_en_json_long",
  "mode": "sampling",
  "seed": 1001,
  "temperature": 0.7,
  "top_p": 0.95,
  "max_tokens": 160,
  "system_prompt": "...",
  "prompt": "...",
  "response": "...",
  "latency_sec": 12.34,
  "prompt_tokens": 210,
  "output_tokens": 155,
  "generation_tps": 12.6,
  "peak_memory_gb": 4.9,
  "finish_reason": "length",
  "timestamp": "2026-08-11T12:00:00+00:00"
}
```

## Prompt dataset

100 prompts, four categories × 25, all written as realistic engineering messages:

| category | content |
|---|---|
| `pure_ru` | fully Russian, **zero Latin characters** — the clean control |
| `ru_en` | Russian narrative + English technical terms (`backpressure`, `p95 latency`, …) |
| `ru_json_code` | Russian + JSON objects, Python snippets, config keys, identifiers |
| `ru_en_json_long` | all of the above, longer context (~360–590 characters) |

Enforced by `generate_prompts.py` and re-checked at generation time:

* every prompt contains an explicit "answer in Russian" instruction, phrased eight
  different ways so the model cannot key off one memorised construction;
* **no CJK / Kana / Hangul anywhere in any prompt** — otherwise the detector could not
  distinguish expected from unexpected Han characters;
* `pure_ru` additionally contains no Latin letters at all.

## Detector

Per response: `has_han`, `han_char_count`, `han_chars`, `positions`, contiguous
`han_segments` each with a ±60-character context window (intrusion marked `⟦…⟧`), plus
`has_hiragana`, `has_katakana`, `has_hangul` and a separate `cjk_punct_count`
(fullwidth/CJK punctuation is tracked but never counted as Han intrusion).

Han coverage: CJK Unified Ideographs `U+4E00–U+9FFF`, Extension A `U+3400–U+4DBF`,
Compatibility Ideographs `U+F900–U+FAFF` and Supplement `U+2F800–U+2FA1F`, Radicals
Supplement `U+2E80–U+2EFF`, Kangxi Radicals `U+2F00–U+2FDF`, the ideographic iteration
mark / number zero, and Extensions B–I in the astral planes.

A response is only counted as leakage when it contains Han characters **and** neither the
prompt nor the response is topically about Chinese/Japanese/Korean (`topical_cjk_context`).
No current prompt triggers that guard — it exists so the detector stays honest if the
prompt set is extended.

## Semantic-collapse detector (`sanity.py`)

At low bit widths the model stops producing Russian sentences and starts producing rubble.
A Han character inside rubble says nothing about language selection, so every response is
classified before any leakage statistic is computed:

* **`sane`** — a healthy Russian answer. Only these count as evidence about language
  selection.
* **`collapsed`** — rubble, by at least one extreme signal.
* **`uncertain`** — cannot be judged confidently: too short, almost entirely code, or
  mixed signals. Deliberately a real third state, never silently folded into `sane`.

Signals are all cheap character/word statistics — no LLM judge: replacement chars,
control/private-use chars, punctuation+symbol density, markdown/underscore noise, digit
and alphabetic density, Cyrillic share of letters, longest identical-character run,
distinct-word ratio, repeated word 4-grams, Shannon character entropy, mean word length,
length, plus four word-shape signals (share of 1–2 character words, letter+digit words,
vowel-less words, characters inside hyphen/underscore chains).

The word-shape group was added after the detector was checked against real outputs: the
first version called `ар-ад-прелиест-нап-на-нау-на eBay-2-22_ --прелогман-рис-илоры` *sane*,
because that text is lexically diverse, high-entropy, mostly Cyrillic and low on
punctuation. Conversely the Cyrillic threshold was relaxed from 0.60 to 0.35 because it
was flagging perfectly good `ru_en` answers such as *"Второй full quality run в процессе;
timing и incident metrics по всем режимам собираются"* — the category deliberately asks
for English terms.

Answering entirely in the wrong language is reported as `wrong_output_language`, not as a
collapse; it still never counts as `sane`.

Intrusions are written split by verdict — `results/intrusions_sane.jsonl`,
`_uncertain.jsonl`, `_collapsed.jsonl` — because that split, not the raw count, is the
thing the experiment turns on.

## Metrics and statistics

Per `quantization × category`, per `quantization × mode`, and aggregated per
`quantization`:

`total_responses`, `responses_with_han`, `intrusion_rate` with a **95 % Wilson interval**,
`total_han_chars`, `han_per_1000_output_chars`, `han_per_1000_output_tokens`,
`mean_han_chars_in_contaminated`, Hiragana/Katakana/Hangul response counts, mean+median
latency, mean output tokens and characters.

Comparisons: baseline (`q8`) vs each variant, overall and per category, with a two-sided
**Fisher exact test** (rare binary events) and a Haldane–Anscombe corrected odds ratio.
Across all four bit widths, a **Cochran–Armitage trend test** answers the actual research
question — *does the rate rise monotonically as bit width falls?*

**Anti-p-hacking guard rails, implemented in code:** if zero intrusions are observed, the
report states that no conclusion is possible in either direction and gives only the Wilson
upper bound; with fewer than 10 total events it labels the comparison underpowered and
tells you not to interpret the p-values; per-category tests are flagged as unadjusted for
multiple comparisons. Wilson intervals are what you should read first.

## Known limitations

* Baseline is 8-bit, not bf16 (memory). Effects measured are lower bounds.
* One model family. Whatever is found here is a statement about Qwen3-4B-Instruct-2507
  under MLX affine quantization, not about quantization in general.
* One machine, one MLX version. `mlx-lm` is pinned in `requirements.txt`; record the exact
  version if you report numbers.
* Context capped at 2048 tokens and `max_tokens` at 160; longer generations plausibly leak
  more, and this design would not see it.
* The upstream checkpoint is not pinned to a commit by default — set
  `REVISION=<sha> ./quantize_models.sh` if you need bit-exact reproducibility.
* `Qwen3-4B-Instruct-2507` emits no `<think>` blocks, so responses are answers only. If
  you swap in a reasoning model, pass `analyze.py --strip-think` to keep chain-of-thought
  text out of the detector — otherwise leakage inside reasoning and leakage inside the
  answer get pooled into one number.

---

## Stage 2 — remediation (nothing is fixed yet, by design)

If the data shows that semantics stay correct while the surface language occasionally
breaks, the interesting question becomes: *can the language-selection margin be restored
without raising the precision of the whole model?* Options to evaluate later:

1. **Explicit system-level language constraint** — a stronger, more specific
   language-lock system prompt. Cheapest possible intervention; measure it first as it is
   the honest control for everything below.
2. **Unicode/script-aware logit bias or masking** — `mlx-lm` accepts `logits_processors`
   in `generate`/`stream_generate`, so a processor can down-weight or hard-mask token ids
   whose decoded text contains Han/Kana/Hangul. Precompute the offending id set once from
   the tokenizer vocabulary. Needs care with code blocks and legitimate quoting.
3. **Resampling a suspicious foreign-script token** — detect at the sampling step, reject,
   and re-sample from the remaining distribution. Cheaper than masking everything, and it
   preserves the distribution shape where no leakage is happening.
4. **Lightweight output validator** — post-hoc detection (the detector in `analyze.py`
   already is one) plus a single constrained retry. No decode-loop surgery; the highest
   latency cost.
5. **Calibration-aware quantization** — `mlx_lm.dwq` / `mlx_lm.awq` / `mlx_lm.gptq` with a
   Russian + code-switched calibration set, tested against the same benchmark. Directly
   tests whether the effect is about *which* weights lose precision rather than how many bits.
6. **Language steering** — an activation-space direction for "output language = Russian",
   applied at inference. Most invasive, most interesting if the margin hypothesis holds.

The `logit_probe.py` margin measurement is the natural before/after metric for all six.
