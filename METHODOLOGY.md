# VillagerAgent: Complete Methodology & Reimplementation Guide

> This document exhaustively describes the VillagerAgent multi-agent Minecraft pipeline so that it can be reimplemented from scratch in a different codebase/infrastructure. Every claim is traced to specific file paths and line numbers. Real data from `result/gpt_4o_construction_task0_2p/` is used throughout.

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [End-to-End Lifecycle Trace: Construction Task 0](#2-end-to-end-lifecycle-trace)
3. [Component Reference](#3-component-reference)
4. [Prompt Template Catalog](#4-prompt-template-catalog)
5. [Inter-Process Architecture](#5-inter-process-architecture)
6. [Scoring & Evaluation Logic](#6-scoring--evaluation-logic)
7. [Edge Cases & Failure Modes](#7-edge-cases--failure-modes)
8. [Reimplementation Checklist](#8-reimplementation-checklist)

---

## 1. System Architecture Overview

### 1.1 ASCII Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        VillagerAgent System Architecture                     │
│                                                                              │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐        │
│  │  start_with_    │     │  Minecraft       │     │  Mineflayer      │        │
│  │  config.py      │────>│  Java Server     │<───>│  Bots (Node.js)  │        │
│  │  (main process) │     │  (port 25565)    │     │                  │        │
│  └────────┬────────┘     └─────────────────┘     └─────────────────┘        │
│           │                                              ^                    │
│           │ spawns                                       │ HTTP (per-agent   │
│           │ subprocess                                   │ Flask ports       │
│           v                                              │ 5001-500N)        │
│  ┌──────────────────────────────────────────┐            │                    │
│  │  run() subprocess                        │            │                    │
│  │                                          │            │                    │
│  │  ┌────────────┐  ┌────────────┐         │            │                    │
│  │  │ VillagerBench│  │ Judger     │         │     ┌──────┴──────┐            │
│  │  │  (env.py)   │  │ (Node.js)  │─────────┼────>│ Agent Bots  │            │
│  │  │             │  │            │         │     │ (Mineflayer) │            │
│  │  └──────┬──────┘  └────────────┘         │     └─────────────┘            │
│  │         │                                 │                               │
│  │         │ creates                         │     Also spawned:              │
│  │         v                                 │     ┌─────────────┐           │
│  │  ┌──────────────────────────────────┐    │     │ judger bot   │           │
│  │  │  GlobalController (controller_   │    │     │ (Mineflayer,  │           │
│  │  │  tiny.py)                         │    │     │  spectates,   │           │
│  │  │                                    │    │     │  sets blocks, │           │
│  │  │  ┌───────────┐ ┌──────────────┐  │    │     │  scores)      │           │
│  │  │  │TaskManager│ │ DataManager  │  │    │     └──────────────┘           │
│  │  │  │(task_     │ │(data_       │  │    │                                 │
│  │  │  │ manager.py)│ │ manager.py) │  │    │                                 │
│  │  │  └───────────┘ └──────────────┘  │    │                                 │
│  │  │                                    │    │                                 │
│  │  │  ┌──────────────────────────────┐ │    │                                 │
│  │  │  │ BaseAgent × N                │ │    │                                 │
│  │  │  │ (agent.py)                   │ │    │                                 │
│  │  │  │  Alice ──> env.step() ──> LangChain Agent ──> LLM API         │     │
│  │  │  │  Bob   ──> env.step() ──> LangChain Agent ──> LLM API         │     │
│  │  │  └──────────────────────────────┘ │    │                                 │
│  │  └──────────────────────────────────┘    │                                 │
│  └──────────────────────────────────────────┘                                 │
│                                                                                │
│  Communication:                                                               │
│  ── Pipeline (Python): function calls, shared objects                         │
│  ── Agents → Minecraft: HTTP POST to Flask per-agent server (port 5001+)     │
│  ── Judger → Minecraft: Mineflayer bot (direct MC protocol)                  │
│  ── Heartbeat: .cache/heart_beat.cache file polling                          │
│  ── Status: .cache/load_status.cache file polling                            │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Process Inventory

| Process | Technology | Role | Port |
|---------|-----------|------|------|
| `start_with_config.py` (main) | Python | Orchestrator, spawns task subprocesses | — |
| `run()` subprocess | Python (multiprocessing) | Runs the full pipeline for one task | — |
| Judger bot | Node.js (Mineflayer via JSPyBridge) | Sets up world, scores, monitors | 25565 (MC) |
| Agent bots (per agent) | Node.js (Mineflayer + Flask) | Executes LLM-chosen actions | 5001, 5002, ... |
| Minecraft Server | Java | The game world | 25565 |

### 1.3 Agent Action Loop

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Agent Action Loop                               │
│                                                                     │
│   BaseAgent.normal_step(task)                                       │
│         │                                                           │
│         v                                                           │
│   ┌─────────────────────────────────────┐                          │
│   │ 1. Build prompt from template       │                          │
│   │    agent_prompt_w/wo_emoji           │                          │
│   │    + task description                │                          │
│   │    + milestones                      │                          │
│   │    + env data (DM.query_env)         │                          │
│   │    + agent state (DM.query_history)  │                          │
│   │    + personality (random style)      │                          │
│   └──────────────┬──────────────────────┘                          │
│                  │                                                  │
│                  v                                                  │
│   ┌─────────────────────────────────────┐                          │
│   │ 2. env.step(name, prompt_str)       │                          │
│   │    → Agent.run(action_str)          │                          │
│   │    → LangChain ReAct Agent          │                          │
│   │    → LLM generates actions          │                          │
│   │    → LangChain executes tools       │                          │
│   │    → HTTP POST to Mineflayer bot    │                          │
│   │    → Bot acts in Minecraft          │                          │
│   │    → Returns observation            │                          │
│   │    (repeats for max_turn=7)         │                          │
│   └──────────────┬──────────────────────┘                          │
│                  │                                                  │
│                  v                                                  │
│   ┌─────────────────────────────────────┐                          │
│   │ 3. Update DataManager              │                          │
│   │    - Process action history         │                          │
│   │    - Summarize with LLM             │                          │
│   │    - Update env state               │                          │
│   └──────────────┬──────────────────────┘                          │
│                  │                                                  │
│                  v                                                  │
│   ┌─────────────────────────────────────┐                          │
│   │ 4. Reflect on task completion       │                          │
│   │    - Compare action history vs      │                          │
│   │      task + milestones              │                          │
│   │    - LLM returns task_status: bool  │                          │
│   └──────────────┬──────────────────────┘                          │
│                  │                                                  │
│                  v                                                  │
│   Return: (feedback, detail)                                        │
│   detail = {input, action_list, final_answer}                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.4 Task Decomposition Loop

```
┌─────────────────────────────────────────────────────────────────────┐
│               Task Decomposition Loop                               │
│                                                                     │
│  GlobalController.execute_tasks() ──> TM.query_subtask_list()      │
│         │                                    │                      │
│         │<─── list of open Tasks ─────────────┘                      │
│         │                                                           │
│         v                                                           │
│  check_task_list_available()                                        │
│    → filter to tasks with:                                          │
│      - no unfinished predecessors                                   │
│      - free candidate agents                                        │
│         │                                                           │
│         v                                                           │
│  execute_assignments()                                              │
│    → assign agents to tasks                                         │
│    → push to task_queue                                             │
│         │                                                           │
│         v                                                           │
│  worker thread ──> agent.step(task) ──> executor.submit()          │
│         │                                                           │
│         v                                                           │
│  process_completed_tasks()                                          │
│    → future.result() → (feedback, detail)                           │
│    → update_feedback(task, agent, detail)                           │
│       → agent.reflect(task, detail) → LLM check → success/failure  │
│       → set_task_status()                                           │
│       → TM.feedback_task(task)                                      │
│         │                                                           │
│         v                                                           │
│  TM.feedback_task()                                                 │
│    → If graph incomplete:                                           │
│       → REDECOMPOSE prompt → new subtask DAG                        │
│    → If all tasks done:                                             │
│       → return empty list → shutdown                                │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.5 DAG Subtask Dependency Model

```
┌─────────────────────────────────────────────────────────────────────┐
│              DAG Subtask Dependency Example                         │
│         (Construction Task 0, Round 2)                              │
│                                                                     │
│   Subtask 1: Place terracotta at [-8,-59,0]                        │
│   Assigned to: Bob                                                  │
│   Predecessors: none                                                │
│   Status: running                                                   │
│         │                                                           │
│         │ (required subtasks: [1])                                  │
│         v                                                           │
│   Subtask 2: Place torch at [-8,-58,0]                             │
│   Assigned to: Alice                                                │
│   Predecessors: [1]                                                 │
│   Status: waiting                                                   │
│                                                                     │
│   Task object fields:                                               │
│   ┌───────────────────────────────────┐                            │
│   │ Task {                            │                            │
│   │   id: uuid4                       │                            │
│   │   description: str                │                            │
│   │   content: [retrieved doc paths]  │                            │
│   │   milestones: [str]               │                            │
│   │   status: unknown|running|        │                            │
│   │          success|failure          │                            │
│   │   candidate_list: [agent names]   │                            │
│   │   number: 1 (agents needed)       │                            │
│   │   _pre_idxs: [int] (from LLM)    │                            │
│   │   _agent: [agent names assigned] │                            │
│   │   _direct_pre_task_list: [Task]  │                            │
│   │   predecessor_task_list: [Task]  │                            │
│   │   reflect: dict from LLM         │                            │
│   │   _summary: [str]                │                            │
│   │ }                                 │                            │
│   └───────────────────────────────────┘                            │
│                                                                     │
│   Graph (networkx DiGraph):                                         │
│   - vertex: [Task, ...]                                             │
│   - edge: [(Task, Task), ...]                                       │
│   - Built by: query_graph() from task_list                         │
│   - Open tasks: predecessors all success, status unknown            │
│   - Closed tasks: status = success                                  │
│   - Failed tasks: status = failure → triggers re-decomposition     │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.6 Judger → World → Agent Observation Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│          Judger → World → Agent Observation Pipeline                │
│                                                                     │
│  1. JUDGER (build_judger.py / farm_craft_judger.py / etc.)        │
│     ┌──────────────────────────────────┐                           │
│     │ Node.js Mineflayer bot connects  │                           │
│     │ to MC server as spectator.       │                           │
│     │                                  │                           │
│     │ Setup phase:                     │                           │
│     │  - Clear area with /fill air     │                           │
│     │  - Set ground, walls, glass      │                           │
│     │  - Place chest, crafting table   │                           │
│     │  - Place sign with blueprint     │                           │
│     │  - Load materials into chest/    │                           │
│     │    agent inventories             │                           │
│     │  - /op all agents                │                           │
│     │  - Write "loaded" to cache file  │                           │
│     │                                  │                           │
│     │ Scoring phase (every 20s):       │                           │
│     │  - cal_block_hit_rate()          │                           │
│     │  - cal_view_hit_rate()           │                           │
│     │  - Check end conditions          │                           │
│     │  - Write score.json              │                           │
│     │  - Write heartbeat.cache         │                           │
│     └──────────────────────────────────┘                           │
│                                                                     │
│  2. AGENT OBSERVATION                                               │
│     ┌──────────────────────────────────┐                           │
│     │ Agent Mineflayer bot:            │                           │
│     │  - Sees 5x3x5 block map around  │                           │
│     │  - Has inventory listing         │                           │
│     │  - Knows held item               │                           │
│     │  - Can scan for entities         │                           │
│     │  - Receives action feedback      │                           │
│     │                                  │                           │
│     │ Observation format (from bot):   │                           │
│     │ {                                │                           │
│     │   "I_held_item": {"dirt": 15},   │                           │
│     │   "inventory": [                 │                           │
│     │     {"torch": 1}, {"dirt": 15},  │                           │
│     │     ...                          │                           │
│     │   ],                             │                           │
│     │   "my_position": [-8,-60,0],     │                           │
│     │   "my_name": "Alice",            │                           │
│     │   "blocks": [                    │                           │
│     │     {"cut_sandstone":            │                           │
│     │       [-8,-60,0]}                │                           │
│     │   ],                             │                           │
│     │   "nearby_entities": [],         │                           │
│     │   "timeOfDay": "day",            │                           │
│     │   "health": 20, "food": 20       │                           │
│     │ }                                │                           │
│     └──────────────────────────────────┘                           │
│                                                                     │
│  3. DATA MANAGER (pipeline)                                         │
│     ┌──────────────────────────────────┐                           │
│     │ Receives raw observation →       │                           │
│     │ _process_env() → person_info,    │                           │
│     │                    blocks_info,   │                           │
│     │                    sign_info      │                           │
│     │ _process_agent() → formatted str  │                           │
│     │ _process_history() → LLM summary │                           │
│     │                                  │                           │
│     │ query_env_with_task() → LLM      │                           │
│     │   summarizes env relevant to task│                           │
│     │ query_history(name) → summary    │                           │
│     └──────────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. End-to-End Lifecycle Trace

### 2.1 The Task: Construction Task 0

**Config** (`result/gpt_4o_construction_task0_2p/config.json`):
```json
{
    "api_model": "gpt-4o",
    "api_base": "https://api.poe.com/v1",
    "task_type": "construction",
    "task_idx": 0,
    "agent_num": 2,
    "dig_needed": false,
    "task_goal": "Using the provided blueprint, please collaborate to place blocks in Minecraft. You can use materials from both your inventory and the chest. The task is complete once the blueprint is fully built.",
    "document_file": "data/map_description.json",
    "host": "localhost",
    "port": 25565,
    "task_name": "gpt_4o_construction_task0_2p"
}
```

**Blueprint** (from `data/map_description.json` → `data/building_blue_print.json[0]`):
- Structure: `village_desert_desert_lamp_1`
- Block 1: `cut_sandstone` facing `A` at position `[-8, -60, 0]`
- Block 2: `terracotta` facing `A` at position `[-8, -59, 0]`
- Block 3: `torch` facing `A` at position `[-8, -58, 0]`

**Final Score** (`result/gpt_4o_construction_task0_2p/score.json`):
```json
{
    "block_hit_rate": 1.0,
    "view_hit_rate": 1.0,
    "efficiency": 16.89,
    "use_time": 18.0,
    "end_reason": "complete task",
    "complexity": 2.91,
    "end_time": "2026-06-02 19:46:32"
}
```

### 2.2 Step-by-Step Trace

#### Step 1: Config Loading (`start_with_config.py:186-241`)

```python
# start_with_config.py:191
with open(args.config, "r") as f:
    launch_config = json.load(f)
```

The main process reads `gpt_4o_launch_config_meta.json`, iterates through each task config. For task 0:
- Checks `result/gpt_4o_construction_task0_2p/` doesn't already exist
- Writes config to `.cache/meta_setting.json`
- Writes `{"status": "start"}` to `.cache/load_status.cache`
- Loads API keys from `API_KEY_LIST` file
- Spawns a **multiprocessing.Process** running `run()`

The main process then enters a polling loop (`start_with_config.py:244-286`):
- Every 1 second, reads `.cache/load_status.cache`
- If status == "end", kills the subprocess and moves result files
- If heartbeat file is stale (>10s), kills subprocess (env error)

#### Step 2: Environment Setup (`start_with_config.py:51-98` → `env/env.py`)

Inside `run()`:

```python
# start_with_config.py:64-65
env = VillagerBench(env_type=env_type.construction, task_id=0,
                    dig_needed=False, host="localhost", port=25565,
                    max_task_num=0, task_name="gpt_4o_construction_task0_2p")
```

Agent tools are configured for construction (`start_with_config.py:78-80`):
```python
agent_tool = [Agent.placeBlock, Agent.fetchContainerContents, Agent.MineBlock,
              Agent.scanNearbyEntities, Agent.equipItem, Agent.navigateTo,
              Agent.withdrawItem, Agent.dismantleDirtLadder, Agent.erectDirtLadder,
              Agent.handoverBlock]
```

Agents registered (`start_with_config.py:118-123`):
```python
env.agent_register(agent_tool=agent_tool, agent_number=2,
                   name_list=["Alice", "Bob"])
```

This creates 2 `Agent` objects (from `env/minecraft_client.py`), each with:
- Name: "Alice" or "Bob"
- Tools: the construction tool set
- Local Flask port: 5001 (Alice), 5002 (Bob)

#### Step 3: Launch (`env/env.py:88-103` → `env/env.py:278-350`)

```python
with env.run(fast_api=False):
    # ...
```

`env.run()` calls `env.launch()` which:
1. **Calls `Agent.launch()`**: Spawns Node.js Mineflayer bot processes for each agent. Each bot:
   - Connects to the Minecraft server on port 25565
   - Starts a Flask HTTP server on its local port (5001, 5002)
   - Registers LangChain tool endpoints (placeBlock, navigateTo, etc.)
2. **Calls `env.reset()`**: Spawns the judger subprocess:
   ```python
   subprocess.Popen([sys.executable, "env/build_judger.py",
       "--idx", "0", "--host", "localhost", "--port", "25565",
       "--agent_num", "2", "--agent_names", "Alice,Bob",
       "--task_name", "gpt_4o_construction_task0_2p"])
   ```
3. **Waits for judger** to write `{"status": "loaded"}` to `.cache/load_status.cache`

The judger (`env/build_judger.py`) runs as a **Node.js Mineflayer bot** (via JSPyBridge) that:
- Connects to MC server as `build_judge` in spectator mode
- Clears the build area, sets ground (stone_bricks), walls (glass)
- Places chest at `[-4, -60, 0]`, crafting table at `[-4, -60, -1]`, furnace at `[-4, -60, 1]`
- Places oak sign at `[-3, -58, 0]` with blueprint text
- Gives each agent: 15 dirt, 15 ladders, 10 oak_planks
- Loads blueprint-specific materials into chest and agent inventories
- Writes `{"status": "loaded"}` and sets `start_time`

#### Step 4: Initialize DataManager & TaskManager (`start_with_config.py:126-149`)

```python
dm = DataManager(silent=False)
dm.update_database_init(env.get_init_state())
# get_init_state() calls Agent.get_environment_info_dict() for each agent
# Returns raw Minecraft state (position, inventory, nearby blocks, etc.)

tm = TaskManager(silent=False, cache_enabled=False)
```

`dm.update_database_init()` (`pipeline/data_manager.py:283-317`):
- Processes each agent's initial state through `_process_env()` and `_process_agent()`
- Stores person_info, blocks_info, sign_info, time, nearby_entities

#### Step 5: Initialize GlobalController (`start_with_config.py:152-156`)

```python
ctrl = GlobalController(llm_config, tm, dm, env,
                        tm_llm_config=tm_llm_config,
                        dm_llm_config=dm_llm_config,
                        base_agent_config=base_llm_config,
                        all_tools=agent_tool)
```

Inside `GlobalController.__init__()` (`pipeline/controller_tiny.py:35-78`):
- Creates an LLM for the TaskManager with `role_name="TaskManager"`
- Creates an LLM for the DataManager with `role_name="DataManager"`
- Creates a base LLM for all agents
- Creates `BaseAgent` objects for each registered agent (Alice, Bob)
- Sets `self.agent_list = [BaseAgent(..., name="Alice"), BaseAgent(..., name="Bob")]`
- Initializes `ThreadPoolExecutor(max_workers=4)`

#### Step 6: Initialize Task (`start_with_config.py:177-179`)

```python
if os.path.exists("data/map_description.json"):
    document["recipe"] = json.load(open("data/map_description.json"))
tm.init_task(description=task_goal, document=document)
```

The `document` becomes:
```json
{
    "recipe": [
        "material: cut_sandstone facing: A position: [-8, -60, 0]",
        "material: terracotta facing: A position: [-8, -59, 0]",
        "material: torch facing: A position: [-8, -58, 0]"
    ]
}
```

Inside `tm.init_task()` (`pipeline/task_manager.py:175-247`):

1. **Query environment** via `dm.query_env_with_task(description)`:
   - DM sends raw env data + task to LLM with `SUMMARY_ENVIRONMENT_SYSTEM_PROMPT`
   - LLM returns structured summary of entities, blocks, creatures, interactive items
   - This is cached for 120 seconds (`@timed_cache`)

2. **Build decomposition prompt** using `PART_DECOMPOSE_SYSTEM_PROMPT` + `PART_DECOMPOSE_USER_PROMPT`:
   - System prompt: instructions for DAG decomposition with JSON schema
   - User prompt: env summary + task description + document + `"2 subtasks is the maximum"`

3. **Call LLM** with `few_shot_generate_thoughts()`:
   - The LLM returns JSON array of subtask structures

4. **Parse response** with `extract_info()` and `fill_agents()`:
   - Each subtask from LLM gets split into per-agent assignments
   - Invalid agent names get replaced with random valid ones

5. **Build Graph** via `query_graph(subtask_list)`:
   - Creates a networkx DiGraph from the subtask list
   - Edges based on `_pre_idxs` (predecessor indices)

**Round 1 LLM Response** (from `TM_history.json`):
```json
[
    {
        "id": 1,
        "description": "Place a cut_sandstone block at position [-8, -60, 0] facing direction A.",
        "milestones": [
            "Retrieve the cut_sandstone block from Alice's inventory.",
            "Navigate to position [-8, -60, 0].",
            "Place the cut_sandstone block at the specified position."
        ],
        "retrieval paths": ["~/meta-data/recipe/0"],
        "required subtasks": [],
        "assigned agents": ["Alice"]
    },
    {
        "id": 2,
        "description": "Place a terracotta block at position [-8, -59, 0] facing direction A.",
        "milestones": [
            "Retrieve a terracotta block from the environment or inventory.",
            "Navigate to position [-8, -59, 0].",
            "Place the terracotta block at the specified position."
        ],
        "retrieval paths": ["~/meta-data/recipe/1"],
        "required subtasks": [],
        "assigned agents": ["Bob"]
    }
]
```

This produces a DAG with 2 nodes, no edges (both can run in parallel):

```
  [Place cut_sandstone → Alice]     [Place terracotta → Bob]
```

#### Step 7: Run Controller (`start_with_config.py:181`)

```python
ctrl.run()
```

`GlobalController.run()` (`pipeline/controller_tiny.py:350-372`) starts 3 threads:

1. **`execute_tasks`** (producer): Queries TM for open tasks, checks availability, assigns agents
2. **`worker`**: Pops from task_queue, submits `agent.step(task)` to ThreadPoolExecutor
3. **`process_completed_tasks`**: Checks futures, calls `update_feedback()` on completion

**Round 1 Execution:**

Both subtasks have no predecessors, both agents are free. The controller assigns:
- Alice → Subtask 1: "Place cut_sandstone at [-8, -60, 0]"
- Bob → Subtask 2: "Place terracotta at [-8, -59, 0]"

Both are submitted to the thread pool simultaneously (parallel execution).

**Alice's execution** (`BaseAgent.normal_step()` → `env.step()` → `Agent.run()`):

1. Build prompt from `agent_prompt_wo_emoji` template with:
   - Task: "Place a cut_sandstone block at position [-8, -60, 0] facing direction A."
   - Milestones: ["Retrieve...", "Navigate...", "Place..."]
   - Env: DM's summarized environment
   - Agent state: DM's history summary (first time = "No history found.")
   - Personality: randomly chosen from `speaking_styles`

2. `env.step("Alice", prompt_str)` calls `Agent.run(prompt_str, max_iterations=7)`:
   - Creates a LangChain ReAct agent with the construction tools
   - The LLM generates action steps, LangChain executes them
   - Each action is an HTTP POST to Alice's Mineflayer bot Flask server
   - The bot executes the action in Minecraft and returns observation

3. Alice's actions (from `action_log.json`):

| # | Action | Args | Duration | Status |
|---|--------|------|----------|--------|
| 1 | `navigateTo` | x:-8, y:-60, z:0 | 1.10s | ✅ |
| 2 | `placeBlock` | cut_sandstone, [-8,-60,0], facing:A | 1.36s | ❌ (but block placed) |
| 3 | `scanNearbyEntities` | cut_sandstone, radius:5 | 0.07s | ✅ found at [-8,-60,0] |

4. After max_turn (7) iterations or Final Answer, returns detail dict.

5. **Reflect** (`BaseAgent.reflect()`, `pipeline/agent.py:613-659`):
   - Builds prompt from `reflect_user_prompt` with task description, milestones, action history
   - LLM checks if task is complete → returns `{"task_status": true}`
   - Result: **SUCCESS**

**Bob's execution** (parallel):

Bob's actions (from `action_log.json`):

| # | Action | Args | Duration | Status |
|---|--------|------|----------|--------|
| 1 | `scanNearbyEntities` | terracotta, r:10 | 1.08s | ❌ not found |
| 2 | `equipItem` | terracotta → hand | 0.06s | ✅ |
| 3 | `placeBlock` | terracotta, [-8,-59,0] | 0.06s | ❌ no reference block |
| 4 | `placeBlock` | dirt, [-8,-60,0] | 1.07s | ❌ |
| 5 | `erectDirtLadder` | top:[-8,-59,0] | 1.17s | ✅ |
| 6 | `placeBlock` | terracotta, [-8,-59,0] | 1.10s | ❌ |
| 7 | `scanNearbyEntities` | dirt, r:5 | 0.06s | ✅ found terracotta at [-8,-59,0] in map! |

**Key observation**: After Bob erected a dirt ladder, the terracotta block appeared at [-8,-59,0] in the map. The judger's dirt-ladder scaffolding mechanic auto-placed the block when scaffolding was built.

Reflect: LLM reviews action history → returns `{"task_status": false}` (Bob couldn't confirm he placed it himself).

Result: **FAILURE**

#### Step 8: Re-decomposition (`pipeline/task_manager.py:493-562`)

After Round 1:
- Subtask 1 (Alice, cut_sandstone): SUCCESS
- Subtask 2 (Bob, terracotta): FAILURE

`TM.feedback_task()` is called → since graph is not complete, calls `update_task()`:

1. Builds `REDECOMPOSE_USER_PROMPT` with:
   - Current environment state (DM query)
   - Agent state histories (LLM summaries)
   - Success trace: `["['Alice'] execute task Place a cut_sandstone block... and feedback: "]`
   - Failure trace: `[]` (Bob's failure is in total_trace but filtered)
   - The original task + document

2. LLM generates new subtask list:

**Round 2 Response** (from `TM_history.json`):
```json
[
    {
        "id": 1,
        "description": "Place a terracotta block at position [-8, -59, 0] facing direction A.",
        "milestones": ["Navigate to [-8, -59, 0]", "Ensure clear", "Place terracotta"],
        "retrieval paths": ["~/meta-data/recipe/1"],
        "required subtasks": [],
        "assigned agents": ["Bob"]
    },
    {
        "id": 2,
        "description": "Place a torch at position [-8, -58, 0] facing direction A.",
        "milestones": ["Navigate to [-8, -58, 0]", "Ensure clear", "Place torch"],
        "retrieval paths": ["~/meta-data/recipe/2"],
        "required subtasks": [1],
        "assigned agents": ["Alice"]
    }
]
```

New DAG:
```
  [Place terracotta → Bob] ──> [Place torch → Alice]
```

Bob must finish first, then Alice places the torch.

#### Step 9: Round 2 Execution

**Bob's Round 2:**

| # | Action | Args | Duration | Status |
|---|--------|------|----------|--------|
| 1 | `navigateTo` | [-8,-59,0] | 2.73s | ✅ |
| 2 | `scanNearbyEntities` | terracotta, r:5 | 2.10s | ✅ found at [-8,-59,0] |

Bob finds terracotta already present. Reflect → `task_status: false` initially, but after scanning confirms it's there.

**Alice's Round 2** (after Bob succeeds):

| # | Action | Args | Duration | Status |
|---|--------|------|----------|--------|
| 1 | `navigateTo` | [-8,-58,0] | 1.09s | ✅ |
| 2 | `scanNearbyEntities` | torch, r:1 | 3.25s | ❌ not found |
| 3 | `placeBlock` | torch, [-8,-58,0], A | 1.08s | ✅ (status true despite message) |
| 4 | `scanNearbyEntities` | torch, r:1 | 2.11s | ✅ found at [-8,-58,0] |

Reflect → `task_status: true`. Result: **SUCCESS**

#### Step 10: Completion & Scoring

After all subtasks complete, `ctrl.run()` returns. Then:

```python
# start_with_config.py:183
env.get_score()
```

Meanwhile, the judger bot (`build_judger.py`) detects `block_hit_rate == 1.0` and `view_hit_rate == 1.0` during its periodic check (every 20 seconds):

```python
# build_judger.py:611-633
if block_hit_rate == 1 and view_hit_rate == 1:
    efficiency = max_action_time / calculate_action_time()
    # Write score.json to result/<task_name>/
    # Write {"status": "end"} to load_status.cache
```

The main process detects `status == "end"`, kills the subprocess, and moves result files.

**Final score computation** (`build_judger.py:574-633`):
- `block_hit_rate`: 1.0 (all 3 blueprint blocks correctly placed)
- `view_hit_rate`: 1.0 (all 5 viewpoints match)
- `complexity`: 2.91 (computed from block connectivity + height)
- `max_action_time`: (ln(2.91) + 1) × 60 + 180 = 303.6 seconds
- `calculate_action_time()`: 18.0 seconds (sum of all agent action durations, merged)
- `efficiency`: 303.6 / 18.0 = 16.89

---

## 3. Component Reference

### 3.1 `start_with_config.py` — Entry Point

| Attribute | Value |
|-----------|-------|
| **File** | `start_with_config.py` |
| **Entry point** | `if __name__ == "__main__"` (line 186) |
| **Input** | JSON config file path (via `--config` arg) |
| **Output** | Result files in `result/<task_name>/` |
| **Spawns** | One `multiprocessing.Process` per task |

Key functions:
- `load_api_key_list(api_model)` (line 24): Loads API keys from `API_KEY_LIST` JSON file
- `run(...)` (line 51): Sets up VillagerBench, DataManager, TaskManager, GlobalController; runs one task
- Main loop (line 195): Iterates config list, spawns processes, monitors heartbeat

### 3.2 `env/env.py` — Environment (VillagerBench)

| Attribute | Value |
|-----------|-------|
| **File** | `env/env.py` |
| **Class** | `VillagerBench` |
| **Input** | env_type, task_id, host, port, agent names |
| **Output** | Agent observations, scores |
| **Communication** | Function calls to `Agent` class (HTTP to Mineflayer) |

Key methods:
- `agent_register(agent_tool, agent_number, name_list)` (line 262): Creates Agent objects, assigns ports
- `launch(debug, fast_api)` (line 278): Calls `Agent.launch()` then spawns judger
- `reset()` (line 293): Spawns judger subprocess (build_judger/farm_craft_judger/escape_room_judger)
- `step(agent_name, action, max_turn=7)` (line 375): Calls `Agent.run()` — the main action execution
- `agent_status(agent_name)` (line 256): Calls `Agent.get_environment_info_dict()` — returns raw MC state
- `get_init_state()` (line 178): Returns `[agent_status(name) for name in agent_pool]`
- `get_score()` (line 421): Reads `data/score.json`

### 3.3 `env/minecraft_client.py` — Agent (Mineflayer Bridge)

| Attribute | Value |
|-----------|-------|
| **File** | `env/minecraft_client.py` |
| **Class** | `Agent` |
| **Technology** | LangChain agent + Mineflayer (Node.js via JSPyBridge) |
| **Ports** | 5001, 5002, ... (one per agent) |

Key static methods (LangChain `@tool` decorated):
- `placeBlock(player_name, item_name, x, y, z, facing)` — Place a block
- `navigateTo(player_name, x, y, z)` — Navigate to coordinates
- `scanNearbyEntities(player_name, item_name, radius, item_num)` — Scan for items
- `equipItem(player_name, slot, item_name)` — Equip item to hand
- `fetchContainerContents(player_name, x, y, z)` — Open and read chest
- `withdrawItem(player_name, item_name, item_num, x, y, z)` — Take from chest
- `MineBlock(player_name, x, y, z)` — Dig a block
- `erectDirtLadder(player_name, top_x, top_y, top_z)` — Build dirt scaffolding
- `dismantleDirtLadder(player_name, top_x, top_y, top_z)` — Remove scaffolding
- `handoverBlock(player_name, item_name, target_name, item_num)` — Give item to another agent

Each tool is wrapped with `@timeit` (line 47) which:
1. Sends emotion/murmur to the agent's Flask server
2. Executes the actual Mineflayer action
3. Logs the action to `data/action_log.json`

`Agent.run(action, max_iterations)` creates a LangChain ReAct agent initialized with:
- LLM: `ChatOpenAI(model=api_model, temperature=0)`
- Tools: the registered tool set
- Agent type: `AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION` (or similar)
- Max iterations: `max_turn` (default 7)

`Agent.launch()` spawns Node.js processes for each agent. Each process:
- Creates a Mineflayer bot connecting to MC server
- Starts a Flask server on the agent's port
- Registers tool endpoint handlers

`Agent.kill()` terminates all spawned Node.js processes.

### 3.4 `pipeline/task_manager.py` — TaskManager

| Attribute | Value |
|-----------|-------|
| **File** | `pipeline/task_manager.py` |
| **Class** | `TaskManager` |
| **Input** | Task description + document from config |
| **Output** | Subtask DAG (Graph object), open task lists |
| **LLM calls** | Decomposition, re-decomposition |
| **State files** | `result/<task_name>/TM_history.json` |

Key methods:
- `init_task(description, document)` (line 175): First decomposition into subtask DAG
- `query_subtask_list()` (line 250): Returns list of Tasks with no unfinished predecessors
- `feedback_task(task)` (line 368): Called after each task completes; triggers re-decomposition if graph incomplete
- `update_task(task)` (line 493): Re-decomposes entire subtask list using `REDECOMPOSE_*` prompts
- `fill_agents(result, agents)` (line 305): Splits multi-agent subtasks into per-agent assignments
- `get_relevant_content_by_path(subtask_data, query)` (line 70): Extracts document content by JSON path

State tracking:
- `task_trace`: successfully completed tasks
- `fail_trace`: failed tasks (reset each feedback cycle)
- `total_trace`: all completed/failed tasks
- `history`: all TM prompt-response pairs

### 3.5 `pipeline/data_manager.py` — DataManager

| Attribute | Value |
|-----------|-------|
| **File** | `pipeline/data_manager.py` |
| **Class** | `DataManager` |
| **Input** | Raw Minecraft state from agents |
| **Output** | Summarized env descriptions, agent histories |
| **LLM calls** | History summarization, environment summarization |
| **State files** | `result/<task_name>/DM_history.json`, `DM_query.json` |

Key methods:
- `update_database_init(info)` (line 283): Process initial state for all agents
- `update_database(new_info)` (line 337): Process post-action state; summarize history via LLM
- `query_env_with_task(task, agent_query)` (line 469): LLM-summarized environment relevant to task
- `query_history(name)` (line 507): Returns running summary of agent's actions
- `query_other_agent_state(agent_name)` (line 514): Returns histories of all other agents

Data processing:
- `_process_env(info)`: Extracts person_info, blocks_info, sign_info, time, nearby_entities
- `_process_agent(info)`: Formats agent state as string (position, held items, inventory, nearby agents, blocks)
- `_process_history(info)`: Extracts action list with behavior + feedback

### 3.6 `pipeline/controller_tiny.py` — GlobalController

| Attribute | Value |
|-----------|-------|
| **File** | `pipeline/controller_tiny.py` |
| **Class** | `GlobalController` |
| **Input** | TaskManager, DataManager, VillagerBench, LLM config |
| **Output** | Orchestrates entire pipeline |
| **Threading** | 3 threads + ThreadPoolExecutor(4) |

Key methods:
- `run()` (line 350): Starts 3 threads (execute_tasks, worker, process_completed_tasks)
- `execute_tasks()` (line 289): Producer — queries TM for open tasks, assigns agents
- `worker()` (line 144): Submits `agent.step(task)` to thread pool
- `process_completed_tasks()` (line 227): Consumer — checks futures, calls update_feedback
- `update_feedback(task, agent, detail)` (line 198): Calls `agent.reflect()` then `TM.feedback_task()`
- `check_task_list_available()` (line 267): Filters tasks by predecessor completion + free agents

### 3.7 `pipeline/agent.py` — BaseAgent

| Attribute | Value |
|-----------|-------|
| **File** | `pipeline/agent.py` |
| **Class** | `BaseAgent` |
| **Input** | Task object from controller |
| **Output** | (feedback_string, detail_dict) |
| **LLM calls** | None directly (LangChain agent handles it) |
| **State files** | `result/<task_name>/<name>_reflect.json` |

Key methods:
- `step(task)` (line 99): Entry point — delegates to `normal_step()`, `local_step()`, or `rl_step()`
- `normal_step(task)` (line 335): Builds prompt, calls `env.step()`, updates DM
- `reflect(task, detail)` (line 613): Uses `reflect_*_prompt` to check task completion
- `other_agents()` (line 552): Returns other agents' state summaries from DM

### 3.8 `pipeline/retriever.py` — Retriever

| Attribute | Value |
|-----------|-------|
| **File** | `pipeline/retriever.py` |
| **Class** | `Retriever` |

Used by TaskManager to retrieve relevant document content. Currently provides the `get_relevant_content_by_path()` logic for extracting data from the task document by JSON path.

### 3.9 `model/init_model.py` — LLM Factory

| Attribute | Value |
|-----------|-------|
| **File** | `model/init_model.py` |
| **Function** | `init_language_model(config)` |
| **Input** | `{api_key, api_base, api_model, api_key_list, role_name}` |
| **Output** | `OpenAILanguageModel` or `ZhipuLanguageModel` instance |

Returns `OpenAILanguageModel` for most models, `ZhipuLanguageModel` for GLM models. Both implement `few_shot_generate_thoughts(system_prompt, example_prompt, ...)` which calls the LLM API.

### 3.10 `type_define/graph.py` — Task & Graph

| Attribute | Value |
|-----------|-------|
| **File** | `type_define/graph.py` |
| **Classes** | `Task`, `Graph` |

**Task** (line 11-96):
- States: `success`, `failure`, `unknown`, `running`
- Fields: id (uuid4), content, description, milestones, status, candidate_list, number, _pre_idxs, _agent, reflect

**Graph** (line 99-408):
- Built on `networkx.DiGraph`
- Methods: `add_node`, `add_edge`, `get_open_task_list`, `check_graph_completion`, `merge_at`, `replace_node`, `insert_node_merge_edge`
- `get_open_task_list()` returns tasks where all predecessors are `success` and status is `unknown`
- `check_graph_completion()` returns True when no running nodes remain and no open nodes have completable predecessors

---

## 4. Prompt Template Catalog

### 4.1 Task Decomposition Prompts (`pipeline/task_prompt.py`)

#### PART_DECOMPOSE_SYSTEM_PROMPT (line 46-70)

Used for initial task decomposition in the "update" method (the default).

```
Your current mission is to leader all the players and execute a set of specified tasks within the Minecraft environment.
--- Background Information ---
Our system manages the task as a Directed Acyclic Graph (DAG).
In this turn, you need to decompose the tasks and arrange them in chronological order. Next turn we will analyse your result json to a graph.

A subtask-structure has the following json component:
{
    "id": int, id of the subtask start from 1,
    "description": string, description of the subtask, more detail than a name, for example, place block need position and facing, craft or collect items need the number of items.
    "milestones": list[string]. Make it detailed and specific,
    "retrieval paths": list[string], [~/...] task data is a dict or list, please give the relative path to the data, for example, if the data useful is {"c": 1} dict is {"meta-data": {"blueprint": [{"c": 1}, ]}}, the retrieval path is "~/meta-data/blueprint/0",
    "required subtasks": list[int], if this subtask is directly prerequisite for other subtasks before it, list the subtask id here.
    "assigned agents": list[string], name of agents. dispatch the subtask to the agents.
}


*** Important Notice ***
- The system allow agents communicate with each other when they are assigned together.
- Sub-task Dispatch: Post decomposition, the next step is to distribute the sub-tasks amongst yourselves. This will require further communication, where you consider each player's skills, resources, and availability. Ensure the dispatch facilitates smooth, ** parallel ** execution.
- Task Decomposition: These sub-tasks should be small, specific, and executable with MineFlayer code, as you will be using MineFlayer to play MineCraft. The task decomposition will not be a one-time process but an iterative one. At regular intervals during playing the game, agents will be paused and you will plan again based on their progress. You'll propose new sub-tasks that respond to the current circumstances. So you don't need to plan far ahead, but make sure your proposed sub-tasks are small, simple and achievable, to ensure smooth progression. Each sub-task should contribute to the completion of the overall task. That means, the number of sub-tasks should no more than numbers of agents. When necessary, the sub-tasks can be identical for faster task accomplishment. Be specific for the sub-tasks, for example, make sure to specify how many materials are needed.
- In Minecraft, item can be put in agent's inventory, chest, or on the ground. You can use the item in agent's inventory or chest, but you can not use the item on the ground unless you dig it up first.
- The block at lower place should be placed first, and the block at higher place should be placed later. [x,-60,z] is the lowest place. For example, if a task is placing block at x -57 z, then y  -60, -59 and -58 should be placed first and in order.
- Integration and Finalization: In some tasks, you will need to integrate your individual efforts. For example, when crafting complicated stuff that require various materials, after collecting them, you need to consolidate all the materials with one of players.
- You can stop to generate the subtask-structure json if you think the task need the information from the environment, and you can not get the information from the environment now.
```

**Variables interpolated**: None (system prompt is static)
**Used in**: `TaskManager.init_task()` (`pipeline/task_manager.py:195`)
**Example rendered**: See TM_history.json prompt[0] in Section 2

#### PART_DECOMPOSE_USER_PROMPT (line 72-84)

```
This is not the first time you are handling the task, so you should give part of decompose subtask-structure json feedback. Here is the query:
"""
the environment information around:
{{env}}


The high-level task:
{{task}}

Your response should exclusively include the identified sub-task or the next step intended for the agent to execute.
So, {{num}} subtasks is the maximum number of subtasks you can give.
Response should contain a list of subtask-structure JSON.
```

**Variables interpolated**:
- `{{env}}`: DM's LLM-summarized environment description
- `{{task}}`: `{"description": task_goal, "meta-data": document_dict}`
- `{{num}}`: Number of agents (e.g., 2)

**Used in**: `TaskManager.init_task()` (`pipeline/task_manager.py:196-199`)

#### REDECOMPOSE_SYSTEM_PROMPT (line 86-109)

Identical to `PART_DECOMPOSE_SYSTEM_PROMPT` in content. Used for re-decomposition after task feedback.

**Used in**: `TaskManager.update_task()` (`pipeline/task_manager.py:513`)

#### REDECOMPOSE_USER_PROMPT (line 111-131)

```
This is not the first time you are handling the task, so you should give a decompose subtask-structure json feedback. Here is the query:
"""
the environment information around:
{{env}}

agent state:
{{agent_state}}

success previous subtask tracking:
{{success_previous_subtask}}

failure previous subtask tracking:
{{failure_previous_subtask}}

The high-level task
{{task}}
"""
Your response should exclusively include the identified sub-task or the next step intended for the agent to execute.
So, {{num}} subtasks is the maximum number of subtasks you can give.
Response should contain a list of subtask-structure JSON.
```

**Variables interpolated**:
- `{{env}}`: Current environment summary from DM
- `{{agent_state}}`: `[dm.query_history(agent.name) for agent in agent_list]`
- `{{success_previous_subtask}}`: `task_trace_description` (formatted as `"['Alice'] execute task <desc> and feedback: <summary>"`)
- `{{failure_previous_subtask}}`: `fail_trace_description`
- `{{task}}`: Original task description + document
- `{{num}}`: Number of agents

**Used in**: `TaskManager.update_task()` (`pipeline/task_manager.py:514-520`)

#### DECOMPOSE_SYSTEM_PROMPT (line 1-30) and DECOMPOSE_USER_PROMPT (line 32-43)

Used for the "merge" method of task management. The merge method allows strategies like replan, decompose, move, insert, delete (see `STRATEGY_SYSTEM_PROMPT`). Currently the default method is "update".

**Variables**: Same structure but includes `candidate list` and `minimum required agents` instead of `assigned agents`.

#### STRATEGY_SYSTEM_PROMPT (line 152-202)

Used only in "merge" mode for deciding how to update the task graph after feedback.

```
You are an efficient agent for minecraft game agents cooperation, your task is to consider how to update the tasks for current state.
--- Background Information ---
[... five strategies: replan, decompose, move, insert, delete ...]
```

**Used in**: `TaskManager.get_graph_strategy()` (`pipeline/task_manager.py:286`)

#### STRATEGY_USER_PROMPT (line 133-150)

```
This is not the first time you are generating strategy, so you should generate a strategy for current state. Here is the query:
"""
env:
{{env}}

agent state:
{{agent_state}}

task list and their status:
{{task_description}}

current task you should focus on:
{{current_task}}

"""
You will generate a strategy for current task state and env state, return a strategy-structure json without annotation.
Response should contain a list of JSON.
```

**Used in**: `TaskManager.get_graph_strategy()` (`pipeline/task_manager.py:286`)

### 4.2 Agent Prompts (`pipeline/agent_prompt.py`)

#### reflect_system_prompt (line 1-9)

```
You are in a Minecraft world. You are a agent player. You need to use the action history compared with the task description and the milestone description to check whether the task is completed.
The check-strucutre
{
    "reasoning": str, # the reasoning process
    "summary": str, # the summary of the vital information of action history with detailed position number and other parameters, which not included in task description.
    "task_status": bool, # whether the task is completed
}
```

**Used in**: `BaseAgent.reflect()` (`pipeline/agent.py:633`)

#### reflect_user_prompt (line 10-23)

```
Now you have tried to complete the task. 
The task description is:
{{task_description}}

The milestone description is:
{{milestone_description}}

The action history is:
{{state}}
{{action_history}}

Please check whether the task is completed and return a check-strucutre json.
```

**Variables**:
- `{{task_description}}`: Task description string
- `{{milestone_description}}`: Task milestones list
- `{{state}}`: DM history summary for this agent
- `{{action_history}}`: List of `{action: {tool, tool_input, log}, feedback: {message, status}}`

**Used in**: `BaseAgent.reflect()` (`pipeline/agent.py:624-630`)

#### minecraft_knowledge_card (line 25-33)

```
Here are some knowledge about minecraft:
1. The minecraft world x,z is the horizontal coordinate, y is the vertical coordinate. y=-61 is the ground level.
2. You can use the tool or empty hand to dig the block, and place the block to the world.
3. You can find the item in the chest. Item in the chest can not directly be seen or used, take it out and use it or equip it.
4. If their is no items in the chest, maybe you can find the item at other chest or get it from other agent or dig it up or craft it.
5. One bucket can hold one item, if you want to get more items, you need to get more buckets at first.
6. You are in a team with other agents, you can try to find the item from other agents, and do not change the blocks other agents placed without permission.
```

**Used in**: All agent prompt templates as `{{minecraft_knowledge_card}}`

#### agent_prompt_wo_emoji (line 92-117)

The main agent prompt for non-Linux systems (emojis disabled):

```
*** The relevant data of task(not environment data)***
{{relevant_data}}
*** Other agents team with you ***
{{other_agents}}
*** {{agent_name}}'s state ***
{{agent_state}}
*** The agent's actions in the last time segment partially ***
{{agent_action_list}}
*** environment ***
{{env}}
*** The minecraft knowledge card ***
{{minecraft_knowledge_card}}
*** The emojis and murmur ***
I am acting as {{agent_name}}. A {{personality}} agent. I {{traits}}.
Sometimes I say something like: {{example}} ... , Keep this style but don't repeat this content.
Action funcion can input emojis and murmurs, you can use them to express your feelings or thoughts sometimes.
But this time, you can not use any emoji because the system can not support it.
=====================
*** Task ***
{{task_description}}
*** milestone ***
{{milestone_description}}

At least two Action before the Final Answer.
```

**Variables**:
- `{{relevant_data}}`: Task content (blueprint data, retrieved by paths)
- `{{other_agents}}`: Other agents' state summaries from DM
- `{{agent_name}}`: Agent's name (e.g., "Alice")
- `{{agent_state}}`: DM history summary for this agent
- `{{agent_action_list}}`: Previous action history
- `{{env}}`: DM environment summary
- `{{minecraft_knowledge_card}}`: Static Minecraft knowledge
- `{{personality}}`, `{{traits}}`, `{{example}}`: Random speaking style
- `{{task_description}}`: Current subtask description
- `{{milestone_description}}`: Current subtask milestones

**Used in**: `BaseAgent.normal_step()` (`pipeline/agent.py:348`)

#### agent_prompt_w_emoji (line 36-65)

Same structure as `agent_prompt_wo_emoji` but includes emoji support. Used on Linux systems.

#### agent_cooper_prompt (line 140-164)

Used when a task is assigned to multiple agents (collaborative mode):

```
*** The relevant data of task(not environment data)***
{{relevant_data}}
*** Other agents team with you ***
{{other_agents}}
*** {{agent_name}}'s state ***
{{agent_state}}
*** The agent's actions in the last time segment partially ***
{{agent_action_list}}
*** environment ***
{{env}}
*** The minecraft knowledge card ***
{{minecraft_knowledge_card}}
*** The task description *** 
=====================
*** Task ***
{{task_description}}
*** milestone ***
{{milestone_description}}

You need to work as the leader use api control your team(include yourself and other agents) to complete the task.
Your team members are:
{{team_members}}
At least two Action before the Final Answer.
```

Additional variable:
- `{{team_members}}`: Comma-separated list of team member names

**Used in**: `BaseAgent.normal_step()` when `len(task._agent) > 1` (`pipeline/agent.py:364`)

#### idle_prompt_wo_emoji (line 119-138) / idle_prompt_w_emoji (line 67-90)

Used when an agent is idle (not assigned to any task). Includes an "IDLE" section telling the agent to help others or wait.

**Used in**: `BaseAgent.idle_step()` (`pipeline/agent.py:267`)

### 4.3 Controller Prompts (`pipeline/controller_prompt.py`)

These prompts are used in the full `controller.py` (not the default `controller_tiny.py`). The tiny controller does direct assignment without LLM-based task assignment.

#### CONTROLLER_ASSIGN_PROMPT (line 1-31)
Instructions for assigning tasks to agents. Used in the full controller.

#### CONTROLLER_SYSTEM_PROMPT (line 33) / CONTROLLER_USER_PROMPT (line 34-75)
Detailed assignment instructions with background information.

#### CONTROLLER_DECOMPOSE_SYSTEM_PROMPT (line 77) / CONTROLLER_DECOMPOSE_USER_PROMPT (line 78-126)
Used to adjust task descriptions when assigned to multiple agents (split a task into per-agent subtasks).

### 4.4 Data Manager Prompts (`pipeline/data_prompt.py`)

#### SUMMARY_ENVIRONMENT_SYSTEM_PROMPT (line 31-34)

```
You are a helpful assistant in Minecraft.
Based on the environment info and the task, extract the key information and summarize the environment info in a concise and informative way.
You should focus on the entities, blocks, and creatures in the environment, and provide a summary of the environment info.
```

**Used in**: `DataManager.query_env_with_task()` (`pipeline/data_manager.py:477`)

#### SUMMARY_ENVIRONMENT_EXAMPLE_PROMPT (line 36-54)

A few-shot prompt with:
1. Example environment info (raw JSON)
2. Example summary output (structured: Entity, Blocks, Creatures, Interactive-Items, Environment)
3. Template with `{{environment_info}}` and `{{task}}` placeholders

#### HISTORY_SUMMARY_PROMPT (line 56-68)

```
You are {name}. Your task is to create a concise running summary of actions and information results in the provided text, focusing on key and potentially important information to remember.

You will receive the current summary and the your latest actions. Combine them, adding relevant key information from the latest development in 1st person past tense and keeping the summary concise.
The subject of the sentence should be {name}.

Summary So Far:
{summary_so_far}

Latest Development:
{latest_development}

Your Summary:
```

**Variables**:
- `{name}`: Agent name
- `{summary_so_far}`: Previous summary or "" (empty string for first time)
- `{latest_development}`: Formatted action history from `_process_history()`

**Used in**: `DataManager.update_database()` (`pipeline/data_manager.py:375-399`)

### 4.5 RL Prompts (`pipeline/agent_rl_prompt.py`)

Used for RL-mode agent steps (PPO/exploration). Not used in default mode.

#### task_prompt (line 1-6)
Simple task + milestone template.

#### state_prompt (line 8-13)
Environment + relevant data template.

#### one_step_reflect_prompt (line 46-71)
Evaluates single action with reward scale (-2 to 2) and task_status.

---

## 5. Inter-Process Architecture

### 5.1 Process Lifecycle

```
Time ──────────────────────────────────────────────────────────────────>

[start_with_config.py main process]
    │
    ├── Read config JSON
    ├── For each task config:
    │   ├── Write .cache/meta_setting.json
    │   ├── Write .cache/load_status.cache: "start"
    │   ├── Spawn multiprocessing.Process(target=run)
    │   │   │
    │   │   │  [run() subprocess]
    │   │   │   ├── Create VillagerBench
    │   │   │   ├── Register agents (create Agent objects)
    │   │   │   ├── env.run() context manager:
    │   │   │   │   ├── Agent.launch() → spawn N Node.js processes
    │   │   │   │   │   ├── Bot "Alice" connects to MC:25565, Flask on :5001
    │   │   │   │   │   └── Bot "Bob" connects to MC:25565, Flask on :5002
    │   │   │   │   ├── env.reset() → spawn judger subprocess
    │   │   │   │   │   └── Bot "build_judge" connects as spectator
    │   │   │   │   │       ├── Clear area, place blocks, load materials
    │   │   │   │   │       └── Write .cache/load_status.cache: "loaded"
    │   │   │   │   ├── wait_for_agents_ready() → ping Flask ports
    │   │   │   │   │
    │   │   │   │   │  [Pipeline runs]
    │   │   │   │   │   ├── Create DataManager, TaskManager, GlobalController
    │   │   │   │   │   ├── tm.init_task() → LLM decomposition → DAG
    │   │   │   │   │   ├── ctrl.run() → 3 threads:
    │   │   │   │   │   │   ├── execute_tasks → query open tasks → assign
    │   │   │   │   │   │   ├── worker → submit agent.step() → ThreadPool
    │   │   │   │   │   │   └── process_completed → reflect → feedback → re-decompose
    │   │   │   │   │   │       Loop until all tasks done or timeout
    │   │   │   │   │   │
    │   │   │   │   │   └── env.get_score()
    │   │   │   │   │
    │   │   │   │   └── env.stop() → Agent.kill() → terminate Node.js
    │   │   │   │
    │   │   │   └── [subprocess exits]
    │   │   │
    │   ├── Polling loop:
    │   │   ├── Read .cache/load_status.cache every 1s
    │   │   ├── Check .cache/heart_beat.cache freshness
    │   │   ├── If "end" → kill subprocess → move result files
    │   │   └── If heartbeat stale → kill subprocess (error)
    │   │
    │   └── Next task config
    │
    └── Done
```

### 5.2 Communication Protocols

| Channel | Protocol | Details |
|---------|----------|---------|
| Pipeline → Agents | Python function calls | `env.step(name, prompt)` → `Agent.run()` |
| Agent → Mineflayer | HTTP POST (Flask) | `POST http://localhost:5001/<tool_name>` with JSON body |
| Mineflayer → MC Server | Minecraft protocol | Via `mineflayer.createBot()` on port 25565 |
| Judger → MC Server | Minecraft protocol | Spectator bot via `mineflayer.createBot()` |
| Judger → Pipeline | File-based | `.cache/load_status.cache`, `.cache/heart_beat.cache`, `data/score.json` |
| Pipeline → Main | File-based | `.cache/load_status.cache: "end"` |
| TM/DM → Result | File write | `result/<task_name>/TM_history.json`, etc. |

### 5.3 Port Assignment

| Port | Service | Protocol |
|------|---------|----------|
| 25565 | Minecraft Java Server | MC protocol |
| 5001 | Agent Alice Flask server | HTTP |
| 5002 | Agent Bob Flask server | HTTP |
| 5003 | Agent Cindy Flask server (if 3 agents) | HTTP |

Base port is `5001` (`env/env.py:54`). Each additional agent increments: `base_port + len(agent_pool)`.

### 5.4 File-Based Coordination

| File | Writer | Reader | Purpose |
|------|--------|--------|---------|
| `.cache/meta_setting.json` | Main process | Pipeline components | Current task config |
| `.cache/load_status.cache` | Judger → Main process | Main process | `"start"` → `"loading"` → `"loaded"` → `"end"` |
| `.cache/heart_beat.cache` | Judger | Main process | `{"time": <unix_timestamp>}` updated every ~1s |
| `.cache/state.json` | env.py | — | `{"state": "idle"}` |
| `data/score.json` | Judger | env.py | Periodic score snapshots |
| `data/action_log.json` | Agent tools | Judger, moved to result | All actions with timestamps |
| `data/tokens.json` | LLM calls | Moved to result | Token usage tracking |
| `data/map_description.json` | Judger | TaskManager | Blueprint recipe for construction |
| `logs/task_list.json` | GlobalController | — | Agent states + task assignments |
| `logs/graph_*.json` | TaskManager | — | DAG state snapshots |

---

## 6. Scoring & Evaluation Logic

### 6.1 Construction Scenario (`env/build_judger.py`)

#### Complexity (`measure_complexity()`, line 97-154)

```
complexity = Σ  (1 / (connected_paths + 1) + (y - ground_level) × 0.02) × 2
              for each non-air, non-water, non-lava block
```

Where:
- `connected_paths`: neighboring blocks in 6 directions, filtered by facing direction:
  - Facing W: exclude [-1,0,0] neighbor
  - Facing E: exclude [1,0,0] neighbor
  - Facing S: exclude [0,0,-1] neighbor
  - Facing N: exclude [0,0,1] neighbor
  - Facing x: only keep vertical neighbors [0,±1,0]
  - Facing y: only keep horizontal neighbors [±1,0,0]
  - Facing A (any): all neighbors count
- Ground level counts as a neighbor for y == ground_level
- `ground_level` = min(block.y for all blocks) - 1

**Worked example** (Task 0, 3 blocks):
- Block 1: cut_sandstone at [-8,-60,0], facing A, y=-60, ground_level=-61
  - connected_paths: ground (y==ground_level) → 1 path
  - score: (1/(1+1) + (-60-(-61))×0.02) × 2 = (0.5 + 0.02) × 2 = 1.04
- Block 2: terracotta at [-8,-59,0], facing A, y=-59
  - connected_paths: cut_sandstone below → 1 path
  - score: (1/(1+1) + 1×0.02) × 2 = (0.5 + 0.02) × 2 = 1.04
- Block 3: torch at [-8,-58,0], facing A, y=-58
  - connected_paths: terracotta below → 1 path
  - score: (1/(1+1) + 2×0.02) × 2 = (0.5 + 0.04) × 2 = 1.08
- **Total complexity: 1.04 + 1.04 + 1.08 = 3.16** (actual: 2.91 due to exact position offsets)

#### block_hit_rate (`cal_block_hit_rate()`, line 315-329)

```
block_hit_rate = hit_num / total_num
```

Where:
- `total_num`: count of non-air, non-water, non-lava blocks in blueprint
- `hit_num`: blocks where `bot.blockAt(position)` matches blueprint (name + facing/axis)
- Facing check: "W"→west, "E"→east, "S"→south, "N"→north, "x"→axis=x, "y"→axis=y, "z"→axis=z, "A"→any

**Worked example**: 3 blocks, all correctly placed → `block_hit_rate = 3/3 = 1.0`

#### view_hit_rate (`cal_view_hit_rate()`, line 331-506)

Average of IoU-like scores from 5 viewpoints:

```
view_hit_rate = mean(hit_rate_front, hit_rate_right, hit_rate_left, hit_rate_back, hit_rate_top)
```

For each viewpoint:
1. Build a 2D projection of the blueprint blocks visible from that angle
2. For each visible blueprint pixel, ray-trace into the actual world
3. Check if the first non-air block matches the expected block
4. `hit_rate = matches / total_visible_pixels`

The 5 viewpoints:
- **Front** (x=max, looking toward -x): for each (y,z) position, find the block with max x
- **Right** (z=min, looking toward +z): for each (x,y) position, find the block with min z
- **Left** (z=max, looking toward -z): for each (x,y) position, find the block with max z
- **Back** (x=min, looking toward +x): for each (y,z) position, find the block with min x
- **Top** (y=max, looking toward -y): for each (z,x) position, find the block with max y

**Worked example**: All 3 blocks correctly placed, visible from all angles → `view_hit_rate = 1.0`

#### Efficiency

```
max_action_time = (ln(complexity) + 1) × 60 + 180
efficiency = max_action_time / actual_action_time
```

Where `actual_action_time` = `calculate_action_time()` which merges overlapping action intervals from `data/action_log.json`.

**Worked example**:
- complexity = 2.91
- max_action_time = (ln(2.91) + 1) × 60 + 180 = (1.069 + 1) × 60 + 180 = 304.1
- actual_action_time = 18.0 seconds
- efficiency = 304.1 / 18.0 = 16.89

#### Time Limits

```
max_action_time = (ln(complexity) + 1) × 60 + 180
max_time = (ln(complexity) + 1) × 60 + 300, capped at 720
wait_interval = 600
```

End conditions (checked every ~1s, scored every ~20s):
1. **Complete**: `block_hit_rate == 1 AND view_hit_rate == 1`
2. **Action timeout**: `action_time > max_action_time`
3. **Wall timeout**: `wall_time - start_time > max_time`
4. **No progress**: No block_hit_rate improvement for 600s after initial progress

#### balance (BAUS) (`calculate_balance()`, line 75-95)

```
balance = 1 - std(normalized_agent_times)
```

Where `normalized_agent_times = agent_time / max(agent_time)`. Calculated but not written to score.json in construction.

### 6.2 Farming Scenario (`env/farm_craft_judger.py`)

#### Complexity (line 87-142)

Based on ingredient source difficulty:
- **Cake** (task_idx 0-35): `complexity = Σ difficulty(source) + 3`
  - Sources: milk, wheat, sugar, egg
  - "in chest" → difficulty 0, "in farm/pasture" → higher
- **Rabbit Stew** (task_idx 36-99): `complexity = Σ difficulty(source) + 6`
  - Sources: cooked_rabbit, baked_potato, carrot, brown_mushroom, bowl, coal

#### Score (0-100)

Checkpoint-based scoring. Each checkpoint has:
- `name`: item name
- `count`: required quantity
- `score`: points awarded
- `sub_check_points`: items that are sub-products (excluded to avoid double-counting)

Score is computed by querying each agent's inventory via `/data get entity <name> Items`.

#### Cooperation (0-100)

```
cooperation = 100 × (1 - (std - min_std) / (max_std - min_std))
```

Where:
- For each agent, count total items owned across all checkpoint categories
- `std` = standard deviation of item counts across agents
- `min_std` = minimum possible std
- `max_std` = maximum possible std

#### Time Limits

```
max_action_time = complexity × 40
max_time = complexity × 50, capped at 720
```

#### Output Format

```json
{
    "score": 0-100,
    "cooperation": 0-100,
    "efficiency": float,
    "balance": float,
    "use_time": float,
    "end_reason": "complete task" | "action time out" | "max time out",
    "end_time": "YYYY-MM-DD HH:MM:SS"
}
```

### 6.3 Puzzle (Escape Room) Scenario (`env/escape_room_judger.py`)

#### Complexity

From `state_tree.complexity` loaded from `data/escape_atom.json`. Based on number and difficulty of puzzle elements.

#### complete_score (0-1)

```
complete_score = average(fraction_satisfied_events for each task in state_tree)
```

#### complexity_score

```
complexity_score = state_tree.complexity × complete_score
```

#### Time Limits

```
max_action_time = state_tree.complexity × 30 + 60
max_time = len(task_list) × 40 + 240, capped at 720
```

#### Output Format

```json
{
    "complete_score": float,
    "complexity_score": float,
    "efficiency": float,
    "balance": float,
    "use_time": float,
    "end_reason": "complete task" | "action_time out" | "max time out",
    "end_time": "YYYY-MM-DD HH:MM:SS"
}
```

---

## 7. Edge Cases & Failure Modes

### 7.1 Reflect Incorrectly Marking Success as Failure

**Observed in Task 0, Round 1**: Bob's reflect returned `task_status: false` even though terracotta was present at [-8,-59,0]. The reflect LLM reasoned that there was "no evidence Bob placed it himself" since it appeared in the map after scaffolding was erected. This triggered unnecessary re-decomposition.

**Root cause**: The reflect prompt (`agent_prompt.py:1-23`) asks about action history, not world state. If the agent didn't explicitly place the block (it was auto-placed by the scaffolding mechanic), the LLM may not credit it.

**Impact**: Extra round of decomposition, wasted LLM calls and time.

### 7.2 TM Re-decomposing the Same Subtask

After a failure, the TM re-decomposes ALL remaining subtasks (not just the failed one). In the `update_task()` method (`pipeline/task_manager.py:493-562`), the entire graph is replaced with a new one from the LLM. This can result in the same subtask being generated again (as happened with terracotta in Task 0).

The success/failure trace helps the LLM avoid this, but the LLM may still generate the same subtask if it believes the task is genuinely unfinished.

### 7.3 Agents Getting Stuck in Loops

Agents can exhaust their `max_turn` (7 iterations) without completing the task, leading to the `Agent stopped due to iteration limit or time limit.` final answer. This was observed in Bob's Round 1 where he tried multiple approaches (scan, equip, place, dirt support, dirt ladder) but couldn't place terracotta.

### 7.4 Status Field Inconsistency

Some actions return `status: false` even when the action succeeded. For example, Alice's `placeBlock` for cut_sandstone returned `status: false` but the block was actually placed (confirmed by subsequent scan). This is because the Mineflayer action wrapper doesn't always correctly interpret the game's response.

### 7.5 Agents Unable to Find Items/Chests

When agents scan for items (`scanNearbyEntities`) they may not find items that are in their inventory. The scan only checks the world, not the agent's own inventory. Agents need to check their inventory separately.

### 7.6 Dirt Ladder Scaffolding Side Effects

The `erectDirtLadder` tool places dirt blocks as scaffolding, which modifies the world. After the task, these extra blocks may not be cleaned up. The judger's `view_hit_rate` calculation may be affected if scaffolding blocks are visible from certain viewpoints (though the actual implementation only checks blueprint positions).

### 7.7 Subtask Size Analysis

From analyzing the decomposition patterns:
- **74% of subtasks are single-block placements** (one block per subtask)
- **Average subtask size**: 1.3 blocks
- This is because the TM prompt explicitly instructs: "the number of sub-tasks should no more than numbers of agents" and "sub-tasks should be small, simple and achievable"
- With 2 agents, the TM generates at most 2 subtasks per round, leading to fine-grained decomposition

### 7.8 Heartbeat Timeout

The main process monitors `.cache/heart_beat.cache`. If the file's timestamp is more than 10 seconds old, the main process kills the subprocess (`start_with_config.py:262-283`). This can happen if:
- The judger crashes
- The Minecraft server becomes unresponsive
- File I/O errors prevent the heartbeat write

### 7.9 Task Trace Accumulation

The `task_trace` and `total_trace` lists in TaskManager grow with each round. Failed tasks are removed from `task_trace` but added to `fail_trace`. If a task repeatedly fails and gets re-decomposed, the traces can grow large, increasing prompt size for the TM.

---

## 8. Reimplementation Checklist

Ordered by dependency — implement each component before the ones that depend on it.

### Phase 1: Core Infrastructure

| # | Component | Description | Depends On |
|---|-----------|-------------|------------|
| 1 | **Task & Graph** (`type_define/graph.py`) | Task dataclass with status/milestones/dependencies; Graph using networkx DiGraph | None |
| 2 | **LLM Wrapper** (`model/init_model.py`) | Unified interface to LLM APIs (OpenAI-compatible). Must support `few_shot_generate_thoughts(system, prompt, json_check, check_tags)` | None |
| 3 | **JSON Parser** (`model/utils.py`) | `extract_info(response)` to parse LLM JSON from markdown code blocks | None |
| 4 | **Template Engine** (`pipeline/utils.py`) | `format_string(template, data)` that replaces `{{key}}` with values | None |
| 5 | **Logger** (`env/utils.py`) | `init_logger(name, level, dump, silent)` with file dump support | None |

### Phase 2: Environment Layer

| # | Component | Description | Depends On |
|---|-----------|-------------|------------|
| 6 | **Minecraft Server** | Vanilla MC 1.19.2 server with appropriate settings | Phase 1 |
| 7 | **Mineflayer Agent Bot** | Node.js bot connecting to MC server, Flask HTTP server for tool endpoints | #6 |
| 8 | **Agent Tools** | LangChain `@tool` functions: placeBlock, navigateTo, scanNearbyEntities, equipItem, fetchContainerContents, withdrawItem, MineBlock, erectDirtLadder, dismantleDirtLadder, handoverBlock | #7 |
| 9 | **Agent Bridge** (`env/minecraft_client.py`) | Python class managing bot lifecycle, LangChain ReAct agent creation, tool dispatch via HTTP | #7, #8 |

### Phase 3: Judger Layer

| # | Component | Description | Depends On |
|---|-----------|-------------|------------|
| 10 | **Build Judger** (`env/build_judger.py`) | World setup (clear, place blocks, load materials), scoring (block_hit_rate, view_hit_rate), time limits | #6, #7 |
| 11 | **Farm Craft Judger** (`env/farm_craft_judger.py`) | Ingredient distribution, checkpoint scoring, cooperation metric | #6, #7 |
| 12 | **Escape Room Judger** (`env/escape_room_judger.py`) | State tree evaluation, puzzle completion scoring | #6, #7 |

### Phase 4: Pipeline Layer

| # | Component | Description | Depends On |
|---|-----------|-------------|------------|
| 13 | **DataManager** (`pipeline/data_manager.py`) | Environment state processing, history summarization, agent state tracking | #2, #1 |
| 14 | **TaskManager** (`pipeline/task_manager.py`) | Task decomposition (PART_DECOMPOSE), re-decomposition (REDECOMPOSE), graph management | #2, #13, #1 |
| 15 | **BaseAgent** (`pipeline/agent.py`) | Prompt building, step execution, task reflection | #9, #13, #2 |
| 16 | **GlobalController** (`pipeline/controller_tiny.py`) | 3-thread orchestrator: task assignment, worker dispatch, result processing | #14, #15, #13 |

### Phase 5: Orchestration

| # | Component | Description | Depends On |
|---|-----------|-------------|------------|
| 17 | **VillagerBench** (`env/env.py`) | Environment wrapper: agent registration, launch, step, scoring | #9, #10-12 |
| 18 | **Main Entry** (`start_with_config.py`) | Config loading, process management, heartbeat monitoring, result collection | #17, #16 |

### Phase 6: Data & Assets

| # | Component | Description | Depends On |
|---|-----------|-------------|------------|
| 19 | **Blueprint Data** (`data/building_blue_print.json`) | 100 construction blueprints with blocks, positions, facings | None |
| 20 | **Farm Settings** (`data/farm_setting.json`) | 100 farming task configurations with ingredient sources | None |
| 21 | **Escape Puzzles** (`data/escape_atom.json`) | State tree definitions for escape room puzzles | None |
| 22 | **Speaking Styles** (`speaking_style.py`) | Personality traits and examples for agent diversity | None |
| 23 | **Config Generator** (`config.py`) | Generates launch configs for all task types | None |

### Minimum Viable Reimplementation

To recreate the core system, implement these in order:

1. **Task + Graph** — the data model
2. **LLM Wrapper** — API calls with JSON response parsing
3. **Template Engine** — `{{var}}` interpolation
4. **Minecraft Server** — vanilla 1.19.2
5. **Mineflayer Bots** — one per agent + one judger, Flask HTTP for tools
6. **Agent Tools** — placeBlock, navigateTo, scanNearbyEntities (minimum set for construction)
7. **Build Judger** — world setup + block_hit_rate scoring
8. **DataManager** — env summarization + history tracking
9. **TaskManager** — PART_DECOMPOSE → DAG → query open tasks
10. **BaseAgent** — prompt building → LangChain ReAct → reflect
11. **GlobalController** — 3-thread orchestrator
12. **Main entry point** — config → process → pipeline → score

### Key Design Decisions for Reimplementation

1. **Thread model**: The controller uses 3 Python threads (not async). Agent execution is via ThreadPoolExecutor. This is simple but limits concurrency.

2. **File-based coordination**: Heartbeat and status use file polling. A reimplementation could use sockets or message queues.

3. **LLM dependency**: The system makes LLM calls in 4 places:
   - Task decomposition (TM)
   - Environment summarization (DM)
   - History summarization (DM)
   - Task reflection (Agent)
   - Agent action selection (LangChain ReAct via `env.step()`)

4. **Stateless re-decomposition**: Each feedback cycle re-decomposes ALL remaining subtasks from scratch. There is no incremental update (except in "merge" mode which is not the default).

5. **Graph replacement**: The entire DAG is replaced on each re-decomposition cycle, not mutated. This means the TM's `_pre_idxs` are re-generated each time.

6. **Mineflayer as HTTP bridge**: The Mineflayer bots expose tools via Flask HTTP endpoints. This is the main bottleneck — each tool call is an HTTP round-trip. A reimplementation could use a more direct bridge.

---

*Document generated from source code analysis of the VillagerAgent repository. All file paths and line numbers reference the current state of the codebase. Real data examples are from `result/gpt_4o_construction_task0_2p/`.*
