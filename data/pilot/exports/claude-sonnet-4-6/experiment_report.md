# Experiment Report: icse_pilot_v1

## Summary

- **Date:** 2026-10-09
- **Status:** completed
- **Agents:** llm_baseline
- **Issues:** 20
- **Transformations:** paraphrase, verbosity_reduction, typo_injection, reordering, paragraph_to_structured, neutralize_emotional
- **Total runs:** 160
- **Total cost:** $1.4213

### Excluded from metrics A/F/G

- **Runs that did not complete normally** (timeout, cost cap, error): 0
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
| llm_baseline|django__django-15347 | 1.000 | 1.000 |
| llm_baseline|django__django-15814 | 1.000 | 1.000 |
| llm_baseline|matplotlib__matplotlib-23964 | 1.000 | 1.000 |
| llm_baseline|matplotlib__matplotlib-24970 | 1.000 | 1.000 |
| llm_baseline|mwaskom__seaborn-3010 | 1.000 | 1.000 |
| llm_baseline|mwaskom__seaborn-3190 | 1.000 | 1.000 |
| llm_baseline|psf__requests-2148 | 1.000 | 1.000 |
| llm_baseline|psf__requests-2317 | 0.800 | 0.800 |
| llm_baseline|pylint-dev__pylint-6506 | 1.000 | 1.000 |
| llm_baseline|pylint-dev__pylint-7993 | 1.000 | 1.000 |
| llm_baseline|pytest-dev__pytest-11143 | 1.000 | 1.000 |
| llm_baseline|pytest-dev__pytest-7373 | 1.000 | 1.000 |
| llm_baseline|scikit-learn__scikit-learn-14087 | 1.000 | 1.000 |
| llm_baseline|scikit-learn__scikit-learn-14983 | 1.000 | 1.000 |
| llm_baseline|sympy__sympy-20049 | 1.000 | 1.000 |
| llm_baseline|sympy__sympy-24102 | 1.000 | 1.000 |

**Mean Stability Score (llm_baseline):** 0.990

## RQ2 — Transformation Sensitivity

TS is a drop rate (success → failure counts +1, failure → success −1); the flip rate counts any change of outcome between the original and the variant.

| Agent | Transformation | Sensitivity (G) | Flip rate |
|-------|---------------|-----------------|-----------|
| llm_baseline | reordering | 0.053 | 0.053 |
| llm_baseline | paraphrase | 0.000 | 0.000 |
| llm_baseline | verbosity_reduction | 0.000 | 0.000 |
| llm_baseline | typo_injection | 0.000 | 0.000 |
| llm_baseline | paragraph_to_structured | 0.000 | 0.000 |
| llm_baseline | neutralize_emotional | 0.000 | 0.000 |

**Most disruptive transformation:** reordering (sensitivity = 0.053)

**Noise floor (llm_baseline):** control flip rate = 0.000 over 20 control run(s), re-runs of the unchanged original. A flip rate at or below it is indistinguishable from run-to-run variance.

## Issue-Level Results

