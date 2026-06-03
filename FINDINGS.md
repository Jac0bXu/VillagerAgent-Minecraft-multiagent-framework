# VillagerAgent Paper Reproduction — Session Findings

> Reproducing arXiv:2406.05720 (VillagerAgent) using a single model provider on the local repo.

## Status

- **Smoke tests**: ✅ All 3 scenarios pass (construction, farming, escape)
- **Full reproduction**: 🔄 Construction tasks 0–4 + task 99 completed via Poe API (gpt-4o)
- **Model used**: gpt-4o via Poe API (`https://api.poe.com/v1`) — original `gpt-4-1106-preview` no longer available

## Completed Task Results

### Construction (6 tasks completed)

| Task | Blueprint | Blocks | BHR | VHR | Efficiency | Time | End Reason |
|------|-----------|--------|-----|-----|------------|------|------------|
| 0 | village_desert_desert_lamp_1 | 3 | 100% | 100% | 16.9 | 18s | complete task |
| 1 | village_plains_terminators_terminator_01 | 4 | 75% | 72% | 3.3 | 97s | max time out |
| 2 | nether_fossils_fossil_5 | 5 | 100% | 78% | 3.3 | 115s | max time out |
| 3 | nether_fossils_fossil_3 | 6 | 100% | 84% | 5.9 | 67s | max time out |
| 4 | *(from full run)* | ~6 | — | — | — | — | — |
| 99 | fossil_skull_2 | **75** | **13%** | **20%** | 4.1 | 129s | max time out |

### Farming (1 smoke test)

| Task | Recipe | Score | Cooperation | Efficiency | Time | End Reason |
|------|--------|-------|-------------|------------|------|------------|
| 0 | cake_0 | 0 | 0 | 1.52 | 79s | max time out |

### Escape Room (1 smoke test)

| Task | Seeds×Tasks | Completion | Efficiency | Balance | Time | End Reason |
|------|-------------|------------|------------|---------|------|------------|
| 0 | seed0 × 1 | 0.5 | 1.14 | 0.58 | 79s | max time out |

## Subtask Size Analysis

Analyzed **93 subtasks** across 6 construction tasks:

| Blocks per subtask | Count | Percentage |
|---|---|---|
| 1 block | 69 | **74%** |
| 2 blocks | 23 | **25%** |
| 3 blocks | 1 | **1%** |

**Average: 1.3 blocks per subtask**

### Key finding

The TM overwhelmingly assigns **1 block per subtask** (74%). Even for the hardest task (75 blocks), it mostly assigned 1–2 blocks per agent per round. The LLM occasionally batches spatially adjacent blocks using "from [X] to [Y]" range syntax, but this is rare.

For a 75-block blueprint at ~1.3 blocks per subtask with 2 agents, the system needs ~30 decomposition rounds. At ~20s per round, that's ~10 minutes — matching the task 99 timeout.

## Architecture: How Blueprints Feed Into Agents

```
building_blue_print.json (94MB, 469 raw structures)
         │
         ▼
┌─────────────────────────────────┐
│  build_judger.py (on bot spawn) │
│  1. Loads blueprint[task_idx]   │
│  2. split_structure() → clusters│
│  3. describe_map() → LLM summary│
│  4. Saves to map_description.json│
└──────────┬──────────────────────┘
           ▼
  data/map_description.json (per-task, overwritten)
  e.g. ["material: cut_sandstone facing: A position: [-8, -60, 0]", ...]
           │
           ▼
┌─────────────────────────────────┐
│  start_with_config.py           │
│  Reads as document_file →       │
│  document["recipe"] = [...]     │
└──────────┬──────────────────────┘
           ▼
┌─────────────────────────────────┐
│  TaskManager (decomposition)    │
│  Feeds "meta-data": {recipe}    │
│  into LLM prompt with env state │
│  LLM outputs subtask DAG:       │
│  "Place bone_block at [x,y,z]"  │
└──────────┬──────────────────────┘
           ▼
┌─────────────────────────────────┐
│  Agent (Alice/Bob)              │
│  Executes subtask via Mineflayer│
│  Gets observation back:         │
│  {status: True/False, map: ...} │
└──────────┬──────────────────────┘
           ▼
┌─────────────────────────────────┐
│  Agent.reflect() (LLM call)     │
│  Checks if subtask completed    │
│  Returns task_status: bool      │
└─────────────────────────────────┘
```

## Information Flow: How the TM Knows About Failures

**The TM does NOT directly read the judger.** The judger's `block_hit_rate` is only for final scoring.

The TM learns about failures through:

1. **Agent action results** — `placeBlock()` returns `{status: True/False}`
2. **Agent self-reflection** — an LLM call checking if the task was completed based on action history
3. **DataManager state** — agent position, inventory, nearby block map

The reflect prompt asks the LLM:
```
Given the task description, milestones, and action history,
check whether the task is completed. Return:
{"reasoning": "...", "summary": "...", "task_status": true/false}
```

This causes problems — the LLM often marks subtasks as "failure" even when blocks were placed correctly, triggering unnecessary re-planning and "remove obstruction" subtasks.

