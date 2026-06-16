import json
import logging
import os
import time
import random
import urllib.error
import urllib.request
from retry import retry

from model.abstract_language_model import AbstractLanguageModel
from model.utils import extract_info

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_GLM_ANTHROPIC_BASE_URL = "https://api.z.ai/api/anthropic"
GLM_ANTHROPIC_VERSION = "2023-06-01"
GLM_MIN_MAX_TOKENS = 1024


def normalize_glm_anthropic_base_url(api_base: str = "") -> str:
    """Return the Anthropic-compatible GLM API root.

    GLM's OpenAI-compatible /api/paas/v4 path can require prepaid balance for
    premium models. The Anthropic-compatible path is covered by the GLM Coding
    Plan, so route GLM calls there by default.
    """
    base = str(api_base or os.getenv("GLM_API_BASE") or "").strip().rstrip("/")
    if not base:
        return DEFAULT_GLM_ANTHROPIC_BASE_URL

    lower = base.lower()
    if (
        "api.openai.com" in lower
        or "api.chatanywhere.tech" in lower
        or "open.bigmodel.cn/api/paas" in lower
    ):
        return DEFAULT_GLM_ANTHROPIC_BASE_URL
    if lower.endswith("/v1/messages"):
        return base[: -len("/v1/messages")]
    if lower.endswith("/v1"):
        return base[: -len("/v1")]
    return base


def first_env_key(names):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


