from uuid import uuid4

import pytest

from app.db.models import Run
from app.services.models import ModelGateway, TokenBudgetPause


def test_token_budget_pauses_before_model_call_without_recording_prompt(settings) -> None:
    run = Run(
        course_id=uuid4(), thread_id="token-run", token_limit=1, token_usage=0, token_ledger=[]
    )
    with pytest.raises(TokenBudgetPause, match="可能超过"):
        ModelGateway(settings).complete(
            run,
            node="chapter_write",
            operation="draft",
            prompt="long enough to estimate a model call",
            prompt_name="writer",
            prompt_hash="a" * 64,
        )
    assert run.pause_requested
    assert run.error_code == "token_budget_pause"
    assert run.token_ledger == []
