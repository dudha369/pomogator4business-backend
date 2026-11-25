"""Правила архива по чатам: какие чаты пишутся в архив (бизнес-бот и юзербот)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.features.history import rule_queries, rules
from app.features.limits.bot import enforce
from app.platform.api.deps import require_user

router = APIRouter()

ChatKind = Literal["private", "group", "supergroup", "channel"]


class RuleOut(BaseModel):
    chat_id: int
    kind: ChatKind
    enabled: bool
    media_enabled: bool
    notify: bool


class RulesOut(BaseModel):
    rules: list[RuleOut]  # только отклонения от умолчаний (см. history.rules)
    groups_used: int  # включено групп и каналов
    groups_limit: int | None  # лимит тарифа; None — без ограничений


class RuleIn(BaseModel):
    kind: ChatKind
    enabled: bool | None = None
    media_enabled: bool | None = None
    notify: bool | None = None


async def _state(owner_id: int) -> dict:
    from app.features.limits import service
    from app.features.limits.plans import limit_for

    plan = (await service.plan_of(owner_id))["plan"]
    return {
        "rules": await rule_queries.list_rules(owner_id),
        "groups_used": await rule_queries.count_enabled_groups(owner_id),
        "groups_limit": limit_for(plan, "archive_groups"),
    }


@router.get("/archive/rules", response_model=RulesOut)
async def get_rules(user: dict = Depends(require_user)):
    return await _state(user["id"])


@router.put("/archive/rules/{chat_id}", response_model=RulesOut)
async def put_rule(chat_id: int, body: RuleIn, user: dict = Depends(require_user)):
    owner_id = user["id"]
    if body.enabled:
        current = await rules.rule_for(owner_id, chat_id, body.kind, "userbot")
        is_group = body.kind in rule_queries.GROUP_KINDS
        if is_group and not current.enabled:
            used = await rule_queries.count_enabled_groups(owner_id)
            if not await enforce(owner_id, "archive_groups", need=1, current=used):
                raise HTTPException(status_code=403, detail="limit_reached")
    await rules.set_rule(
        owner_id,
        chat_id,
        body.kind,
        enabled=body.enabled,
        media_enabled=body.media_enabled,
        notify=body.notify,
    )
    return await _state(owner_id)
