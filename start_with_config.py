import multiprocessing
import argparse
import os
import shutil
import random
import psutil

import time
from env.env import VillagerBench, env_type, Agent
from env.utils import safe_load_json, safe_write_json
from model.init_model import init_language_model
from model.utils import is_rcac_api_base, normalize_openai_api_base

start_time = time.time()
from pipeline.controller_tiny import GlobalController
from pipeline.data_manager import DataManager
from pipeline.task_manager import TaskManager
import json

print(f"pipeline Time taken: {time.time() - start_time}")
start_time = time.time()

os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

def load_api_key_list(api_model: str, api_base: str = "") -> list:
    with open("API_KEY_LIST", "r") as f:
        key_map = json.load(f)

    model = str(api_model or "").lower()
    if is_rcac_api_base(api_base) or "rcac" in model or "purdue" in model:
        candidates = ["RCAC", "PURDUE_RCAC", "GENAI_STUDIO", "AGENT_KEY", "OPENAI"]
    elif "gemini" in model:
        candidates = ["GEMINI", "AGENT_KEY", "OPENAI"]
    elif "glm" in model:
        candidates = ["GLM", "ZAI", "ZHIPU", "AGENT_KEY", "OPENAI"]
    elif "qwen" in model:
        candidates = ["DASHSCOPE", "QWEN", "AGENT_KEY", "OPENAI"]
    else:
        candidates = ["AGENT_KEY", "OPENAI"]

    for key in candidates:
        values = key_map.get(key)
        if values:
            return values
    raise KeyError(f"No API key list found for model {api_model}; checked {candidates}")


def move_if_exists(src: str, dst: str):
    if os.path.exists(src) and not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)


def safe_task_name(task_name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in task_name)


def move_judger_log(task_name: str, result_dir: str):
    src = os.path.join("logs", f"{safe_task_name(task_name)}_judger.log")
    dst = os.path.join(result_dir, "judger.log")
    if os.path.exists(src):
        os.makedirs(result_dir, exist_ok=True)
        if os.path.exists(dst):
            os.remove(dst)
        shutil.move(src, dst)


def append_pipeline_log(task_name: str, exception: str, detail: str = None):
    os.makedirs(".cache", exist_ok=True)
    log_path = ".cache/pipeline_test_logs.json"
    logs = safe_load_json(log_path, default=[])
    if not isinstance(logs, list):
        logs = []

    entry = {
        "task_name": task_name,
        "time": time.time(),
        "exception": exception
    }
    if detail:
        entry["detail"] = detail
    logs.append(entry)
    safe_write_json(log_path, logs)


def expected_judger_script(task_type: str):
    return {
        "construction": "env/build_judger.py",
        "farming": "env/farm_craft_judger.py",
        "puzzle": "env/escape_room_judger.py",
        "auto": "env/auto_judger.py",
        "meta": "env/meta_judger.py",
        "gen": "env/llm_gen_judger.py",
    }.get(task_type)


def has_live_judger(parent: psutil.Process, task_type: str) -> bool:
    expected_script = expected_judger_script(task_type)
    if not expected_script:
        return True
    try:
        children = parent.children(recursive=True)
    except psutil.Error:
        return False
    for child in children:
        try:
            cmdline = child.cmdline()
        except psutil.Error:
            continue
        if any(expected_script in part for part in cmdline):
            return True
    return False


def kill_process_tree(parent: psutil.Process):
    try:
        children = parent.children(recursive=True)
    except psutil.Error:
        children = []
    for child in children:
        try:
            child.kill()
        except psutil.Error:
            pass
    try:
        parent.kill()
    except psutil.Error:
        pass


def write_task_config(config: dict) -> str:
    result_dir = os.path.join("result", config["task_name"])
    os.makedirs(result_dir, exist_ok=True)
    safe_write_json(os.path.join(result_dir, "config.json"), config)
    return result_dir


def move_runtime_artifacts(result_dir: str):
    move_if_exists("data/action_log.json",
                   os.path.join(result_dir, "action_log.json"))
    move_if_exists("data/tokens.json",
                   os.path.join(result_dir, "tokens.json"))


def finish_success(parent: psutil.Process, config: dict):
    kill_process_tree(parent)
    result_dir = write_task_config(config)
    move_runtime_artifacts(result_dir)
    move_judger_log(config["task_name"], result_dir)


