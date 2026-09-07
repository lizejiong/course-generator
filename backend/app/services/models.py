import hashlib
from dataclasses import dataclass
from uuid import uuid4

from openai import OpenAI

from app.config import Settings
from app.db.models import Run


@dataclass(frozen=True)
class ModelResult:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    model: str


class ModelGateway:
    """The sole OpenAI-compatible SDK boundary; prompts are never persisted."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def complete(
        self,
        run: Run,
        *,
        node: str,
        operation: str,
        prompt: str,
        prompt_name: str,
        prompt_hash: str,
        model_override: str | None = None,
    ) -> ModelResult:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for model execution")
        model = model_override or self.settings.openai_model
        response = OpenAI(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
        ).chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content or ""
        usage = response.usage
        ledger_entry = {
            "call_id": str(uuid4()),
            "operation": operation,
            "node": node,
            "model": model,
            "prompt_name": prompt_name,
            "prompt_hash": prompt_hash,
            "input_hash": hashlib.sha256(prompt.encode()).hexdigest(),
            "output_hash": hashlib.sha256(content.encode()).hexdigest(),
            "input_tokens": usage.prompt_tokens if usage else None,
            "output_tokens": usage.completion_tokens if usage else None,
        }
        run.token_ledger = [*run.token_ledger, ledger_entry]
        run.token_usage += (usage.total_tokens if usage else 0) or 0
        return ModelResult(
            content, ledger_entry["input_tokens"], ledger_entry["output_tokens"], model
        )
