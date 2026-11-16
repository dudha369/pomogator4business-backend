"""Шаблоны быстрых ответов (команда .t). Подстановки: {name}, {full_name}."""

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_user
from api.schemas import Template
from app.features.templates import service as templates_db

router = APIRouter()

MAX_TEMPLATES = 50
_NAME_RE = re.compile(r"^\S{1,32}$")


class TemplatesOut(BaseModel):
    templates: list[Template]


class TemplateDeleted(BaseModel):
    deleted: Literal[True]


@router.get("/templates", response_model=TemplatesOut)
async def list_templates(user: dict = Depends(require_user)):
    return {"templates": await templates_db.list_templates(user["id"])}


class TemplateSave(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=4096)


@router.post("/templates", response_model=Template)
async def save_template(payload: TemplateSave, user: dict = Depends(require_user)):
    name = payload.name.strip().lower()
    if not _NAME_RE.match(name):
        raise HTTPException(
            status_code=400, detail="Name must be 1-32 characters without spaces"
        )
    if not payload.text.strip():
        raise HTTPException(status_code=422, detail="Text must not be blank")

    exists = await templates_db.get_template(user["id"], name) is not None
    if not exists and await templates_db.count_templates(user["id"]) >= MAX_TEMPLATES:
        raise HTTPException(status_code=400, detail="Too many templates")

    await templates_db.save_template(user["id"], name, payload.text)
    return {"name": name, "text": payload.text}


@router.delete("/templates/{name}", response_model=TemplateDeleted)
async def delete_template(name: str, user: dict = Depends(require_user)):
    if not await templates_db.delete_template(user["id"], name.strip().lower()):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"deleted": True}
