def init_language_model(args: dict):
    api_model = args.get("api_model", "")
    api_base = args.get("api_base", "")

    from model.utils import is_openai_compatible_api

    if is_openai_compatible_api(api_model, api_base):
        from model.openai_models import OpenAILanguageModel

        new_args = {
            "api_key": args.get("api_key", None),
            "api_model": api_model,
            "api_base": api_base,
            "evaluation_strategy": args.get("evaluation_strategy", None),
            "enable_ReAct_prompting": args.get("enable_ReAct_prompting", None),
            "strategy": args.get("strategy", None),
            "role_name": args.get("role_name", None),
            "api_key_list": args.get("api_key_list", None)
        }
        new_args = {k: v for k, v in new_args.items() if v is not None}
        return OpenAILanguageModel(**new_args)
    elif "gemini" in api_model:
        from model.google_model import GoogleLanguageModel

        new_args = {
            "api_key": args.get("api_key", None),
            "api_model": api_model,
            "role_name": args.get("role_name", None),
            "api_key_list": args.get("api_key_list", None)
        }
        new_args = {k: v for k, v in new_args.items() if v is not None}
        return GoogleLanguageModel(**new_args)
    elif "glm" in api_model:
        from model.zhipu_model import ZhipuLanguageModel

        new_args = {
            "api_key": args.get("api_key", None),
            "api_model": api_model,
            "api_base": api_base,
            "role_name": args.get("role_name", None),
            "api_key_list": args.get("api_key_list", None)
        }
        new_args = {k: v for k, v in new_args.items() if v is not None}
        return ZhipuLanguageModel(**new_args)
    elif "vllm" in api_model or "llama" in api_model or "NAS" in api_model:
        from model.vllm_model import VLLMLanguageModel

        new_args = {
            "api_key": args.get("api_key", None),
            "api_model": api_model,
            "api_base": args.get("api_base", None),
            "role_name": args.get("role_name", None),
        }
        new_args = {k: v for k, v in new_args.items() if v is not None}
        print(f"Loading VLLM model with args: {new_args}")
        return VLLMLanguageModel(**new_args)
    else:
        from model.huggingface_model import HFLanguageModel

        new_args = {
            "api_key": args.get("api_key", None),
            "model_tokenizer": args.get("model_tokenizer", None),
            "verbose": args.get("verbose", None),
            "api_key_list": args.get("api_key_list", None)
        }
        new_args = {k: v for k, v in new_args.items() if v is not None}
        return HFLanguageModel(**new_args)
