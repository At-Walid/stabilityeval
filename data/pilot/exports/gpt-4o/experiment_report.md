# Experiment Report: icse_pilot_model2

## Summary

- **Date:** 2026-10-11
- **Status:** completed
- **Agents:** llm_baseline
- **Issues:** 20
- **Transformations:** paraphrase, verbosity_reduction, typo_injection, reordering, paragraph_to_structured, neutralize_emotional
- **Total runs:** 160
- **Total cost:** $0.7194

### Excluded from metrics A/F/G

- **Runs that did not complete normally** (timeout, cost cap, error): 3
- **Runs on quality-warning variants** (identifier retention failed after retries): 4
  - neutralize_emotional: 0
  - paragraph_to_structured: 1
  - paraphrase: 0
  - reordering: 0
  - typo_injection: 0
  - verbosity_reduction: 3
- **Runs on no-op variants** (identical to the original after whitespace normalization): 8
  - neutralize_emotional: 5
  - paragraph_to_structured: 0
  - paraphrase: 0
  - reordering: 1
  - typo_injection: 0
  - verbosity_reduction: 2

## RQ1 — Stability Results

| Scope | Success Consistency (A) | Stability Score (F) |
|-------|------------------------|---------------------|
| llm_baseline|astropy__astropy-12907 | 1.000 | 1.000 |
| llm_baseline|astropy__astropy-14365 | 1.000 | 1.000 |
| llm_baseline|astropy__astropy-7746 | 1.000 | 1.000 |
| llm_baseline|django__django-12708 | 1.000 | 1.000 |
| llm_baseline|django__django-15347 | 0.833 | 0.833 |
| llm_baseline|django__django-15814 | 1.000 | 1.000 |
| llm_baseline|matplotlib__matplotlib-23964 | 1.000 | 1.000 |
| llm_baseline|matplotlib__matplotlib-24970 | 1.000 | 1.000 |
| llm_baseline|mwaskom__seaborn-3010 | 1.000 | 1.000 |
| llm_baseline|mwaskom__seaborn-3190 | 1.000 | 1.000 |
| llm_baseline|psf__requests-2148 | 0.833 | 0.833 |
| llm_baseline|psf__requests-2317 | 1.000 | 1.000 |
| llm_baseline|pylint-dev__pylint-6506 | 0.333 | 0.333 |
| llm_baseline|pylint-dev__pylint-7993 | 1.000 | 1.000 |
| llm_baseline|pytest-dev__pytest-11143 | 1.000 | 1.000 |
| llm_baseline|pytest-dev__pytest-7373 | 1.000 | 1.000 |
| llm_baseline|scikit-learn__scikit-learn-14087 | 0.667 | 0.667 |
| llm_baseline|scikit-learn__scikit-learn-14983 | 1.000 | 1.000 |
| llm_baseline|sympy__sympy-20049 | 1.000 | 1.000 |
| llm_baseline|sympy__sympy-24102 | 1.000 | 1.000 |

**Mean Stability Score (llm_baseline):** 0.933

## RQ2 — Transformation Sensitivity

TS is a drop rate (success → failure counts +1, failure → success −1); the flip rate counts any change of outcome between the original and the variant.

| Agent | Transformation | Sensitivity (G) | Flip rate |
|-------|---------------|-----------------|-----------|
| llm_baseline | paragraph_to_structured | 0.056 | 0.056 |
| llm_baseline | typo_injection | 0.000 | 0.000 |
| llm_baseline | reordering | -0.056 | 0.056 |
| llm_baseline | verbosity_reduction | -0.067 | 0.067 |
| llm_baseline | neutralize_emotional | -0.133 | 0.133 |
| llm_baseline | paraphrase | -0.150 | 0.150 |

**Most disruptive transformation:** paragraph_to_structured (sensitivity = 0.056)

**Noise floor (llm_baseline):** control flip rate = 0.000 over 20 control run(s), re-runs of the unchanged original. A flip rate at or below it is indistinguishable from run-to-run variance.

## Issue-Level Results

