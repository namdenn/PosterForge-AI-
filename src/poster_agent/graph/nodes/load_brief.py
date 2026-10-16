"""Read a JSON campaign brief from disk."""

import asyncio
import json
from pathlib import Path
from typing import Any

from poster_agent.domain.enums import CampaignStatus
from poster_agent.graph.state import CampaignState


async def load_brief(state: CampaignState) -> CampaignState:
    """Load JSON without performing domain validation."""

    brief_path = Path(state["brief_path"])
    try:
        content = await asyncio.to_thread(brief_path.read_text, encoding="utf-8")
        decoded: Any = json.loads(content)
        if not isinstance(decoded, dict):
            raise ValueError("the JSON root must be an object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "status": CampaignStatus.FAILED,
            "validation_errors": [f"Cannot load brief '{brief_path}': {exc}"],
        }

    return {
        "raw_brief": decoded,
        "status": CampaignStatus.VALIDATING,
        "validation_errors": [],
    }
