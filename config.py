import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "config.yaml"))

class Settings:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self.data: Dict[str, Any] = {}
        self.load()

    def load(self):
        if not self.config_path.exists():
            # If default doesn't exist, we use a basic fallback or raise an error
            self.data = {
                "db_path": "myrss.db",
                "fetch_interval_minutes": 15,
                "fulltext": {
                    "min_text_chars": 200,
                    "fetcher": "trafilatura"
                }
            }
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.data = yaml.safe_load(f) or {}

    @property
    def db_path(self) -> str:
        env_db_path = os.getenv("DB_PATH")
        if env_db_path:
            return env_db_path
        return self.data.get("db_path", "myrss.db")

    @property
    def port(self) -> int:
        env_port = os.getenv("PORT")
        if env_port:
            try:
                return int(env_port)
            except ValueError:
                pass
        return self.data.get("port", 8888)

    @property
    def fetch_interval_minutes(self) -> int:
        return self.data.get("fetch_interval_minutes", 15)

    @property
    def min_text_chars(self) -> int:
        fulltext_cfg = self.data.get("fulltext", {})
        return fulltext_cfg.get("min_text_chars", 200)

    @property
    def fallback_engine(self) -> str:
        fulltext_cfg = self.data.get("fulltext", {})
        return fulltext_cfg.get("fallback_engine", "jina")

    @property
    def jina_reader_url(self) -> str:
        fulltext_cfg = self.data.get("fulltext", {})
        return fulltext_cfg.get("jina_reader_url", "https://r.jina.ai/")

    @property
    def promote_threshold(self) -> int:
        classify_cfg = self.data.get("classify", {})
        return classify_cfg.get("promote_threshold", 5)

    @property
    def auto_summary(self) -> bool:
        ai_cfg = self.data.get("ai", {})
        return ai_cfg.get("auto_summary", True)

    @property
    def summary_length(self) -> str:
        ai_cfg = self.data.get("ai", {})
        return ai_cfg.get("summary_length", "medium")

    @property
    def summary_language(self) -> str:
        ai_cfg = self.data.get("ai", {})
        return ai_cfg.get("summary_language", "auto")

    @property
    def system_language(self) -> str:
        return self.data.get("system_language", "zh")

    @property
    def interest_profile_enabled(self) -> bool:
        return self.data.get("interest_profile_enabled", False)

    @property
    def access_password(self) -> str:
        return self.data.get("access_password", "")

    def get_ai_config(self, task_name: str, summary_length: Optional[str] = None) -> Dict[str, Any]:
        ai_cfg = self.data.get("ai", {})
        default_cfg = ai_cfg.get("default", {})
        task_cfg = ai_cfg.get("tasks", {}).get(task_name, {})
        
        max_tokens = task_cfg.get("max_tokens")
        if task_name == "summary" and not max_tokens:
            len_val = summary_length or ai_cfg.get("summary_length", "medium")
            is_numeric = False
            try:
                target_num = int(len_val)
                is_numeric = True
            except (ValueError, TypeError):
                pass
                
            if is_numeric:
                max_tokens = max(target_num * 3, 1500)
            elif len_val == "short":
                max_tokens = 500
            elif len_val == "long":
                max_tokens = 2000
            else:
                max_tokens = 1200

        # Merge default and task config, task config overrides default
        return {
            "base_url": task_cfg.get("base_url") or default_cfg.get("base_url") or "http://localhost:9999/v1",
            "api_key": task_cfg.get("api_key") or default_cfg.get("api_key") or "",
            "model": task_cfg.get("model") or default_cfg.get("model") or "qwen-local",
            "batch_size": task_cfg.get("batch_size", 25) if task_name == "classify" else None,
            "max_concurrency": task_cfg.get("max_concurrency", 2) if task_name == "classify" else None,
            "max_tokens": max_tokens,
            "pregenerate": ai_cfg.get("pregenerate", False),
            "stream": ai_cfg.get("stream", True),
            "use_reasoning": task_cfg.get("use_reasoning") if task_cfg.get("use_reasoning") is not None else True,
            "reasoning_disabler": task_cfg.get("reasoning_disabler") or default_cfg.get("reasoning_disabler") or "auto"
        }

    def save(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.data, f, allow_unicode=True, sort_keys=False)

settings = Settings()
