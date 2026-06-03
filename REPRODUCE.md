# Reproducing the VillagerAgent Paper Experiments

This note maps the paper experiments from arXiv:2406.05720 to this checkout.

## What The Paper Reports

The main VillagerBench experiments use VillagerAgent on three Minecraft scenarios:

- Construction Cooperation: 100 tasks, task indices 0-99, two agents, no material-factory mining for the main LLM comparison.
- Farm-to-Table Cooking: 100 tasks, indices 0-35 for cake and 36-99 for rabbit stew.
- Escape Room Challenge: 25 generated tasks from five difficulty levels and fixed seeds.

The paper compares `gpt-4-1106-preview`, `gemini-pro`, and `glm-4`. Each task is executed once for the LLM capability test, with a run stopped when completed or when it exceeds the expected time frame. Appendix C lists model settings: temperature 0 for GPT/Gemini, 0.01 for GLM, max context below 4,000 tokens, and output length around 1,024 tokens for the tested prompts.

The paper also includes:

- AgentVerse baseline on Farm-to-Table Cooking.
- Agent quantity ablation on construction task 0 and task 64 with 1, 2, 4, and 8 agents, repeated six times.
- Same-vs-diverse agent abilities ablation on farming task 99, repeated six times.
- Overcooked-AI comparison against ProAgent.

## Current Repo Fit

This checkout contains the core VillagerBench runtime, Mineflayer agent server, static construction and farming task data, escape atom data, prompt templates, and judgers.

Known gaps:

- There is no local AgentVerse or Overcooked-AI implementation in this checkout, so those paper tables are not directly reproducible without adding external baseline code.
- `config.py` currently generates only small sample ranges for construction/farming/puzzle rather than the full paper setup.
- `start_with_config.py` has been adjusted to accept `--config` and respect `api_model`/`api_base` from each config.
- The Dockerfile still references `run.py`, which is not present. Prefer local setup unless you patch Docker first.

## Setup

Run from the repo root.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
npm install
python js_setup.py
```

Create `API_KEY_LIST` in the repo root. The runner checks model-specific key groups first, then falls back:

```json
{
  "AGENT_KEY": ["openai-compatible-key"],
  "OPENAI": ["openai-key"],
  "GEMINI": ["gemini-key"],
  "GLM": ["zhipu-or-glm-key"]
}
```

Start a Minecraft 1.19.2 server on the configured host/port, usually `localhost:25565`. The judgers issue `/op` for registered agents, but the server must allow commands/offline Mineflayer login.

## Generate Paper Configs

Generate the main GPT-4 paper-style configs:

```bash
python scripts/generate_paper_configs.py \
  --suite all \
  --api-model gpt-4-1106-preview \
  --api-base https://api.openai.com/v1 \
  --host localhost \
  --port 25565
```

This writes:

- `paper_configs/gpt_4_1106_preview_paper_construction_config.json`
- `paper_configs/gpt_4_1106_preview_paper_farming_config.json`
- `paper_configs/gpt_4_1106_preview_paper_escape_config.json`

Generate GLM/Gemini configs by changing `--api-model`, for example:

```bash
python scripts/generate_paper_configs.py --suite all --api-model glm-4
python scripts/generate_paper_configs.py --suite all --api-model gemini-pro
```

For a cheap smoke test, generate one task first:

```bash
python scripts/generate_paper_configs.py \
  --suite construction \
  --construction-tasks 1 \
  --output-dir paper_configs/smoke
```

## Run Experiments

Run one config file at a time:

```bash
python start_with_config.py --config paper_configs/gpt_4_1106_preview_paper_construction_config.json
python start_with_config.py --config paper_configs/gpt_4_1106_preview_paper_farming_config.json
python start_with_config.py --config paper_configs/gpt_4_1106_preview_paper_escape_config.json
```

Full reproduction is expensive: 225 Minecraft tasks per model for the main comparison, plus extra ablation repeats. Expect many LLM calls and long wall-clock time.

## Summarize Results

After runs, aggregate local `result/*/score.json` files:

```bash
python scripts/summarize_results.py --result-dir result
```

Metric mapping:

- Construction: `block_hit_rate` -> C, `view_hit_rate` -> VHR, `efficiency` -> E, `balance` -> B if present.
- Farming: `score` -> C, `cooperation` -> ACR, `efficiency` -> E, `balance` -> B.
- Escape: `complete_score` -> C, `efficiency` -> E, `balance` -> B.

Construction and escape completion fields are stored as fractions by the judgers and reported as percentages by the summarizer.

## Ablations

Agent quantity ablation:

```bash
python scripts/generate_paper_configs.py --suite construction --construction-tasks 1 --construction-agents 1 --output-dir paper_configs/ablations
python scripts/generate_paper_configs.py --suite construction --construction-tasks 65 --construction-agents 4 --output-dir paper_configs/ablations
```

The paper repeats construction task 0 and task 64 six times for each agent count. The helper currently generates task prefixes; duplicate/repeated configs should use unique `task_name` values before running.

Same-vs-diverse farming task 99 is partly supported in `start_with_config.py`: set `task_type` to `farming`, `task_idx` to `99`, `agent_num` to `3`, and use `role: "same"` or `role: "different"` in the config.

## Practical First Target

Start with one smoke task, then one small subset of each scenario, then run the full GPT-4 configs. Once the pipeline is stable, repeat with GLM/Gemini and compare the summarizer output to Tables 1 and 3 in the paper.
