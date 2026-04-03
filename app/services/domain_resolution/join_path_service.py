from __future__ import annotations

from collections import deque
from typing import Any, Dict, List

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolution.models import DomainPlan, DomainPlanJoin


class DomainJoinPathService:
    def get_join_path(self, plan: DomainPlan, to_workspace_table_id: int) -> List[DomainPlanJoin]:
        target = int(to_workspace_table_id)
        root = int(plan.primary.workspace_table_id)
        if target == root:
            return []

        edges: Dict[int, List[DomainPlanJoin]] = {}
        for join in plan.joins:
            edges.setdefault(int(join.from_workspace_table_id), []).append(join)
            edges.setdefault(int(join.to_workspace_table_id), []).append(self.reverse_join(join))

        queue = deque([(root, [])])
        seen = {root}

        while queue:
            current, path = queue.popleft()
            for edge in edges.get(current, []):
                nxt = int(edge.to_workspace_table_id)
                if nxt in seen:
                    continue
                next_path = path + [edge]
                if nxt == target:
                    return next_path
                seen.add(nxt)
                queue.append((nxt, next_path))

        raise ForgeError("Join path not found for table in domain", status_code=400)

    def reverse_join(self, join: DomainPlanJoin) -> DomainPlanJoin:
        join_type = str(join.join_type or "").upper()
        reversed_type = "INNER" if join_type == "INNER" else "LEFT"
        return DomainPlanJoin(
            join_id=f"{join.join_id}:rev",
            from_workspace_table_id=int(join.to_workspace_table_id),
            to_workspace_table_id=int(join.from_workspace_table_id),
            join_type=reversed_type,
            join_spec=self.reverse_join_spec(join.join_spec),
            sort_order=int(join.sort_order),
        )

    def reverse_join_spec(self, join_spec: Dict[str, object]) -> Dict[str, object]:
        spec = dict(join_spec or {})
        on_list = spec.get("on") or []
        reversed_on: List[Dict[str, Any]] = []
        for item in on_list:
            if not isinstance(item, dict):
                continue
            reversed_item = dict(item)
            reversed_item["left"] = dict(item.get("right") or {})
            reversed_item["right"] = dict(item.get("left") or {})
            reversed_on.append(reversed_item)
        spec["on"] = reversed_on
        return spec
