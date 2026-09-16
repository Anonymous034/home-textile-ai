from __future__ import annotations

from pathlib import Path


def inspect_mock_output(path: Path) -> tuple[str, dict[str, float | None]]:
    """真实阈值必须用50组素材标定；模拟结果永远不能通过专业质量门槛。"""
    return "mock_unverified", {
        "identity": None,
        "body_and_clothing": None,
        "furniture_structure": None,
        "material_fidelity": None,
        "contact_and_occlusion": None,
        "lighting_consistency": None,
        "perspective": None,
    }
