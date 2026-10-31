"""Skills for frontend completion menus."""

from typing import Any
from fastapi import APIRouter
from abstract.skills.loader import list_skills
from entity.constant import Namespace
from interface.api_component import APIComponent
from interface.sandbox import ISandbox


class ListSkillsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/skills/list", self.handler, methods=["GET"], name="skills_list")

    async def handler(self) -> dict[str, Any]:
        """List available skills with name, description and category for completion."""
        skills_dir = self.get_system(ISandbox).get_base(Namespace.SKILLS)
        if not skills_dir.exists():
            return {"skills": [], "total": 0}
        skills = list_skills(skills_dir=skills_dir)
        return {"skills": [{"name": item["name"], "description": item.get("description", ""), "category": item.get("category")} for item in skills], "total": len(skills)}


api = ListSkillsAPI()
