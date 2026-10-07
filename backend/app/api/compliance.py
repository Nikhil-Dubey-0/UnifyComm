from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentAgent, RulesDep, SessionDep
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.compliance import ComplianceLogItem
from app.schemas.system import ComplianceRuleOut
from app.services import compliance_log

router = APIRouter(prefix="/compliance", tags=["compliance"], responses=ERROR_RESPONSES)


@router.get("/rules")
async def compliance_rules(rules: RulesDep, _: CurrentAgent) -> list[ComplianceRuleOut]:
    return [ComplianceRuleOut(rule_id=r.rule_id, description=r.description) for r in rules]


@router.get("/checks")
async def compliance_checks(
    session: SessionDep,
    _: CurrentAgent,
    passed: bool | None = None,
    rule_id: Annotated[str | None, Query(max_length=100)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[ComplianceLogItem]:
    return await compliance_log.list_checks(
        session, passed=passed, rule_id=rule_id, cursor=cursor, limit=limit
    )
