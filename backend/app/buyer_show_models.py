"""Strict engine-neutral lifestyle planning contract."""
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .detail_models import AssetRef, StrictModel

Style = Literal["更真实", "更精致"]
AspectRatio = Literal["3:4", "16:9", "1:1", "4:3", "9:16"]
Resolution = Literal["1K", "2K", "4K"]
SHOT_TYPES = ("全景体验图", "中景功能展现图", "细节材质特写图", "人货交互使用图")
ANGLES = (
    "eye-level wide view with environmental context",
    "three-quarter medium view demonstrating the product function",
    "close-up of the actual product material and construction",
    "over-the-shoulder view of a plausible real person using the product",
    "low wide angle showing the product in the same lived-in environment",
    "side-on medium view showing a different functional detail",
    "oblique close-up of a different seam, finish or material transition",
    "side view of a different natural product-use action",
    "doorway or contextual foreground wide composition",
    "high three-quarter view of another plausible use arrangement",
    "raking-light close-up of a previously unseen construction detail",
    "eye-level interaction showing the product after a natural use action",
)


class BuyerPlanRequest(StrictModel):
    product_name: str = Field(min_length=1, max_length=120)
    product_features: str = Field(default="", max_length=3000)
    material: str = Field(default="", max_length=1000)
    style: Style
    image_count: int = Field(ge=1, le=12, strict=True)
    aspect_ratio: AspectRatio
    resolution: Resolution
    scene_preferences: str = Field(default="", max_length=1000)
    selling_points: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=1000)
    assets: list[AssetRef] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def source_required(self):
        if not self.product_name.strip():
            raise ValueError("请提供产品名称")
        if not self.product_features.strip() and not self.assets:
            raise ValueError("请提供产品特征描述或至少一张已上传产品图")
        if len({asset.id for asset in self.assets}) != len(self.assets):
            raise ValueError("产品素材编号不能重复")
        return self


class LifestyleImage(StrictModel):
    index: int = Field(ge=1, le=12, strict=True)
    shot_type: Literal["全景体验图", "中景功能展现图", "细节材质特写图", "人货交互使用图"]
    scene_description: str = Field(min_length=1, max_length=2000)
    image_prompt: str = Field(min_length=1, max_length=9000)
    negative_prompt: str = Field(min_length=1, max_length=2500)

    @field_validator("scene_description")
    @classmethod
    def chinese_description(cls, value):
        if not re.search(r"[\u3400-\u9fff]", value):
            raise ValueError("场景描述必须为中文")
        return value

    @field_validator("image_prompt", "negative_prompt")
    @classmethod
    def english_prompt(cls, value):
        if not re.search(r"[a-zA-Z]", value) or re.search(r"[\u3400-\u9fff]", value):
            raise ValueError("渲染提示词与负向提示词必须为英文")
        return value


class LifestylePlan(StrictModel):
    project_title: str = Field(min_length=1, max_length=240)
    aspect_ratio: AspectRatio
    resolution: Resolution
    image_plan: list[LifestyleImage] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def ordered_diverse_set(self):
        if not self.project_title.strip():
            raise ValueError("项目标题不能为空")
        if [item.index for item in self.image_plan] != list(range(1, len(self.image_plan) + 1)):
            raise ValueError("图序号必须从 1 连续递增")
        scenes = [re.sub(r"\W", "", item.scene_description).casefold() for item in self.image_plan]
        prompts = [" ".join(item.image_prompt.lower().split()) for item in self.image_plan]
        if len(set(scenes)) != len(scenes) or len(set(prompts)) != len(prompts):
            raise ValueError("套图不能重复使用相同场景描述或提示词")
        for index, item in enumerate(self.image_plan):
            if item.shot_type != SHOT_TYPES[index % len(SHOT_TYPES)]:
                raise ValueError("景别必须遵循全景、功能中景、材质特写、人货交互的套图顺序")
        return self


class BuyerRenderRequest(StrictModel):
    taskId: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    planId: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    input: BuyerPlanRequest
    plan: LifestylePlan

    @model_validator(mode="after")
    def confirmed_plan_matches_input(self):
        validate_output(self.plan.model_dump(), self.input)
        return self


def shot_schedule(count: int) -> list[dict]:
    return [{"index": index + 1, "shot_type": SHOT_TYPES[index % 4], "camera_direction": ANGLES[index]} for index in range(count)]


def validate_output(payload: object, request: BuyerPlanRequest) -> LifestylePlan:
    plan = LifestylePlan.model_validate(payload)
    if len(plan.image_plan) != request.image_count or plan.aspect_ratio != request.aspect_ratio or plan.resolution != request.resolution:
        raise ValueError("返回的图片张数、比例或分辨率与用户选择不一致")
    return plan
