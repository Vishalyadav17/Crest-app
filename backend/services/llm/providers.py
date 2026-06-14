from __future__ import annotations

PROVIDERS: dict[str, dict] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "env_var": "GROQ_API_KEY",
        "allowlist": {
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "qwen/qwen3-32b",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
        },
        "requires_free_suffix": False,
        "block_substrings": set(),
        "ctx_cap": None,
        "hard_stop_on_429": False,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env_var": "OPENROUTER_API_KEY",
        "allowlist": {
            "openai/gpt-oss-120b:free",
            "qwen/qwen3-next-80b-a3b-instruct:free",   # strong instruct, reliable JSON
            "qwen/qwen3-coder:free",
            "meta-llama/llama-3.3-70b-instruct:free",  # reliable JSON workhorse
            "nvidia/nemotron-3-super-120b-a12b:free",  # 120B reasoner — best free for deep analysis
            "nousresearch/hermes-3-llama-3.1-405b:free",  # 405B, strong long-form
        },
        "requires_free_suffix": True,
        "block_substrings": set(),
        "ctx_cap": None,
        "hard_stop_on_429": False,
    },
    "ollama": {
        "base_url": None,  # resolved at runtime from OLLAMA_BASE_URL env
        "env_var": "OLLAMA_API_KEY",
        "allowlist": {"qwen3", "deepseek-r1", "llama3.3"},
        "requires_free_suffix": False,
        "block_substrings": set(),
        "ctx_cap": None,
        "hard_stop_on_429": False,
        "always_free": True,
    },
    "github": {
        "base_url": "https://models.github.ai/inference",
        "env_var": "GITHUB_MODELS_TOKEN",
        "allowlist": {
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "meta/Llama-3.3-70B-Instruct",
            "deepseek/DeepSeek-R1",
        },
        "requires_free_suffix": False,
        "block_substrings": set(),
        "ctx_cap": None,
        "hard_stop_on_429": True,
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "env_var": "NVIDIA_API_KEY",
        # NVIDIA NIM free tier — big reliable pool. Curated: instruct models (reliable JSON) +
        # the strong analysts (Kimi K2.6, Qwen3.5-122b). deepseek-v4/nemotron reason heavily so
        # only used where token budget is generous (deep_analysis).
        "allowlist": {
            "meta/llama-3.3-70b-instruct",
            "qwen/qwen3-next-80b-a3b-instruct",
            "moonshotai/kimi-k2.6",
            "qwen/qwen3.5-122b-a10b",
            "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            "deepseek-ai/deepseek-v4-flash",
        },
        "requires_free_suffix": False,
        "block_substrings": set(),
        "ctx_cap": None,
        "hard_stop_on_429": False,
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "env_var": "CEREBRAS_API_KEY",
        # this key's free tier exposes exactly these two — tight allowlist so a paid/locked
        # model can never be reached. gpt-oss-120b reasons heavily (needs generous token budget
        # for clean JSON); zai-glm-4.7 returns clean JSON in ≥400 tokens.
        "allowlist": {
            "gpt-oss-120b",
            "zai-glm-4.7",
        },
        "requires_free_suffix": False,
        "block_substrings": set(),
        "ctx_cap": None,
        "hard_stop_on_429": False,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "env_var": "GEMINI_API_KEY",
        "allowlist": {
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-3-flash",
        },
        "requires_free_suffix": False,
        "block_substrings": {"pro"},
        "ctx_cap": None,
        "hard_stop_on_429": False,
    },
}

ORDER: list[str] = ["groq", "nvidia", "cerebras", "openrouter", "ollama", "github", "gemini"]

