from fastapi import APIRouter

router = APIRouter(prefix="/v1/rlhf", tags=["rlhf"])


@router.get("/health")
def rlhf_health():
    return {"ok": True}