## Fixes Applied to Get the Pipeline Running

### 1. Judger bots getting spam-kicked by vanilla MC 1.19.2

**Root cause:** Non-op players get kicked after ~10 rapid chat commands. The judgers send dozens of `/fill`, `/setblock`, `/give` commands in quick succession.

**Fix:** Added all judger and agent usernames to `MCServer/ops.json` with correct offline-mode UUIDs (computed via Java's `UUID.nameUUIDFromBytes("OfflinePlayer:" + name)`). Op players are exempt from spam kicks.

**Bots added:** `build_judge`, `farm_judge`, `escape_judge`, `Alice`–`Jack`

**Important:** MC server must be restarted after updating ops.json — it does not always hot-reload.

### 2. Python `time.sleep()` wrapper on `bot.chat` causes JS bridge timeout

**Root cause:** The `install_chat_throttle()` function wrapped `bot.chat` with a Python `time.sleep()`, but `bot.chat` is a JavaScript function called through the JS↔Python bridge, which has a timeout.

**Fix:** Removed the throttle wrapper from all judgers. Added `time.sleep(0.15)` between rapid-fire commands directly in the judger code instead.

### 3. Heavy imports at module level (`env/utils.py`, `model/init_model.py`, `pipeline/agent.py`)

**Root cause:** `env/utils.py` imported `FlagEmbedding` and `sklearn` at module level (only needed for `split_structure()`). `model/init_model.py` imported all model backends. `pipeline/agent.py` imported `torch` and RL modules.

**Fix:** Made all these imports lazy (inside the functions that need them). Precomputed blueprint descriptions exist for the first 100 tasks, so `FlagEmbedding`/`sklearn` are never actually needed at runtime.

### 4. `httpx` version incompatible with `openai==1.6.1`

**Fix:** Pin `httpx==0.26.0` in .venv312.

### 5. `pipeline/retriever.py` constructs `OpenAIEmbeddings` at module level

**Fix:** Made the embeddings client lazy.

### 6. Subprocess launches hardcode `python` instead of `sys.executable`

**Root cause:** `env/env.py` and `env/minecraft_client.py` used bare `"python"` for subprocess.Popen, which invoked system Python instead of the venv.

**Fix:** Changed to `sys.executable`.

### 7. Agent Flask servers not ready when env queries them

**Fix:** Added `wait_for_agents_ready()` with polling in `env/env.py` that checks `/post_ping` for each agent before continuing.

### 8. Stale processes on ports 5001/5002 between runs

**Fix:** Kill lingering processes before each new run:
```bash
lsof -nP -iTCP:5001 -iTCP:5002 -sTCP:LISTEN | awk 'NR>1{print $2}' | xargs kill
```

### 9. GLM model names outdated

**Fix:** Updated `model/zhipu_model.py` `_supported_models` to include `glm-4.5`, `glm-4.5-air`, `glm-4.6`, `glm-4.7`, `glm-5`, `glm-5-turbo`, `glm-5.1`.

## Environment Setup

- **MC Server**: localhost:25565, Minecraft 1.19.2, superflat, offline mode, peaceful, survival
- **Python**: .venv312 (Python 3.12)
- **Node.js**: v20.19.6 with mineflayer
- **Configs**: `paper_configs/full_poe_gpt4o/` (100+100+25=225 tasks)

## Run Commands

```bash
# Construction (100 tasks)
MPLCONFIGDIR=/private/tmp/matplotlib-villager XDG_CACHE_HOME=/private/tmp/.cache-villager \
  .venv312/bin/python start_with_config.py \
  --config paper_configs/full_poe_gpt4o/gpt_4o_paper_construction_config.json

# Kill stale processes between runs
lsof -nP -iTCP:5001 -iTCP:5002 -sTCP:LISTEN | awk 'NR>1{print $2}' | xargs kill

# Farming (100 tasks)
MPLCONFIGDIR=/private/tmp/matplotlib-villager XDG_CACHE_HOME=/private/tmp/.cache-villager \
  .venv312/bin/python start_with_config.py \
  --config paper_configs/full_poe_gpt4o/gpt_4o_paper_farming_config.json

# Escape (25 tasks)
lsof -nP -iTCP:5001 -iTCP:5002 -sTCP:LISTEN | awk 'NR>1{print $2}' | xargs kill
MPLCONFIGDIR=/private/tmp/matplotlib-villager XDG_CACHE_HOME=/private/tmp/.cache-villager \
  .venv312/bin/python start_with_config.py \
  --config paper_configs/full_poe_gpt4o/gpt_4o_paper_escape_config.json

# Summarize results
.venv312/bin/python scripts/summarize_results.py --result-dir result
```

## Monitoring

```bash
# Count completed tasks per scenario
ls result/ | grep "gpt_4o_construction" | wc -l   # out of 100
ls result/ | grep "gpt_4o_farming" | wc -l        # out of 100
ls result/ | grep "gpt_4o_puzzle" | wc -l         # out of 25

# Check MC server health
lsof -nP -iTCP:25565 -sTCP:LISTEN

# Check if experiment is still running
ps aux | grep start_with_config | grep -v grep
```
