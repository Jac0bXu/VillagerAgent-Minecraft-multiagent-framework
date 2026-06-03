# AGENTS.md

Guidance for coding agents working in this repository.

## Project Overview

This repo is VillagerAgent / VillagerBench, a Python-first multi-agent framework for coordinating LLM-driven agents in a Minecraft 1.19.2 environment. The high-level loop is:

1. `VillagerBench` launches Mineflayer-backed Minecraft agents and a task-specific judger.
2. `DataManager` summarizes current environment, agent state, and history.
3. `TaskManager` decomposes a natural-language task into a dependency graph of subtasks.
4. `GlobalController` assigns available subtasks to `BaseAgent` instances.
5. Each `BaseAgent` uses LLM output plus Mineflayer tool calls to act in Minecraft.

Most real runs require a Minecraft server, Node/Mineflayer packages, API keys, and external LLM access.

## Important Paths

- `env/`: Minecraft runtime and environment layer.
  - `env/env.py`: `VillagerBench`, `env_type`, agent registration, judger launch, scoring, state access.
  - `env/minecraft_client.py`: Python `Agent` wrapper around tool methods and local HTTP endpoints.
  - `env/minecraft_server.py` and `env/minecraft_server_fast.py`: Flask + Mineflayer bot servers.
  - `env/*_judger.py`: task-specific world setup/evaluation for construction, farming, puzzle, meta, and generation tasks.
- `pipeline/`: orchestration layer.
  - `pipeline/task_manager.py`: decomposes tasks and maintains the task graph.
  - `pipeline/data_manager.py`: stores and summarizes environment/history/agent data.
  - `pipeline/controller.py`: full controller with collaboration handling and stop conditions.
  - `pipeline/controller_tiny.py`: simpler/faster controller used by `start_with_config.py`.
  - `pipeline/agent.py`: `BaseAgent` execution and reflection logic.
  - `pipeline/*_prompt.py`: prompt templates for task decomposition, controller assignment, agents, and data summaries.
- `model/`: LLM backends and selection logic.
  - `model/init_model.py`: chooses OpenAI-compatible, Gemini, GLM, vLLM/llama, or Hugging Face backend based on `api_model`.
  - `model/openai_models.py`: OpenAI-compatible API client, token accounting, and cache helpers.
- `type_define/`: `Task`, `Graph`, and summary data structures.
- `rl_env/`: reinforcement-learning helpers for DQN/PPO action ranking.
- `data/`: static benchmark/task/Minecraft data plus some runtime outputs. Treat tracked static JSON differently from generated files.
- `doc/api_library.md`: human-readable Mineflayer tool API reference.
- `example.py`, `tiny_start.py`: small runnable examples after configuring API/server details.
- `start_with_config.py`: batch runner; currently reads `gpt_4o_launch_config_meta.json` from the repo root.
- `config.py`: launch-config/task generator, but it initializes an LLM at import time and requires `API_KEY_LIST`.

## Setup

Use the repo root as the working directory; several modules rely on relative paths and `sys.path.append(os.getcwd())`.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
npm install
python js_setup.py
```

Create `API_KEY_LIST` in the repo root. It is ignored by git and should not be committed. Existing code commonly expects:

```json
{
  "AGENT_KEY": ["..."],
  "OPENAI": ["..."],
  "GEMINI": ["..."],
  "GLM": ["..."]
}
```

Many scripts read `API_KEY_LIST` at import or startup, including `config.py`, `start_with_config.py`, `pipeline/retriever.py`, and demo scripts. Without it, even harmless imports may fail.

For real environment runs, start/configure a Minecraft 1.19.2 server, usually on port `25565`, with offline auth compatible with Mineflayer. Give each agent operator permissions in-game, for example `/op Alice`.

## Common Commands

```bash
python js_setup.py
python example.py
python tiny_start.py
python start_with_config.py
```

Notes:

- `example.py` contains placeholder model/base URL values; edit or copy it before expecting a real run.
- `tiny_start.py` is a minimal one-agent flow, but still launches the environment and needs API/server settings.
- `start_with_config.py` expects a local launch config JSON. Files matching `*config*.json` are ignored by git, so fresh clones may not include local configs.
- `Dockerfile` appears stale: it has `ENTRYPOINT python run.py`, but this repo does not currently contain `run.py`. Verify or patch the Docker entry point before relying on Docker.

## Verification

There is no discovered pytest suite, `pyproject.toml`, or standard formatter config in this checkout. For focused Python changes, prefer targeted syntax/import checks:

```bash
python -m py_compile path/to/file.py
```

For integration changes, only run environment scripts when the user has confirmed that API keys and a Minecraft server are available. Those runs can spawn bot and judger subprocesses, call external LLM APIs, and rewrite runtime files.

Useful files after a real run:

- `logs/*.log`
- `logs/task_list.json`
- `logs/graph_*.json`
- `data/action_log.json`
- `data/score.json`
- `data/tokens.json`
- `result/<task_name>/`

## Generated And Sensitive Files

Avoid committing or casually editing runtime/sensitive artifacts:

- `API_KEY_LIST`, `openai_api_key.txt`, `google_api_key.txt`, `zhipu_api_key.txt`
- `node_modules/`, `package-lock.json`
- `MCServer/`
- `logs/*`
- `result/*` except tracked result utility scripts
- `.cache/*.cache`, `.cache/state.json`, `.cache/meta_setting.json`
- `data/action_log.json`, `data/tokens.json`, `data/score.json`, `data/url_prefix.json`, `data/llm_inference.json`
- `img/*graph.png`, `img/*graph.md`

Some generated-looking files are already tracked in this checkout, including `.cache/agent_info_example.json`, `.cache/meta_setting.json`, `.DS_Store`, and a `__pycache__` file. Do not remove or revert tracked oddities unless the user asks.

## Coding Notes

- Keep changes scoped; this is a research/prototype codebase with many side-effectful scripts.
- Preserve existing relative-path conventions unless doing a deliberate cleanup.
- Prefer structured JSON handling for task/config/data files.
- Be careful searching the whole repo: `data/building_blue_print.json` is huge. Use targeted searches or exclude large generated/static data when possible.
- `Agent` tools in `env/minecraft_client.py` are LangChain `@tool` functions that POST to per-agent Flask endpoints. Adding a tool usually requires changes in both the Python wrapper and the server endpoint implementation.
- `VillagerBench.__init__` and environment runs write/reset files under `data/`, `.cache/`, and `logs/`.
- `TaskManager.__init__` deletes graph files in `img/` and `logs/`; avoid instantiating it just to inspect state.
- `model/init_model.py` uses substring checks on `api_model`; OpenAI-compatible providers like Qwen/DeepSeek route through `OpenAILanguageModel`.
- The root file `__init__ .py` contains a space in its filename; do not rely on it as a normal package initializer.