| Issue | Transformation | Agent | Status | Outcome | File overlap (Jaccard) | Cost |
|-------|----------------|-------|--------|---------|------------------------|------|
| astropy__astropy-12907 | original | llm_baseline | success | success | 1.000 | $0.0063 |
| astropy__astropy-12907 | paraphrase | llm_baseline | success | success | 1.000 | $0.0068 |
| astropy__astropy-12907 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0099 |
| astropy__astropy-12907 | typo_injection | llm_baseline | success | success | 1.000 | $0.0066 |
| astropy__astropy-12907 | reordering | llm_baseline | success | success | 1.000 | $0.0090 |
| astropy__astropy-12907 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0079 |
| astropy__astropy-12907 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0066 |
| astropy__astropy-12907 | original (control) | llm_baseline | success | success | 1.000 | $0.0067 |
| astropy__astropy-14365 | original | llm_baseline | success | success | 1.000 | $0.0152 |
| astropy__astropy-14365 | paraphrase | llm_baseline | success | success | 1.000 | $0.0187 |
| astropy__astropy-14365 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0161 |
| astropy__astropy-14365 | typo_injection | llm_baseline | success | success | 1.000 | $0.0185 |
| astropy__astropy-14365 | reordering | llm_baseline | success | success | 1.000 | $0.0135 |
| astropy__astropy-14365 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0165 |
| astropy__astropy-14365 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0133 |
| astropy__astropy-14365 | original (control) | llm_baseline | success | success | 1.000 | $0.0156 |
| astropy__astropy-7746 | original | llm_baseline | success | success | 1.000 | $0.0084 |
| astropy__astropy-7746 | paraphrase | llm_baseline | success | success | 1.000 | $0.0138 |
| astropy__astropy-7746 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0110 |
| astropy__astropy-7746 | typo_injection | llm_baseline | success | success | 1.000 | $0.0102 |
| astropy__astropy-7746 | reordering | llm_baseline | success | success | 1.000 | $0.0080 |
| astropy__astropy-7746 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0090 |
| astropy__astropy-7746 | neutralize_emotional | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| astropy__astropy-7746 | original (control) | llm_baseline | success | success | 1.000 | $0.0093 |
| django__django-12708 | original | llm_baseline | success | success | 1.000 | $0.0095 |
| django__django-12708 | paraphrase | llm_baseline | success | success | 1.000 | $0.0089 |
| django__django-12708 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0066 |
| django__django-12708 | typo_injection | llm_baseline | success | success | 1.000 | $0.0071 |
| django__django-12708 | reordering | llm_baseline | success | success | 1.000 | $0.0073 |
| django__django-12708 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0076 |
| django__django-12708 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0095 |
| django__django-12708 | original (control) | llm_baseline | success | success | 1.000 | $0.0095 |
| django__django-15347 | original | llm_baseline | success | success | 1.000 | $0.0069 |
| django__django-15347 | paraphrase | llm_baseline | success | success | 1.000 | $0.0068 |
| django__django-15347 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0068 |
| django__django-15347 | typo_injection | llm_baseline | success | success | 1.000 | $0.0069 |
| django__django-15347 | reordering | llm_baseline | success | success | 1.000 | $0.0069 |
| django__django-15347 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0085 |
| django__django-15347 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0069 |
| django__django-15347 | original (control) | llm_baseline | success | success | 1.000 | $0.0069 |
| django__django-15814 | original | llm_baseline | success | success | 1.000 | $0.0081 |
| django__django-15814 | paraphrase | llm_baseline | success | success | 1.000 | $0.0080 |
| django__django-15814 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0082 |
| django__django-15814 | typo_injection | llm_baseline | success | success | 1.000 | $0.0081 |
| django__django-15814 | reordering | llm_baseline | success | success | 1.000 | $0.0081 |
| django__django-15814 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0080 |
| django__django-15814 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0080 |
| django__django-15814 | original (control) | llm_baseline | success | success | 1.000 | $0.0080 |
| matplotlib__matplotlib-23964 | original | llm_baseline | success | success | 1.000 | $0.0094 |
| matplotlib__matplotlib-23964 | paraphrase | llm_baseline | success | success | 1.000 | $0.0106 |
| matplotlib__matplotlib-23964 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0089 |
| matplotlib__matplotlib-23964 | typo_injection | llm_baseline | success | success | 1.000 | $0.0103 |
| matplotlib__matplotlib-23964 | reordering | llm_baseline | success | success | 1.000 | $0.0091 |
| matplotlib__matplotlib-23964 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0094 |
| matplotlib__matplotlib-23964 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0092 |
| matplotlib__matplotlib-23964 | original (control) | llm_baseline | success | success | 1.000 | $0.0092 |
| matplotlib__matplotlib-24970 | original | llm_baseline | success | success | 1.000 | $0.0073 |
| matplotlib__matplotlib-24970 | paraphrase | llm_baseline | success | success | 1.000 | $0.0090 |
| matplotlib__matplotlib-24970 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0073 |
| matplotlib__matplotlib-24970 | typo_injection | llm_baseline | success | success | 1.000 | $0.0090 |
| matplotlib__matplotlib-24970 | reordering | llm_baseline | success | success | 1.000 | $0.0095 |
| matplotlib__matplotlib-24970 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0080 |
| matplotlib__matplotlib-24970 | neutralize_emotional | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| matplotlib__matplotlib-24970 | original (control) | llm_baseline | success | success | 1.000 | $0.0073 |
| mwaskom__seaborn-3010 | original | llm_baseline | success | success | 1.000 | $0.0089 |
| mwaskom__seaborn-3010 | paraphrase | llm_baseline | success | success | 1.000 | $0.0112 |
| mwaskom__seaborn-3010 | verbosity_reduction | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| mwaskom__seaborn-3010 | typo_injection | llm_baseline | success | success | 1.000 | $0.0089 |
| mwaskom__seaborn-3010 | reordering | llm_baseline | success | success | 1.000 | $0.0093 |
| mwaskom__seaborn-3010 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0094 |
| mwaskom__seaborn-3010 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0093 |
| mwaskom__seaborn-3010 | original (control) | llm_baseline | success | success | 1.000 | $0.0089 |
| mwaskom__seaborn-3190 | original | llm_baseline | success | success | 1.000 | $0.0075 |
| mwaskom__seaborn-3190 | paraphrase | llm_baseline | success | success | 1.000 | $0.0067 |
| mwaskom__seaborn-3190 | verbosity_reduction | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| mwaskom__seaborn-3190 | typo_injection | llm_baseline | success | success | 1.000 | $0.0078 |
| mwaskom__seaborn-3190 | reordering | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| mwaskom__seaborn-3190 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0068 |
| mwaskom__seaborn-3190 | neutralize_emotional | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| mwaskom__seaborn-3190 | original (control) | llm_baseline | success | success | 1.000 | $0.0080 |
| psf__requests-2148 | original | llm_baseline | success | success | 1.000 | $0.0079 |
| psf__requests-2148 | paraphrase | llm_baseline | success | success | 1.000 | $0.0081 |
| psf__requests-2148 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0077 |
| psf__requests-2148 | typo_injection | llm_baseline | success | success | 1.000 | $0.0083 |
| psf__requests-2148 | reordering | llm_baseline | success | success | 1.000 | $0.0083 |
| psf__requests-2148 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0079 |
| psf__requests-2148 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0078 |
| psf__requests-2148 | original (control) | llm_baseline | success | success | 1.000 | $0.0079 |
| psf__requests-2317 | original | llm_baseline | success | success | 1.000 | $0.0072 |
| psf__requests-2317 | paraphrase | llm_baseline | success | success | 1.000 | $0.0077 |
| psf__requests-2317 | verbosity_reduction | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| psf__requests-2317 | typo_injection | llm_baseline | success | success | 1.000 | $0.0081 |
| psf__requests-2317 | reordering | llm_baseline | success | failure | 0.000 | $0.0054 |
| psf__requests-2317 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0078 |
| psf__requests-2317 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0084 |
| psf__requests-2317 | original (control) | llm_baseline | success | success | 1.000 | $0.0073 |
| pylint-dev__pylint-6506 | original | llm_baseline | success | success | 1.000 | $0.0074 |
| pylint-dev__pylint-6506 | paraphrase | llm_baseline | success | success | 1.000 | $0.0070 |
| pylint-dev__pylint-6506 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0103 |
| pylint-dev__pylint-6506 | typo_injection | llm_baseline | success | success | 1.000 | $0.0072 |
| pylint-dev__pylint-6506 | reordering | llm_baseline | success | success | 1.000 | $0.0073 |
| pylint-dev__pylint-6506 | paragraph_to_structured | llm_baseline | success | success | 0.500 | $0.0093 |
| pylint-dev__pylint-6506 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0085 |
| pylint-dev__pylint-6506 | original (control) | llm_baseline | success | success | 1.000 | $0.0070 |
| pylint-dev__pylint-7993 | original | llm_baseline | success | success | 1.000 | $0.0095 |
| pylint-dev__pylint-7993 | paraphrase | llm_baseline | success | success | 1.000 | $0.0141 |
| pylint-dev__pylint-7993 | verbosity_reduction | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| pylint-dev__pylint-7993 | typo_injection | llm_baseline | success | success | 1.000 | $0.0104 |
| pylint-dev__pylint-7993 | reordering | llm_baseline | success | success | 1.000 | $0.0095 |
| pylint-dev__pylint-7993 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0096 |
| pylint-dev__pylint-7993 | neutralize_emotional | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| pylint-dev__pylint-7993 | original (control) | llm_baseline | success | success | 1.000 | $0.0099 |
| pytest-dev__pytest-11143 | original | llm_baseline | success | success | 1.000 | $0.0112 |
| pytest-dev__pytest-11143 | paraphrase | llm_baseline | success | success | 1.000 | $0.0113 |
| pytest-dev__pytest-11143 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0110 |
| pytest-dev__pytest-11143 | typo_injection | llm_baseline | success | success | 1.000 | $0.0113 |
| pytest-dev__pytest-11143 | reordering | llm_baseline | success | success | 1.000 | $0.0112 |
| pytest-dev__pytest-11143 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0112 |
| pytest-dev__pytest-11143 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0113 |
| pytest-dev__pytest-11143 | original (control) | llm_baseline | success | success | 1.000 | $0.0112 |
| pytest-dev__pytest-7373 | original | llm_baseline | success | success | 1.000 | $0.0112 |
| pytest-dev__pytest-7373 | paraphrase | llm_baseline | success | success | 1.000 | $0.0113 |
| pytest-dev__pytest-7373 | verbosity_reduction | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| pytest-dev__pytest-7373 | typo_injection | llm_baseline | success | success | 1.000 | $0.0111 |
| pytest-dev__pytest-7373 | reordering | llm_baseline | success | success | 1.000 | $0.0117 |
| pytest-dev__pytest-7373 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0103 |
| pytest-dev__pytest-7373 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0112 |
| pytest-dev__pytest-7373 | original (control) | llm_baseline | success | success | 1.000 | $0.0112 |
| scikit-learn__scikit-learn-14087 | original | llm_baseline | success | success | 1.000 | $0.0113 |
| scikit-learn__scikit-learn-14087 | paraphrase | llm_baseline | success | success | 1.000 | $0.0130 |
| scikit-learn__scikit-learn-14087 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0097 |
| scikit-learn__scikit-learn-14087 | typo_injection | llm_baseline | success | success | 1.000 | $0.0153 |
| scikit-learn__scikit-learn-14087 | reordering | llm_baseline | success | success | 1.000 | $0.0078 |
| scikit-learn__scikit-learn-14087 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0099 |
| scikit-learn__scikit-learn-14087 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0100 |
| scikit-learn__scikit-learn-14087 | original (control) | llm_baseline | success | success | 1.000 | $0.0103 |
| scikit-learn__scikit-learn-14983 | original | llm_baseline | success | success | 1.000 | $0.0095 |
| scikit-learn__scikit-learn-14983 | paraphrase | llm_baseline | success | success | 1.000 | $0.0069 |
| scikit-learn__scikit-learn-14983 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0085 |
| scikit-learn__scikit-learn-14983 | typo_injection | llm_baseline | success | success | 1.000 | $0.0103 |
| scikit-learn__scikit-learn-14983 | reordering | llm_baseline | success | success | 1.000 | $0.0084 |
| scikit-learn__scikit-learn-14983 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0084 |
| scikit-learn__scikit-learn-14983 | neutralize_emotional | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| scikit-learn__scikit-learn-14983 | original (control) | llm_baseline | success | success | 1.000 | $0.0103 |
| sympy__sympy-20049 | original | llm_baseline | success | success | 1.000 | $0.0105 |
| sympy__sympy-20049 | paraphrase | llm_baseline | success | success | 1.000 | $0.0119 |
| sympy__sympy-20049 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0155 |
| sympy__sympy-20049 | typo_injection | llm_baseline | success | success | 1.000 | $0.0106 |
| sympy__sympy-20049 | reordering | llm_baseline | success | success | 1.000 | $0.0123 |
| sympy__sympy-20049 | paragraph_to_structured | llm_baseline | success | success | 1.000 | $0.0103 |
| sympy__sympy-20049 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0101 |
| sympy__sympy-20049 | original (control) | llm_baseline | success | success | 1.000 | $0.0118 |
| sympy__sympy-24102 | original | llm_baseline | success | success | 1.000 | $0.0144 |
| sympy__sympy-24102 | paraphrase | llm_baseline | success | success | 1.000 | $0.0143 |
| sympy__sympy-24102 | verbosity_reduction | llm_baseline | success | success | 1.000 | $0.0117 |
| sympy__sympy-24102 | typo_injection | llm_baseline | success | success | 1.000 | $0.0146 |
| sympy__sympy-24102 | reordering | llm_baseline | success | success | 1.000 | $0.0083 |
| sympy__sympy-24102 | paragraph_to_structured | llm_baseline | skipped_variant | excluded | N/A | $0.0000 |
| sympy__sympy-24102 | neutralize_emotional | llm_baseline | success | success | 1.000 | $0.0114 |
| sympy__sympy-24102 | original (control) | llm_baseline | success | success | 1.000 | $0.0135 |

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
  "experiment_name": "icse_pilot_v1",
  "description": "ICSE 2027 pilot: 20 SWE-bench Lite issues, LLM Baseline, 6 transforms, 1 control repeat",
  "execution_mode": "real",
  "agents": [
    {
      "name": "llm_baseline",
      "version": "1.0",
      "params": {
        "model": "claude-sonnet-4-6",
        "temperature": 0.0,
        "max_tokens": 4096,
        "timeout_seconds": 120,
        "cost_cap_usd": 0.5,
        "api_key_env_var": "ANTHROPIC_API_KEY"
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
  "cost_limit_usd": 5.0,
  "output_dir": "./results/icse_pilot_v1",
  "originals_only": false
}
```
