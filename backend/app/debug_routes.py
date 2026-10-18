import traceback
from anthropic import Anthropic
from fastapi import APIRouter, Depends

from app.auth import ROLE_MANAGER, require_roles

router = APIRouter(prefix="/debug", tags=["debug"], dependencies=[Depends(require_roles(ROLE_MANAGER))])

@router.get("/claude")
def debug_claude(model: str = "sonnet-5-5", prompt: str = "hi"):
    try:
        r = Anthropic().messages.create(
            model=model,
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )
        return {"ok": True, "text": r.content[0].text, "usage": r.usage.model_dump()}
    except Exception as e:
        return {
            "ok": False,
            "error": repr(e),
            "cause": repr(e.__cause__),
            "traceback": traceback.format_exc(),
        }