| Issue | Transformation | Agent | Status | Outcome | File overlap (Jaccard) | Cost |
|-------|----------------|-------|--------|---------|------------------------|------|
| astropy__astropy-12907 | original | llm_baseline | success | success | 1.000 | $0.0037 |
| astropy__astropy-12907 | paraphrase | llm_baseline | success | success | 1.000 | $0.0044 |
| astropy__astropy-12907 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0038 |
| astropy__astropy-12907 | typo_injection | llm_baseline | success | success | 1.000 | $0.0037 |
| astropy__astropy-12907 | reordering | llm_baseline | success | success | 1.000 | $0.0035 |
| astropy__astropy-12907 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0037 |
| astropy__astropy-12907 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0036 |
| astropy__astropy-12907 | original (control) | llm_baseline | success | success | 1.000 | $0.0037 |
| astropy__astropy-14365 | original | llm_baseline | success | success | 1.000 | $0.0038 |
| astropy__astropy-14365 | paraphrase | llm_baseline | success | success | 1.000 | $0.0095 |
| astropy__astropy-14365 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0032 |
| astropy__astropy-14365 | typo_injection | llm_baseline | success | success | 1.000 | $0.0037 |
| astropy__astropy-14365 | reordering | llm_baseline | success | success | 1.000 | $0.0042 |
| astropy__astropy-14365 | paragraph_to_structured | llm_baseline | no_patch | excluded | N/A | $0.0425 |
| astropy__astropy-14365 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0038 |
| astropy__astropy-14365 | original (control) | llm_baseline | success | success | 1.000 | $0.0074 |
| astropy__astropy-7746 | original | llm_baseline | success | success | 1.000 | $0.0035 |
| astropy__astropy-7746 | paraphrase | llm_baseline | success | success | 1.000 | $0.0042 |
| astropy__astropy-7746 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0034 |
| astropy__astropy-7746 | typo_injection | llm_baseline | success | success | 1.000 | $0.0035 |
| astropy__astropy-7746 | reordering | llm_baseline | success | success | 1.000 | $0.0044 |
| astropy__astropy-7746 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0035 |
| astropy__astropy-7746 | neutralize_emotional | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| astropy__astropy-7746 | original (control) | llm_baseline | success | success | 1.000 | $0.0035 |
| django__django-12708 | original | llm_baseline | success | success | 1.000 | $0.0049 |
| django__django-12708 | paraphrase | llm_baseline | success | success | 1.000 | $0.0031 |
| django__django-12708 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0024 |
| django__django-12708 | typo_injection | llm_baseline | success | success | 1.000 | $0.0063 |
| django__django-12708 | reordering | llm_baseline | success | success | 1.000 | $0.0041 |
| django__django-12708 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0023 |
| django__django-12708 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0032 |
| django__django-12708 | original (control) | llm_baseline | success | success | 1.000 | $0.0033 |
| django__django-15347 | original | llm_baseline | success | success | 0.500 | $0.0044 |
| django__django-15347 | paraphrase | llm_baseline | success | success | 0.500 | $0.0042 |
| django__django-15347 | verbosity_reduction | llm_baseline | success | success | 0.500 | $0.0040 |
| django__django-15347 | typo_injection | llm_baseline | success | success | 0.500 | $0.0049 |
| django__django-15347 | reordering | llm_baseline | success | success | 0.500 | $0.0034 |
| django__django-15347 | paragraph_to_structured | llm_baseline | success | failure | 0.000 | $0.0040 |
| django__django-15347 | neutralize_emotional | llm_baseline | success | success | 0.500 | $0.0046 |
| django__django-15347 | original (control) | llm_baseline | success | success | 0.500 | $0.0044 |
| django__django-15814 | original | llm_baseline | success | success | 1.000 | $0.0034 |
| django__django-15814 | paraphrase | llm_baseline | success | success | 1.000 | $0.0033 |
| django__django-15814 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0033 |
| django__django-15814 | typo_injection | llm_baseline | success | success | 1.000 | $0.0033 |
| django__django-15814 | reordering | llm_baseline | no_patch | excluded | N/A | $0.0433 |
| django__django-15814 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0033 |
| django__django-15814 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0035 |
| django__django-15814 | original (control) | llm_baseline | success | success | 1.000 | $0.0035 |
| matplotlib__matplotlib-23964 | original | llm_baseline | success | success | 1.000 | $0.0050 |
| matplotlib__matplotlib-23964 | paraphrase | llm_baseline | success | success | 1.000 | $0.0055 |
| matplotlib__matplotlib-23964 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0053 |
| matplotlib__matplotlib-23964 | typo_injection | llm_baseline | success | success | 1.000 | $0.0049 |
| matplotlib__matplotlib-23964 | reordering | llm_baseline | success | success | 1.000 | $0.0050 |
| matplotlib__matplotlib-23964 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0047 |
| matplotlib__matplotlib-23964 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0053 |
| matplotlib__matplotlib-23964 | original (control) | llm_baseline | success | success | 1.000 | $0.0051 |
| matplotlib__matplotlib-24970 | original | llm_baseline | success | success | 1.000 | $0.0035 |
| matplotlib__matplotlib-24970 | paraphrase | llm_baseline | success | success | 1.000 | $0.0037 |
| matplotlib__matplotlib-24970 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0035 |
| matplotlib__matplotlib-24970 | typo_injection | llm_baseline | success | success | 1.000 | $0.0037 |
| matplotlib__matplotlib-24970 | reordering | llm_baseline | success | success | 1.000 | $0.0037 |
| matplotlib__matplotlib-24970 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0035 |
| matplotlib__matplotlib-24970 | neutralize_emotional | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| matplotlib__matplotlib-24970 | original (control) | llm_baseline | success | success | 1.000 | $0.0035 |
| mwaskom__seaborn-3010 | original | llm_baseline | success | success | 1.000 | $0.0047 |
| mwaskom__seaborn-3010 | paraphrase | llm_baseline | success | success | 1.000 | $0.0046 |
| mwaskom__seaborn-3010 | verbosity_reduction | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| mwaskom__seaborn-3010 | typo_injection | llm_baseline | success | success | 1.000 | $0.0046 |
| mwaskom__seaborn-3010 | reordering | llm_baseline | success | success | 1.000 | $0.0045 |
| mwaskom__seaborn-3010 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0049 |
| mwaskom__seaborn-3010 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0046 |
| mwaskom__seaborn-3010 | original (control) | llm_baseline | success | success | 1.000 | $0.0047 |
| mwaskom__seaborn-3190 | original | llm_baseline | success | success | 1.000 | $0.0032 |
| mwaskom__seaborn-3190 | paraphrase | llm_baseline | success | success | 1.000 | $0.0033 |
| mwaskom__seaborn-3190 | verbosity_reduction | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| mwaskom__seaborn-3190 | typo_injection | llm_baseline | success | success | 1.000 | $0.0032 |
| mwaskom__seaborn-3190 | reordering | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| mwaskom__seaborn-3190 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0033 |
| mwaskom__seaborn-3190 | neutralize_emotional | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| mwaskom__seaborn-3190 | original (control) | llm_baseline | success | success | 1.000 | $0.0032 |
| psf__requests-2148 | original | llm_baseline | success | failure | 0.000 | $0.0045 |
| psf__requests-2148 | paraphrase | llm_baseline | success | success | 0.500 | $0.0049 |
| psf__requests-2148 | verbosity_reduction | llm_baseline | success | failure | 0.000 | $0.0043 |
| psf__requests-2148 | typo_injection | llm_baseline | success | failure | 0.000 | $0.0051 |
| psf__requests-2148 | reordering | llm_baseline | success | failure | 0.000 | $0.0039 |
| psf__requests-2148 | paragraph_to_structured | llm_baseline | success | failure | 0.000 | $0.0045 |
| psf__requests-2148 | neutralize_emotional | llm_baseline | success | failure | 0.000 | $0.0043 |
| psf__requests-2148 | original (control) | llm_baseline | success | failure | 0.000 | $0.0050 |
| psf__requests-2317 | original | llm_baseline | success | success | 1.000 | $0.0021 |
| psf__requests-2317 | paraphrase | llm_baseline | success | success | 1.000 | $0.0021 |
| psf__requests-2317 | verbosity_reduction | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| psf__requests-2317 | typo_injection | llm_baseline | success | success | 1.000 | $0.0028 |
| psf__requests-2317 | reordering | llm_baseline | success | success | 1.000 | $0.0022 |
| psf__requests-2317 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0021 |
| psf__requests-2317 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0021 |
| psf__requests-2317 | original (control) | llm_baseline | success | success | 1.000 | $0.0026 |
| pylint-dev__pylint-6506 | original | llm_baseline | success | failure | 0.000 | $0.0030 |
| pylint-dev__pylint-6506 | paraphrase | llm_baseline | success | success | 1.000 | $0.0034 |
| pylint-dev__pylint-6506 | verbosity_reduction | llm_baseline | success | success | 0.500 | $0.0041 |
| pylint-dev__pylint-6506 | typo_injection | llm_baseline | success | failure | 0.000 | $0.0030 |
| pylint-dev__pylint-6506 | reordering | llm_baseline | success | success | 1.000 | $0.0036 |
| pylint-dev__pylint-6506 | paragraph_to_structured | llm_baseline | success | failure | 0.000 | $0.0031 |
| pylint-dev__pylint-6506 | neutralize_emotional | llm_baseline | success | success | 0.500 | $0.0050 |
| pylint-dev__pylint-6506 | original (control) | llm_baseline | success | failure | 0.000 | $0.0030 |
| pylint-dev__pylint-7993 | original | llm_baseline | success | success | 1.000 | $0.0032 |
| pylint-dev__pylint-7993 | paraphrase | llm_baseline | success | success | 1.000 | $0.0030 |
| pylint-dev__pylint-7993 | verbosity_reduction | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| pylint-dev__pylint-7993 | typo_injection | llm_baseline | no_patch | excluded | N/A | $0.0429 |
| pylint-dev__pylint-7993 | reordering | llm_baseline | success | success | 1.000 | $0.0038 |
| pylint-dev__pylint-7993 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0038 |
| pylint-dev__pylint-7993 | neutralize_emotional | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| pylint-dev__pylint-7993 | original (control) | llm_baseline | success | success | 1.000 | $0.0032 |
| pytest-dev__pytest-11143 | original | llm_baseline | success | success | 1.000 | $0.0064 |
| pytest-dev__pytest-11143 | paraphrase | llm_baseline | success | success | 1.000 | $0.0066 |
| pytest-dev__pytest-11143 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0062 |
| pytest-dev__pytest-11143 | typo_injection | llm_baseline | success | success | 1.000 | $0.0064 |
| pytest-dev__pytest-11143 | reordering | llm_baseline | success | success | 1.000 | $0.0063 |
| pytest-dev__pytest-11143 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0063 |
| pytest-dev__pytest-11143 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0064 |
| pytest-dev__pytest-11143 | original (control) | llm_baseline | success | success | 1.000 | $0.0064 |
| pytest-dev__pytest-7373 | original | llm_baseline | success | success | 1.000 | $0.0047 |
| pytest-dev__pytest-7373 | paraphrase | llm_baseline | success | success | 1.000 | $0.0052 |
| pytest-dev__pytest-7373 | verbosity_reduction | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| pytest-dev__pytest-7373 | typo_injection | llm_baseline | success | success | 1.000 | $0.0041 |
| pytest-dev__pytest-7373 | reordering | llm_baseline | success | success | 1.000 | $0.0052 |
| pytest-dev__pytest-7373 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0044 |
| pytest-dev__pytest-7373 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0071 |
| pytest-dev__pytest-7373 | original (control) | llm_baseline | success | success | 1.000 | $0.0038 |
| scikit-learn__scikit-learn-14087 | original | llm_baseline | success | failure | 0.000 | $0.0038 |
| scikit-learn__scikit-learn-14087 | paraphrase | llm_baseline | success | success | 1.000 | $0.0049 |
| scikit-learn__scikit-learn-14087 | verbosity_reduction | llm_baseline | success | failure | 0.000 | $0.0049 |
| scikit-learn__scikit-learn-14087 | typo_injection | llm_baseline | success | failure | 0.000 | $0.0045 |
| scikit-learn__scikit-learn-14087 | reordering | llm_baseline | success | failure | 0.000 | $0.0040 |
| scikit-learn__scikit-learn-14087 | paragraph_to_structured | llm_baseline | success | failure | 0.000 | $0.0046 |
| scikit-learn__scikit-learn-14087 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0048 |
| scikit-learn__scikit-learn-14087 | original (control) | llm_baseline | success | failure | 0.000 | $0.0038 |
| scikit-learn__scikit-learn-14983 | original | llm_baseline | success | success | 1.000 | $0.0041 |
| scikit-learn__scikit-learn-14983 | paraphrase | llm_baseline | success | success | 1.000 | $0.0043 |
| scikit-learn__scikit-learn-14983 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0044 |
| scikit-learn__scikit-learn-14983 | typo_injection | llm_baseline | success | success | 1.000 | $0.0043 |
| scikit-learn__scikit-learn-14983 | reordering | llm_baseline | success | success | 1.000 | $0.0047 |
| scikit-learn__scikit-learn-14983 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0045 |
| scikit-learn__scikit-learn-14983 | neutralize_emotional | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| scikit-learn__scikit-learn-14983 | original (control) | llm_baseline | success | success | 1.000 | $0.0047 |
| sympy__sympy-20049 | original | llm_baseline | success | success | 1.000 | $0.0036 |
| sympy__sympy-20049 | paraphrase | llm_baseline | success | success | 1.000 | $0.0036 |
| sympy__sympy-20049 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0032 |
| sympy__sympy-20049 | typo_injection | llm_baseline | success | success | 1.000 | $0.0033 |
| sympy__sympy-20049 | reordering | llm_baseline | success | success | 1.000 | $0.0036 |
| sympy__sympy-20049 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0032 |
| sympy__sympy-20049 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0033 |
| sympy__sympy-20049 | original (control) | llm_baseline | success | success | 1.000 | $0.0034 |
| sympy__sympy-24102 | original | llm_baseline | success | success | 1.000 | $0.0029 |
| sympy__sympy-24102 | paraphrase | llm_baseline | success | success | 1.000 | $0.0030 |
| sympy__sympy-24102 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0024 |
| sympy__sympy-24102 | typo_injection | llm_baseline | success | success | 1.000 | $0.0028 |
| sympy__sympy-24102 | reordering | llm_baseline | success | success | 1.000 | $0.0031 |
| sympy__sympy-24102 | paragraph_to_structured | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| sympy__sympy-24102 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0029 |
| sympy__sympy-24102 | original (control) | llm_baseline | success | success | 1.000 | $0.0035 |

