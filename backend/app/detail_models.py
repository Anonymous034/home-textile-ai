"""Validated wire contract shared by planning and confirmed rendering."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputParams(StrictModel):
    productName: str = Field(min_length=1, max_length=120)
    fabric: str = Field(default="", max_length=500)
    craftsmanship: str = Field(default="", max_length=500)
    specifications: str = Field(default="", max_length=500)
    sellingPoints: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=1000)
    language: Literal["zh-CN", "en", "es", "fr", "de", "ja", "ko"]
    imageCount: int = Field(ge=1, le=12)
    aspectRatio: Literal["9:16", "3:4", "1:1", "4:3", "16:9"]
    resolution: Literal["1K", "2K", "4K"]

    @model_validator(mode="after")
    def nonblank_name(self):
        if not self.productName.strip():
            raise ValueError("产品名称不能为空")
        return self


class Overlay(StrictModel):
    headline: str = Field(max_length=200)
    body: str = Field(max_length=1000)
    placement: Literal["top", "center", "bottom", "left", "right"]


class PlanItem(StrictModel):
    id: Identifier
    order: int = Field(ge=1, le=12)
    theme: str = Field(min_length=1, max_length=120)
    visualDescription: str = Field(min_length=1, max_length=2000)
    stylePrompt: str = Field(min_length=1, max_length=1000)
    textOverlay: Overlay
    sourceImageIds: list[Identifier] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def nonblank_text(self):
        if not all(value.strip() for value in (self.theme, self.visualDescription, self.stylePrompt)):
            raise ValueError("主题、展示内容和风格不能为空")
        return self


class PlanDocument(StrictModel):
    schemaVersion: Literal["1.0"] = "1.0"
    planId: Identifier
    revision: int = Field(ge=1)
    source: Literal["ai"] = "ai"
    input: InputParams
    items: list[PlanItem] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def sequence(self):
        if len(self.items) != self.input.imageCount:
            raise ValueError("图片张数与方案不一致")
        if [item.order for item in self.items] != list(range(1, len(self.items) + 1)):
            raise ValueError("方案顺序必须从 1 开始连续排列")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("方案卡片 ID 重复")
        return self


class AssetRef(StrictModel):
    id: Identifier
    assetId: Identifier
    role: Literal["main", "detail", "scene"]


class PlanRequest(StrictModel):
    input: InputParams
    assets: list[AssetRef] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_assets(self):
        if len({asset.id for asset in self.assets}) != len(self.assets) or not any(asset.role == "main" for asset in self.assets):
            raise ValueError("素材编号必须唯一，且至少包含一张主图")
        return self


class RenderRequest(PlanRequest):
    taskId: Identifier
    plan: PlanDocument

    @model_validator(mode="after")
    def confirmed_input(self):
        if self.input != self.plan.input:
            raise ValueError("必须使用确认方案中的参数")
        allowed = {asset.id for asset in self.assets}
        if any(not set(item.sourceImageIds).issubset(allowed) for item in self.plan.items):
            raise ValueError("方案引用了未知产品素材")
        return self