# Per-job model split. Each job leads with a DIFFERENT provider so concurrent jobs hit
# different free pools (no single key rate-limits everything). JSON-strict jobs lead with
# reliable-JSON models (llama-3.3 / qwen3-instruct / gemini); gpt-oss-120b is reasoning-heavy
# and flaky in json_object mode, so it's only ever a deep fallback. The two quality-critical
# analysis jobs (deep_analysis, weekend_review) lead with the strongest free models available.
TASK_MODELS: dict[str, list[tuple[str, str]]] = {
    # NOTE: cerebras models reason heavily and can return EMPTY content under a tight token
    # budget (a 200 with no text → caller's json.loads fails, no fallthrough). So cerebras is
    # only a LAST-resort overflow on JSON-strict short tasks (after the reliable gemini fallback),
    # and only used mid-chain on deep_analysis where the token budget is generous.
    "swing_failure": [
        ("groq", "llama-3.3-70b-versatile"),
        ("nvidia", "meta/llama-3.3-70b-instruct"),
        ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        ("gemini", "gemini-2.5-flash"),
        ("cerebras", "zai-glm-4.7"),
    ],
    "sl_analysis": [
        ("groq", "llama-3.3-70b-versatile"),
        ("nvidia", "meta/llama-3.3-70b-instruct"),
        ("openrouter", "qwen/qwen3-next-80b-a3b-instruct:free"),
        ("gemini", "gemini-2.5-flash"),
    ],
    "trade_validation": [
        ("groq", "llama-3.3-70b-versatile"),
        ("nvidia", "meta/llama-3.3-70b-instruct"),
        ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        ("gemini", "gemini-2.5-flash"),
    ],
    "stock_research": [
        ("nvidia", "qwen/qwen3.5-122b-a10b"),
        ("openrouter", "qwen/qwen3-next-80b-a3b-instruct:free"),
        ("groq", "llama-3.3-70b-versatile"),
        ("gemini", "gemini-2.5-flash"),
    ],
    "kite_route": [
        ("groq", "llama-3.1-8b-instant"),
        ("gemini", "gemini-2.5-flash-lite"),
        ("nvidia", "meta/llama-3.3-70b-instruct"),
    ],
    "validate_pick": [
        ("groq", "llama-3.3-70b-versatile"),
        ("nvidia", "meta/llama-3.3-70b-instruct"),
        ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        ("gemini", "gemini-2.5-flash-lite"),
        ("cerebras", "zai-glm-4.7"),
    ],
    "failure_analysis": [
        ("gemini", "gemini-2.5-flash"),
        ("nvidia", "meta/llama-3.3-70b-instruct"),
        ("groq", "llama-3.3-70b-versatile"),
        ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
    ],
    "scan_review": [
        ("groq", "llama-3.3-70b-versatile"),
        ("nvidia", "meta/llama-3.3-70b-instruct"),
        ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        ("gemini", "gemini-2.5-flash-lite"),
    ],
    "market_note": [
        ("gemini", "gemini-2.5-flash"),
        ("groq", "llama-3.3-70b-versatile"),
        ("nvidia", "meta/llama-3.3-70b-instruct"),
    ],
    # quality-critical — strongest free analysts first (Kimi K2.6, Qwen3.5-122b, Qwen-80b);
    # generous token budget so reasoning models are safe mid-chain.
    "deep_analysis": [
        ("nvidia", "moonshotai/kimi-k2.6"),
        ("openrouter", "qwen/qwen3-next-80b-a3b-instruct:free"),
        ("nvidia", "qwen/qwen3.5-122b-a10b"),
        ("groq", "llama-3.3-70b-versatile"),
        ("cerebras", "zai-glm-4.7"),
        ("gemini", "gemini-2.5-flash"),
    ],
    "research_chat": [
        ("nvidia", "moonshotai/kimi-k2.6"),
        ("groq", "llama-3.3-70b-versatile"),
        ("openrouter", "qwen/qwen3-next-80b-a3b-instruct:free"),
        ("gemini", "gemini-2.5-flash"),
    ],
    "weekend_review": [
        ("nvidia", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
        ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"),
        ("groq", "llama-3.3-70b-versatile"),
        ("gemini", "gemini-2.5-flash"),
    ],
    "winner_review": [
        ("nvidia", "meta/llama-3.3-70b-instruct"),
        ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        ("groq", "llama-3.3-70b-versatile"),
        ("gemini", "gemini-2.5-flash-lite"),
    ],
    "order_extract": [
        ("groq", "llama-3.1-8b-instant"),
        ("gemini", "gemini-2.5-flash-lite"),
        ("nvidia", "meta/llama-3.3-70b-instruct"),
    ],
}