## Variant Provenance

What produced each issue text the agents saw (SPEC section 11.6). Placeholders are offline stand-ins from mock / dry-run mode, never generated variants.

| Issue | Transformation | Generator | Transform version | Mode | No-op | Quality warning | Exclusion reason |
|-------|----------------|-----------|-------------------|------|-------|-----------------|------------------|
| astropy__astropy-12907 | neutralize_emotional | claude-haiku-4-5-20251001 | 3 | real | no | no |  |
| astropy__astropy-12907 | original | original | N/A | N/A | no | no |  |
| astropy__astropy-12907 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| astropy__astropy-12907 | paraphrase | claude-haiku-4-5-20251001 | 3 | real | no | no |  |
| astropy__astropy-12907 | reordering | deterministic | 2 | real | no | no |  |
| astropy__astropy-12907 | typo_injection | deterministic | 1 | real | no | no |  |
| astropy__astropy-12907 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| astropy__astropy-14365 | neutralize_emotional | claude-haiku-4-5-20251001 | 3 | real | no | no |  |
| astropy__astropy-14365 | original | original | N/A | N/A | no | no |  |
| astropy__astropy-14365 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| astropy__astropy-14365 | paraphrase | claude-haiku-4-5-20251001 | 3 | real | no | no |  |
| astropy__astropy-14365 | reordering | deterministic | 2 | real | no | no |  |
| astropy__astropy-14365 | typo_injection | deterministic | 1 | real | no | no |  |
| astropy__astropy-14365 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| astropy__astropy-7746 | neutralize_emotional | claude-haiku-4-5-20251001 | 3 | real | yes | no | no-op: identical to the original after whitespace normalization |
| astropy__astropy-7746 | original | original | N/A | N/A | no | no |  |
| astropy__astropy-7746 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| astropy__astropy-7746 | paraphrase | claude-haiku-4-5-20251001 | 3 | real | no | no |  |
| astropy__astropy-7746 | reordering | deterministic | 2 | real | no | no |  |
| astropy__astropy-7746 | typo_injection | deterministic | 1 | real | no | no |  |
| astropy__astropy-7746 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| django__django-12708 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| django__django-12708 | original | original | N/A | N/A | no | no |  |
| django__django-12708 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| django__django-12708 | paraphrase | claude-haiku-4-5-20251001 | 3 | real | no | no |  |
| django__django-12708 | reordering | deterministic | 2 | real | no | no |  |
| django__django-12708 | typo_injection | deterministic | 1 | real | no | no |  |
| django__django-12708 | verbosity_reduction | claude-haiku-4-5-20251001 | 3 | real | no | no |  |
| django__django-15347 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| django__django-15347 | original | original | N/A | N/A | no | no |  |
| django__django-15347 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| django__django-15347 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| django__django-15347 | reordering | deterministic | 2 | real | no | no |  |
| django__django-15347 | typo_injection | deterministic | 1 | real | no | no |  |
| django__django-15347 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| django__django-15814 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| django__django-15814 | original | original | N/A | N/A | no | no |  |
| django__django-15814 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| django__django-15814 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| django__django-15814 | reordering | deterministic | 2 | real | no | no |  |
| django__django-15814 | typo_injection | deterministic | 1 | real | no | no |  |
| django__django-15814 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| matplotlib__matplotlib-23964 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| matplotlib__matplotlib-23964 | original | original | N/A | N/A | no | no |  |
| matplotlib__matplotlib-23964 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| matplotlib__matplotlib-23964 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| matplotlib__matplotlib-23964 | reordering | deterministic | 2 | real | no | no |  |
| matplotlib__matplotlib-23964 | typo_injection | deterministic | 1 | real | no | no |  |
| matplotlib__matplotlib-23964 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| matplotlib__matplotlib-24970 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | yes | no | no-op: identical to the original after whitespace normalization |
| matplotlib__matplotlib-24970 | original | original | N/A | N/A | no | no |  |
| matplotlib__matplotlib-24970 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| matplotlib__matplotlib-24970 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| matplotlib__matplotlib-24970 | reordering | deterministic | 2 | real | no | no |  |
| matplotlib__matplotlib-24970 | typo_injection | deterministic | 1 | real | no | no |  |
| matplotlib__matplotlib-24970 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| mwaskom__seaborn-3010 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| mwaskom__seaborn-3010 | original | original | N/A | N/A | no | no |  |
| mwaskom__seaborn-3010 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| mwaskom__seaborn-3010 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| mwaskom__seaborn-3010 | reordering | deterministic | 2 | real | no | no |  |
| mwaskom__seaborn-3010 | typo_injection | deterministic | 1 | real | no | no |  |
| mwaskom__seaborn-3010 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | yes | no | no-op: identical to the original after whitespace normalization |
| mwaskom__seaborn-3190 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | yes | no | no-op: identical to the original after whitespace normalization |
| mwaskom__seaborn-3190 | original | original | N/A | N/A | no | no |  |
| mwaskom__seaborn-3190 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| mwaskom__seaborn-3190 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| mwaskom__seaborn-3190 | reordering | deterministic | 2 | real | yes | no | no-op: identical to the original after whitespace normalization |
| mwaskom__seaborn-3190 | typo_injection | deterministic | 1 | real | no | no |  |
| mwaskom__seaborn-3190 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | yes | no | no-op: identical to the original after whitespace normalization |
| psf__requests-2148 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| psf__requests-2148 | original | original | N/A | N/A | no | no |  |
| psf__requests-2148 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| psf__requests-2148 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| psf__requests-2148 | reordering | deterministic | 2 | real | no | no |  |
| psf__requests-2148 | typo_injection | deterministic | 1 | real | no | no |  |
| psf__requests-2148 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| psf__requests-2317 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| psf__requests-2317 | original | original | N/A | N/A | no | no |  |
| psf__requests-2317 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| psf__requests-2317 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| psf__requests-2317 | reordering | deterministic | 2 | real | no | no |  |
| psf__requests-2317 | typo_injection | deterministic | 1 | real | no | no |  |
| psf__requests-2317 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | yes | identifier retention failed (missing 2: python2.6, python3.4) |
| pylint-dev__pylint-6506 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| pylint-dev__pylint-6506 | original | original | N/A | N/A | no | no |  |
| pylint-dev__pylint-6506 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| pylint-dev__pylint-6506 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| pylint-dev__pylint-6506 | reordering | deterministic | 2 | real | no | no |  |
| pylint-dev__pylint-6506 | typo_injection | deterministic | 1 | real | no | no |  |
| pylint-dev__pylint-6506 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| pylint-dev__pylint-7993 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | yes | no | no-op: identical to the original after whitespace normalization |
| pylint-dev__pylint-7993 | original | original | N/A | N/A | no | no |  |
| pylint-dev__pylint-7993 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| pylint-dev__pylint-7993 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| pylint-dev__pylint-7993 | reordering | deterministic | 2 | real | no | no |  |
| pylint-dev__pylint-7993 | typo_injection | deterministic | 1 | real | no | no |  |
| pylint-dev__pylint-7993 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | yes | identifier retention failed (missing 1: Python3.9) |
| pytest-dev__pytest-11143 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| pytest-dev__pytest-11143 | original | original | N/A | N/A | no | no |  |
| pytest-dev__pytest-11143 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| pytest-dev__pytest-11143 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| pytest-dev__pytest-11143 | reordering | deterministic | 2 | real | no | no |  |
| pytest-dev__pytest-11143 | typo_injection | deterministic | 1 | real | no | no |  |
| pytest-dev__pytest-11143 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| pytest-dev__pytest-7373 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| pytest-dev__pytest-7373 | original | original | N/A | N/A | no | no |  |
| pytest-dev__pytest-7373 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| pytest-dev__pytest-7373 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| pytest-dev__pytest-7373 | reordering | deterministic | 2 | real | no | no |  |
| pytest-dev__pytest-7373 | typo_injection | deterministic | 1 | real | no | no |  |
| pytest-dev__pytest-7373 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | yes | identifier retention failed (missing 1: 5.4.3) |
| scikit-learn__scikit-learn-14087 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| scikit-learn__scikit-learn-14087 | original | original | N/A | N/A | no | no |  |
| scikit-learn__scikit-learn-14087 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| scikit-learn__scikit-learn-14087 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| scikit-learn__scikit-learn-14087 | reordering | deterministic | 2 | real | no | no |  |
| scikit-learn__scikit-learn-14087 | typo_injection | deterministic | 1 | real | no | no |  |
| scikit-learn__scikit-learn-14087 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| scikit-learn__scikit-learn-14983 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | yes | no | no-op: identical to the original after whitespace normalization |
| scikit-learn__scikit-learn-14983 | original | original | N/A | N/A | no | no |  |
| scikit-learn__scikit-learn-14983 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| scikit-learn__scikit-learn-14983 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| scikit-learn__scikit-learn-14983 | reordering | deterministic | 2 | real | no | no |  |
| scikit-learn__scikit-learn-14983 | typo_injection | deterministic | 1 | real | no | no |  |
| scikit-learn__scikit-learn-14983 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| sympy__sympy-20049 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| sympy__sympy-20049 | original | original | N/A | N/A | no | no |  |
| sympy__sympy-20049 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | no |  |
| sympy__sympy-20049 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| sympy__sympy-20049 | reordering | deterministic | 2 | real | no | no |  |
| sympy__sympy-20049 | typo_injection | deterministic | 1 | real | no | no |  |
| sympy__sympy-20049 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| sympy__sympy-24102 | neutralize_emotional | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| sympy__sympy-24102 | original | original | N/A | N/A | no | no |  |
| sympy__sympy-24102 | paragraph_to_structured | claude-haiku-4-5-20251001 | 5 | real | no | yes | placeholder_lost: [[CODE_1]] appears 2 times, [[CODE_2]] appears 2 times, [[CODE_3]] appears 2 times, [[CODE_4]] appears 3 times, [[CODE_5]] appears 7 times, [[CODE_6]] appears 2 times, [[CODE_7]] appears 2 times, [[CODE_12]] appears 2 times |
| sympy__sympy-24102 | paraphrase | claude-haiku-4-5-20251001 | 4 | real | no | no |  |
| sympy__sympy-24102 | reordering | deterministic | 2 | real | no | no |  |
| sympy__sympy-24102 | typo_injection | deterministic | 1 | real | no | no |  |
| sympy__sympy-24102 | verbosity_reduction | claude-haiku-4-5-20251001 | 4 | real | no | no |  |

