"""机坪消防设施接口：灭火器材台账登记、检查状态流转、当班检查清单导出。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.firefacility import FirefacilityService

router = APIRouter(prefix="/api/firefacility", tags=["机坪消防设施"])

service = FirefacilityService()

STATUSES = ["待检查", "检查中", "待更换", "合格"]


@router.get("/stats")
def stats() -> dict[str, Any]:
    """状态统计：待检查数等着台账明细实时重算，页首统计卡与总览页共用这份口径。"""
    return service.stats()


@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按器材编号检索"),
    status: str | None = Query(default=None, description="待检查、检查中、待更换、合格"),
) -> dict[str, Any]:
    """导出当班检查清单：与列表同一套过滤口径，清单条数和页面上看到的对得上。"""
    items, total = service.list_entries(keyword=keyword, status=status, page=1, size=10000)
    return {"module": "firefacility", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按器材编号检索"),
    status: str | None = Query(default=None, description="待检查、检查中、待更换、合格"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按器材编号与状态过滤设施台账；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单具灭火器材明细，含完整检查记录；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"灭火器材 {entry_id} 不存在或已注销")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一具灭火器材，归属区域等必填字段缺失时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单具灭火器材执行开始检查、检查合格、标记超期、完成换新；越级动作会被拦下并说明原因。"""
    values = payload.values
    entry, message = service.run_action(
        entry_id,
        str(values.get("action") or "").strip(),
        operator=str(values.get("检查人") or ""),
        ticket=str(values.get("检查单号") or ""),
        cycle_months=values.get("检查周期月数"),
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
