# ADR-0006: Two-Tier Deterministic Validation and Cognitive Evaluation

## Status
Accepted

## Context
Asking an LLM to check if quotes exist character-for-character in hundreds of pages leads to hallucinations.

## Decision
1. Deterministic validation in `harness/validation/` runs pure Python string and citation matching, generating a structured `VerificationReport`.
2. The Evaluator Agent operates over the report as `single_shot` to judge semantic authority and legal coherence.