class ZhipuLanguageModel(AbstractLanguageModel):
    _supported_models = [
        "glm-4",
        "glm-3-turbo",
        "glm-4.5",
        "glm-4.5-air",
        "glm-4.5-flash",
        "glm-4.6",
        "glm-4.7",
        "glm-5",
        "glm-5-turbo",
        "glm-5.1",
    ]

    def __init__(self, api_key="", api_model="glm-4.5", role_name="", api_key_list=[], api_base=""):
        keys = []
        if api_key:
            keys.append(api_key)
        keys.extend([key for key in (api_key_list or []) if key])

        env_key = first_env_key(["GLM_API_KEY", "ZAI_API_KEY", "ZHIPU_API_KEY", "ZHIPUAI_API_KEY"])
        if env_key:
            keys.append(env_key)

        self.api_key_list = list(dict.fromkeys(keys))
        if not self.api_key_list:
            raise Exception("Please provide a GLM API key via API_KEY_LIST['GLM'] or GLM_API_KEY")
        self.api_key = self.api_key_list[0]
        self.api_base = normalize_glm_anthropic_base_url(api_base)

        if api_model in ZhipuLanguageModel._supported_models:
            self.api_model = api_model
        else:
            raise Exception(f"only support {ZhipuLanguageModel._supported_models}, but got {api_model}")

        self.role_name = role_name

        self.cache_path = "zhipu.cache"

        # 统计相关
        if not os.path.exists("data"):
            os.mkdir("data")
        if not os.path.exists("data/zhipu.logs"):
            with open("data/zhipu.logs", "w") as log_file:
                log_file.write("")

        if not os.path.exists("data/tokens.json"):
            with open("data/tokens.json", "w") as token_file:
                init_data = {
                    "dates": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                    "tokens_used": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "successful_requests": 0,
                    "total_cost": 0,
                    "action_cost": 0,
                }
                json.dump(init_data, token_file)

    def cache_api_call_handler(self, prompt):
        if os.path.exists(".cache") and os.path.exists(os.path.join(".cache", self.cache_path)):
            with open(os.path.join(".cache", self.cache_path), "r") as cache_file:
                cache = json.load(cache_file)
            if prompt in cache.keys():
                return cache[prompt]
            else:
                return None
        else:
            return None

    def save_cache(self, prompt, response):
        if os.path.exists(".cache"):
            if os.path.exists(os.path.join(".cache", self.cache_path)):
                with open(os.path.join(".cache", self.cache_path), "r") as cache_file:
                    cache = json.load(cache_file)
                cache[prompt] = response
                with open(os.path.join(".cache", self.cache_path), "w") as cache_file:
                    json.dump(cache, cache_file)
            else:
                cache = {prompt: response}
                with open(os.path.join(".cache", self.cache_path), "w") as cache_file:
                    json.dump(cache, cache_file)
        else:
            os.mkdir(".cache")

            cache = {prompt: response}
            with open(os.path.join(".cache", self.cache_path), "w") as cache_file:
                json.dump(cache, cache_file)

    def generate_thoughts(self, state, k):
        pass

    def evaluate_states(self, states):
        pass

    def _request_timeout(self):
        try:
            return int(os.getenv("GLM_API_TIMEOUT", "120"))
        except ValueError:
            return 120

    def _request_max_tokens(self, max_tokens):
        try:
            requested = int(max_tokens or 0)
        except (TypeError, ValueError):
            requested = 0
        try:
            minimum = int(os.getenv("GLM_MIN_MAX_TOKENS", str(GLM_MIN_MAX_TOKENS)))
        except ValueError:
            minimum = GLM_MIN_MAX_TOKENS
        return max(requested, minimum)

    def _build_messages(self, example_prompt):
        messages = []
        for i, prompt in enumerate(example_prompt):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append({"role": role, "content": str(prompt)})
        if not messages:
            messages.append({"role": "user", "content": "Respond to the system instructions."})
        return messages

    def _post_messages(self, body):
        url = f"{self.api_base}/v1/messages"
        headers = {
            "Authorization": f"Bearer {random.choice(self.api_key_list)}",
            "anthropic-version": GLM_ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._request_timeout()) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"GLM Anthropic API error {e.code}: {detail[:1000]}") from e

    def _extract_text(self, response):
        content = response.get("content", "")
        if isinstance(content, str):
            return content

        text_blocks = []
        for block in content or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text_blocks.append(block.get("text", ""))
        return "\n".join(text_blocks).strip()

    def _record_usage(self, usage):
        if not usage:
            return
        prompt_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        with open("data/tokens.json", "r") as token_file:
            tokens = json.load(token_file)

        tokens["dates"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        tokens["tokens_used"] = tokens.get("tokens_used", 0) + prompt_tokens + completion_tokens
        tokens["prompt_tokens"] = tokens.get("prompt_tokens", 0) + prompt_tokens
        tokens["completion_tokens"] = tokens.get("completion_tokens", 0) + completion_tokens
        tokens["successful_requests"] = tokens.get("successful_requests", 0) + 1

        with open("data/tokens.json", "w") as token_file:
            json.dump(tokens, token_file)

    @retry(tries=5, delay=10, backoff=2, max_delay=60)
    def few_shot_generate_thoughts(self, system_prompt: str = "", example_prompt: [str] or str = [], max_tokens=2048,
                                   temperature=0.01, top_p=0.7, top_k=1, stop: [str]=None, cache_enabled=True, api_model="", check_tags=[],
                                   json_check=False):
        if api_model == "":
            api_model = self.api_model
        else:
            if api_model not in ZhipuLanguageModel._supported_models:
                raise Exception(f"only support {ZhipuLanguageModel._supported_models}, but got {api_model}")

        if isinstance(example_prompt, str):
            example_prompt = [example_prompt]

        assert len(example_prompt) % 2 == 1 or len(example_prompt) == 0, "example prompt should be odd number or empty"

        logger.info("waiting for generating thoughts")
        logger.info(f"using api model {api_model}")

        prompt = str(system_prompt) + "\n"
        for i in range(len(example_prompt)):
            prompt += example_prompt[i] + "\n"
        if cache_enabled:
            content = self.cache_api_call_handler(prompt)
            if content is not None:
                if self.role_name:
                    with open(f"ui/logs/{self.role_name}.json", "r") as log_file:
                        logs = json.load(log_file)
                    logs.append({"prompt": prompt, "response": content})
                    with open(f"ui/logs/{self.role_name}.json", "w") as log_file:
                        json.dump(logs, log_file)
                return content

        start_time = time.time()
        try:
            body = {
                "model": api_model,
                "max_tokens": self._request_max_tokens(max_tokens),
                "messages": self._build_messages(example_prompt),
                "temperature": temperature,
                "top_p": top_p,
            }
            if system_prompt:
                body["system"] = system_prompt
            if stop:
                body["stop_sequences"] = stop if isinstance(stop, list) else [stop]

            response = self._post_messages(body)
            content = self._extract_text(response)
            if not content:
                raise Exception(f"GLM returned empty content with stop_reason={response.get('stop_reason')}")
            self._record_usage(response.get("usage"))
            
            for tag in check_tags:
                if tag not in content:
                    raise Exception(f"tag {tag} not in content {content}")
            if json_check:
                if len(extract_info(content)) == 0:
                    raise Exception(f"content {content} is not json")
            if cache_enabled:
                self.save_cache(prompt, content)

            with open("data/zhipu.logs", "a") as log_file:
                log_file.write(
                    "\n" + "-----------" + "\n" + "Prompt : " + str(prompt) + "\n"
                )
            if self.role_name:
                if not os.path.exists(f"ui/logs/{self.role_name}.json"):
                    os.makedirs("ui/logs", exist_ok=True)
                    with open(f"ui/logs/{self.role_name}.json", "w") as log_file:
                        json.dump([], log_file)
                with open(f"ui/logs/{self.role_name}.json", "r") as log_file:
                    logs = json.load(log_file)
                logs.append({"prompt": prompt, "response": content})
                with open(f"ui/logs/{self.role_name}.json", "w") as log_file:
                    json.dump(logs, log_file)

            logger.info(f"Time taken: {time.time() - start_time}")
            if os.path.exists("data/llm_inference.json"):
                with open("data/llm_inference.json", "r") as log_file:
                    log = json.load(log_file)
                log["time"] += time.time() - start_time
                with open("data/llm_inference.json", "w") as log_file:
                    json.dump(log, log_file)
            return content
        except Exception as e:
            logger.warning("Something went wrong on Zhipu's end")
            logger.warning(e)
            logger.warning(e.__cause__)
            raise e