def finish_failure(parent: psutil.Process, config: dict, exception: str, detail: str = None):
    print(exception)
    append_pipeline_log(config["task_name"], exception, detail)
    kill_process_tree(parent)
    result_dir = write_task_config(config)
    safe_write_json(os.path.join(result_dir, "failure.json"), {
        "exception": exception,
        "detail": detail,
        "time": time.time()
    })
    move_runtime_artifacts(result_dir)
    move_judger_log(config["task_name"], result_dir)


def run(api_model: str, api_base: str, task_type: str, task_idx: int, agent_num: int, dig_needed: bool, max_task_num: int, task_goal: str, document_file: str, host: str, port: int, task_name: str, role: str = "same", api_key_list: list = None, document: dict = None):
    start_time = time.time()

    if api_key_list is None:
        api_base = normalize_openai_api_base(api_base)
        api_key_list = load_api_key_list(api_model, api_base)
    if document is None:
        document = {}

    api_base = normalize_openai_api_base(api_base)
    Agent.base_url = api_base
    Agent.model = api_model
    Agent.api_key_list = api_key_list

    # 设置env
    if task_type == "construction":
        env = VillagerBench(env_type=env_type.construction, task_id=task_idx, dig_needed=dig_needed, host=host, port=port, max_task_num=max_task_num, task_name=task_name, _virtual_debug=False)
    elif task_type == "farming":
        env = VillagerBench(env_type=env_type.farming, task_id=task_idx, dig_needed=False, host=host, port=port, max_task_num=max_task_num, task_name=task_name, _virtual_debug=False)
    elif task_type == "puzzle":
        env = VillagerBench(env_type=env_type.puzzle, task_id=task_idx, dig_needed=False, host=host, port=port, max_task_num=max_task_num, task_name=task_name, _virtual_debug=False)
    elif task_type == "meta":
        env = VillagerBench(env_type=env_type.meta, task_id=task_idx, dig_needed=False, host=host, port=port, max_task_num=max_task_num, task_name=task_name, _virtual_debug=False)
    elif task_type == "gen":
        env = VillagerBench(env_type=env_type.gen, task_id=task_idx, dig_needed=False, host=host, port=port, max_task_num=max_task_num, task_name=task_name, _virtual_debug=False)
    else:
        raise NotImplementedError

    # 设置agent_tool
    if task_type == "construction":
        agent_tool = [Agent.placeBlock, Agent.fetchContainerContents, Agent.MineBlock, Agent.scanNearbyEntities, Agent.equipItem,
                      Agent.navigateTo, Agent.withdrawItem, Agent.dismantleDirtLadder, Agent.erectDirtLadder, Agent.handoverBlock]
    elif task_type == "farming":
        agent_tool = [Agent.fetchContainerContents, Agent.MineBlock, Agent.scanNearbyEntities, Agent.equipItem, Agent.SmeltingCooking,
                      Agent.navigateTo, Agent.withdrawItem, Agent.craftBlock, Agent.attackTarget, Agent.useItemOnEntity,
                      Agent.handoverBlock]
    elif task_type == "puzzle":
        agent_tool = [Agent.placeBlock, Agent.fetchContainerContents, Agent.MineBlock, Agent.scanNearbyEntities, Agent.equipItem,
                      Agent.navigateTo, Agent.withdrawItem, Agent.ToggleAction, Agent.handoverBlock]
    elif task_type == "meta" or task_type == "gen":
        agent_tool = [Agent.scanNearbyEntities, Agent.navigateTo, Agent.attackTarget, Agent.useItemOnEntity, Agent.useItemOnBlock,
                      Agent.MineBlock, Agent.placeBlock, Agent.equipItem, Agent.handoverBlock, Agent.SmeltingCooking, Agent.withdrawItem, 
                      Agent.storeItem, Agent.craftBlock, Agent.eat, Agent.fetchContainerContents, Agent.wake, Agent.talkTo, Agent.waitForFeedback,
                      Agent.openContainer, Agent.performMovement, 
                      Agent.sleep, Agent.startFishing, Agent.ToggleAction, 
                      Agent.read, Agent.mountEntity, Agent.dismountEntity]
    else:
        raise NotImplementedError

    print(f"VillagerBench Time taken: {time.time() - start_time}")
    start_time = time.time()

    # 设置agent_pool
    name_list = ["Alice", "Bob", "Cindy", "David", "Eve", "Frank", "Grace", "Helen", "Ivy", "Jack", "Kevin", "Lily",
                 "Mary", "Nancy", "Olivia", "Peter", "Queen", "Rose", "Sam", "Tom", "Umbrella", "Vivian", "Wendy",
                 "Xavier", "Yolanda", "Zoe"]
    if agent_num == 3 and task_type == "farming" and role == "different":
        agent_tool = [Agent.fetchContainerContents, Agent.scanNearbyEntities, Agent.equipItem,
                      Agent.navigateTo, Agent.withdrawItem, Agent.craftBlock, Agent.SmeltingCooking,
                      Agent.handoverBlock]
        env.agent_register(agent_tool=agent_tool, agent_number=1, name_list=[name_list[0]])
        agent_tool = [Agent.fetchContainerContents, Agent.scanNearbyEntities, Agent.equipItem,
                      Agent.navigateTo, Agent.withdrawItem, Agent.craftBlock, Agent.MineBlock,
                      Agent.handoverBlock]
        env.agent_register(agent_tool=agent_tool, agent_number=1, name_list=[name_list[1]])
        agent_tool = [Agent.fetchContainerContents, Agent.scanNearbyEntities, Agent.equipItem,
                      Agent.navigateTo, Agent.withdrawItem, Agent.craftBlock, Agent.attackTarget, 
                      Agent.handoverBlock]
        env.agent_register(agent_tool=agent_tool, agent_number=1, name_list=[name_list[2]])
    else:
        action = document.get("action", None)
        if action == "chat" or action == "handover":
            env.agent_register(agent_tool=agent_tool, agent_number=agent_num+1, name_list=name_list[:agent_num+1])
        else:
            env.agent_register(agent_tool=agent_tool, agent_number=agent_num, name_list=name_list[:agent_num])

    with env.run(fast_api=False):  # 新增加了一个参数，用于控制是否使用fastapi server
        # 启动DM
        dm = DataManager(silent=False)
        dm.update_database_init(env.get_init_state())

        print(f"DataManager Time taken: {time.time() - start_time}")
        start_time = time.time()

        # 启动TM
        tm = TaskManager(silent=False, cache_enabled=False)

        print(f"TaskManager Time taken: {time.time() - start_time}")
        start_time = time.time()

        # 设置llm
        llm_config = {
            "api_key": api_key_list[0],
            "api_base": api_base,
            "api_model": api_model,
            "api_key_list": api_key_list
        }

        tm_llm_config = llm_config
        dm_llm_config = llm_config
        base_llm_config = llm_config


        ctrl = GlobalController(llm_config, tm, dm, env, 
                                tm_llm_config=tm_llm_config, 
                                dm_llm_config=dm_llm_config,
                                base_agent_config=base_llm_config,
                                all_tools=agent_tool)

        # response = ctrl.agent_list[0].llm.few_shot_generate_thoughts(system_prompt="", example_prompt="hi")
        # print(response)
        if task_type == "farming": #补充材料来源prompt
            with open("data/farm_setting.json", "r") as f:
                task_settings = json.load(f)
            task_data = task_settings[task_idx]
            task_goal += f"\nBelow is a detailed list of ingredients and their specific sources. Use this information to plan and coordinate your actions efficiently:\n"
            if "cake" in task_data["name"]:
                task_goal += f"egg: egg in chest\n"
                task_goal += f"milk: {task_data['milk']}\n"
                task_goal += f"wheat: {task_data['wheat']}\n"
                task_goal += f"sugar: {task_data['sugar']}\n"
            elif "rabbit_stew" in task_data["name"]:
                task_goal += f"cooked_rabbit: {task_data['cooked_rabbit']}\n"
                task_goal += f"baked_potato: {task_data['baked_potato']}\n"
                task_goal += f"carrot: {task_data['carrot']}\n"
                task_goal += f"brown_mushroom: {task_data['brown_mushroom']}\n"
                task_goal += f"bowl: {task_data['bowl']}\n"
                
        if os.path.exists(document_file):
            document["recipe"] = json.load((open(document_file)))
        tm.init_task(description=task_goal, document=document)

        ctrl.run()

        env.get_score()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="gpt_4o_launch_config_meta.json", help="launch config json file")
    args = parser.parse_args()

    with open(args.config, "r") as f:
        launch_config = json.load(f)
    heartbeat_timeout_sec = float(os.getenv("VILLAGER_HEARTBEAT_TIMEOUT_SEC", "3600"))
    # shuffle 
    # launch_config = random.sample(launch_config, len(launch_config))
    for i, config in enumerate(launch_config):

        score_path = os.path.join("result", config["task_name"], "score.json")
        if os.path.exists(score_path):
            print(f"task {config['task_name']} exists")
            continue
        print(f"task {i+1}/{len(launch_config)} start")
        print("config:", config)
        safe_write_json(".cache/meta_setting.json", config)
        if config["task_type"] != "meta":
            config.pop("evaluation_arg", None) # 避免evaluation_arg的相关信息影响执行
        safe_write_json(".cache/load_status.cache", {"status": "start"})
        if os.path.exists(".cache/heart_beat.cache"):
            os.remove(".cache/heart_beat.cache")

        api_model = config.get("api_model", "gpt-4o")
        api_base = normalize_openai_api_base(config.get("api_base", "https://api.openai.com/v1"))
        api_key_list = load_api_key_list(api_model, api_base)

        llm_config = {
            "api_key": api_key_list[0],
            "api_base": api_base,
            "api_model": api_model,
            "api_key_list": api_key_list
        }
        
        process = multiprocessing.Process(target=run,
                                            args=(llm_config["api_model"],
                                                llm_config["api_base"],
                                                config["task_type"],
                                                config["task_idx"],
                                                config["agent_num"],
                                                config.get("dig_needed", False),
                                                config.get("max_task_num", 0),
                                                config["task_goal"],
                                                config.get("document_file", ""),
                                                config["host"],
                                                config["port"],
                                                config["task_name"],
                                                config.get("role", "same"),
                                                llm_config["api_key_list"],
                                                config.get("evaluation_arg", {})
                                            )
                                          )
        process.start()

        parent = psutil.Process(process.pid)
        loaded_seen_at = None
        end_seen_at = None
        judger_exit_grace_sec = float(os.getenv("VILLAGER_JUDGER_EXIT_GRACE_SEC", "5"))
        score_grace_sec = float(os.getenv("VILLAGER_SCORE_GRACE_SEC", "5"))

        while True:
            time.sleep(1)
            try:
                status = safe_load_json(".cache/load_status.cache", default={}).get("status")

                if status == "end":
                    if os.path.exists(score_path):
                        finish_success(parent, config)
                        break
                    if end_seen_at is None:
                        end_seen_at = time.time()
                    elif time.time() - end_seen_at > score_grace_sec:
                        finish_failure(parent, config, "env error", "load_status ended without score.json")
                        break
                    continue
                end_seen_at = None

                if status in ("error", "judger_error"):
                    finish_failure(parent, config, "env error", f"load_status reported {status}")
                    break

                if status == "loaded":
                    if loaded_seen_at is None:
                        loaded_seen_at = time.time()
                    elif time.time() - loaded_seen_at > judger_exit_grace_sec and not os.path.exists(score_path) and not has_live_judger(parent, config["task_type"]):
                        finish_failure(parent, config, "judger error", "judger process exited before score.json was written")
                        break
                else:
                    loaded_seen_at = None

                if os.path.exists(".cache/heart_beat.cache"):
                    env_time = safe_load_json(".cache/heart_beat.cache", default={}).get("time")
                    if env_time and time.time() - env_time > heartbeat_timeout_sec:
                        finish_failure(parent, config, "env error", f"heartbeat stale for more than {heartbeat_timeout_sec} seconds")
                        break

                if not process.is_alive() and not os.path.exists(score_path):
                    finish_failure(parent, config, "controller error", "task controller process exited before score.json was written")
                    break
                if os.path.exists(score_path):
                    finish_success(parent, config)
                    break
            except:
                pass

        print(f"task {i+1} end")

# python env/minecraft_server.py -H 10.214.180.148 -P 25565 -LP 5000 -U Alice -W world -D false
# python env/meta_judger.py --idx 0 --host 10.214.180.148 --port 25565 --agent_num 1 --agent_names Alice --task_name meta_test_task0