## Methodology

### Transformations

- **paraphrase** (enabled): params = {}
- **verbosity_reduction** (enabled): params = {"target_ratio": 0.5}
- **typo_injection** (enabled): params = {"error_rate": 0.02}
- **reordering** (enabled): params = {"seed": 42}
- **paragraph_to_structured** (enabled): params = {}
- **neutralize_emotional** (enabled): params = {}

### Metric Definitions

- **Outcome (localization success):** success iff a valid unified diff was extracted and it modifies every file the gold patch modifies; otherwise failure. Without a gold patch, a valid diff counts as success. Weaker than test-based resolution, which is deferred to the larger study. The file overlap (Jaccard) between the patch's files and the gold patch's files is reported next to it.
- **Excluded runs:** runs that did not complete normally, runs on quality-warning variants and runs on no-op variants have no outcome and do not enter A, F or G.
- **A / Success Consistency (SC):** Fraction of variants sharing the same outcome as the original.
- **F / Stability Score (SS):** Weighted aggregate of SC (and optionally patch similarity).
- **G / Transformation Sensitivity (TS):** Mean drop in success rate caused by a transformation.
- **Flip rate:** fraction of issues whose outcome changes, in either direction, between the original and the variant (TS lets opposite flips cancel out).
- **Control flip rate (noise floor):** the same flip rate between the original run and its control runs, re-runs of the unchanged original; control runs never enter A, F or G.

