from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env", override=True)

from app.providers.ark import AgentPlanSeedreamSkillProvider  # noqa: E402
from app.providers.base import ProviderRequest  # noqa: E402


def existing_path(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"图片不存在：{path}")
    return path


async def run(args: argparse.Namespace) -> Path:
    provider = AgentPlanSeedreamSkillProvider()
    request = ProviderRequest(
        job_id=f"agent_plan_test_{uuid4().hex}",
        furniture_path=args.main_view,
        model_path=args.model_image,
        scene_path=args.scene_image,
        composition_id="uploaded-composition",
        composition_path=args.composition_image,
        width=1536,
        height=2048,
        output_count=1,
        guidance=args.guidance,
    )
    await provider.submit_job(request)
    outputs = await provider.get_outputs(request)
    return outputs[0].path


def main() -> None:
    parser = argparse.ArgumentParser(description="执行一次 Agent Plan Seedream 四图融合测试")
    parser.add_argument("--main-view", required=True, type=existing_path)
    parser.add_argument("--model-image", required=True, type=existing_path)
    parser.add_argument("--scene-image", required=True, type=existing_path)
    parser.add_argument("--composition-image", required=True, type=existing_path)
    parser.add_argument("--guidance", default="")
    args = parser.parse_args()
    output = asyncio.run(run(args))
    print(f"RESULT_PATH={output}")


if __name__ == "__main__":
    main()
