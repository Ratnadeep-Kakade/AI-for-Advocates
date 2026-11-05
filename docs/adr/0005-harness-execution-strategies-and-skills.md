# ADR-0005: Harness Execution Strategies and Claude-Style Skills

## Status
Accepted

## Context
A generic ReAct loop applied to all agents causes unpredictable loops and token starvation. Anthropic's 'Building Effective Agents' recommends tailoring the execution strategy to each agent's core capability.

## Decision
1. Each agent manifest declares an `execution_strategy`:
   - `tool_loop`: Budgeted autonomous loop for Legal Researcher.
   - `map_reduce`: Section-by-section parallel extraction for Document Intelligence.
   - `single_shot`: Structured generation over assembled evidence for Argument, Counterargument, and Evaluator.
2. Skills are defined as directory instruction packs (`SKILL.md`) with YAML frontmatter activation rules.