### Configuration Snapshot

```json
{
  "experiment_name": "icse_pilot_model2",
  "description": "ICSE 2027 pilot, second model: the 20 pilot issues and the exact variants of the pilot (experiment bc6f1372), LLM Baseline on GPT-4o, 6 transforms, 1 control repeat. To use another model, change provider and model only (e.g. anthropic / claude-haiku-4-5-20251001); the key variable follows the provider.",
  "execution_mode": "real",
  "agents": [
    {
      "name": "llm_baseline",
      "version": "1.0",
      "params": {
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": 0.0,
        "max_tokens": 4096,
        "timeout_seconds": 120,
        "cost_cap_usd": 0.5
      }
    }
  ],
  "issues": {
    "source": "swebench_lite",
    "issue_ids": [
      "astropy__astropy-12907",
      "astropy__astropy-14365",
      "astropy__astropy-7746",
      "django__django-12708",
      "django__django-15347",
      "django__django-15814",
      "matplotlib__matplotlib-23964",
      "matplotlib__matplotlib-24970",
      "mwaskom__seaborn-3010",
      "mwaskom__seaborn-3190",
      "psf__requests-2148",
      "psf__requests-2317",
      "pylint-dev__pylint-6506",
      "pylint-dev__pylint-7993",
      "pytest-dev__pytest-11143",
      "pytest-dev__pytest-7373",
      "scikit-learn__scikit-learn-14087",
      "scikit-learn__scikit-learn-14983",
      "sympy__sympy-20049",
      "sympy__sympy-24102"
    ]
  },
  "transformations": [
    {
      "name": "paraphrase",
      "enabled": true,
      "params": {}
    },
    {
      "name": "verbosity_reduction",
      "enabled": true,
      "params": {
        "target_ratio": 0.5
      }
    },
    {
      "name": "typo_injection",
      "enabled": true,
      "params": {
        "error_rate": 0.02
      }
    },
    {
      "name": "reordering",
      "enabled": true,
      "params": {
        "seed": 42
      }
    },
    {
      "name": "paragraph_to_structured",
      "enabled": true,
      "params": {}
    },
    {
      "name": "neutralize_emotional",
      "enabled": true,
      "params": {}
    }
  ],
  "runs_per_variant": 1,
  "control_repeats": 1,
  "cost_limit_usd": 4.0,
  "output_dir": "./results/icse_pilot_model2",
  "originals_only": false,
  "reuse_variants_from": "bc6f1372-2088-45dd-907c-d741c0545d27"
}
```
