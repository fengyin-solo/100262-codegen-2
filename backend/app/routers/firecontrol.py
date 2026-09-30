"""机坪消防设施（灭火器材）接口。

覆盖设施台账登记/筛选、开始检查、提交合格、提交到期未换、完成换新的状态流转，
以及检查明细查询与当班检查清单导出。台账列表自带随明细重算的待检查等统计。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.firecontrol import FirecontrolService

router = APIRouter(prefix="/api/firecontrol", tags=["机坪消防"])

service = FirecontrolService()

LIST_FIELDS = [
    "器材编号", "器材类型", "规格型号", "归属区域", "存放位置",
    "检查批次", "检查人", "检查时间", "检查结果",
    "上次检查日", "下次检查日", "到期原因", "更换人", "更换时间",
]
RECORD_FIELDS = ["器材编号", "归属区域", "检查批次", "动作", "检查人", "时间", "检查结果", "到期原因"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按器材编号检索"),
    status: str | None = Query(default=None, description="待检查、检查中、合格、待更换"),
    area: str | None = Query(default=None, description="按归属区域检索，跨区域器材必须写明归属"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按器材编号、状态与归属区域过滤消防设施台账；stats 与明细同源重算。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, area=area, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size, stats=service.stats())


@router.get("/records", response_model=PageResult[dict])
def list_records(
    keyword: str | None = Query(default=None, description="按器材编号检索"),
    area: str | None = Query(default=None, description="按归属区域检索"),
    batch: str | None = Query(default=None, description="按检查批次检索"),
    day: str | None = Query(default=None, description="按检查日期（YYYY-MM-DD）检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """查询检查留痕明细；动作、检查人与时间在此完整可查。"""
    if size > 500:
        raise HTTPException(status_code=400, detail="每页最多 500 条，请缩小分页范围")
    items, total = service.list_records(
        keyword=keyword, area=area, batch=batch, day=day, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    keyword: str | None = None,
    status: str | None = None,
    area: str | None = None,
    day: str | None = Query(default=None, description="当班检查日，默认取当天，仅用于附带的检查留痕"),
) -> dict[str, Any]:
    """导出当班检查清单。

    清单的器材条数与页面列表完全一致：筛选条件（keyword/status/area）与
    GET /api/firecontrol 同源，返回的 total/items 就是页面上看到的口径。
    另外附上当班（默认当天）的检查留痕记录，便于核对每一步的检查人与时间。
    """
    items, total = service.list_entries(
        keyword=keyword, status=status, area=area, page=1, size=10000
    )
    target_day = day or date.today().isoformat()
    records, record_total = service.list_records(
        keyword=keyword, area=area, batch=None, day=target_day, page=1, size=10000
    )
    return {
        "module": "firecontrol",
        "day": target_day,
        # 清单条数以页面台账口径为准，前端按这个数与页面 total 核对
        "total": total,
        "items": items,
        "fields": LIST_FIELDS,
        "records": records,
        "record_total": record_total,
    }


@router.get("/stats")
def entry_stats() -> dict[str, int]:
    """设施台账上的待检查/检查中/合格/待更换数量，随检查明细一起重算。"""
    return service.stats()


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单具灭火器材台账明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"灭火器材 {entry_id} 不存在或已下架")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一具灭火器材（必须写明归属区域），初始状态为待检查。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段或编号重复：{'、'.join(missing)}")
    return ActionResult(ok=True, message="灭火器材已登记，等待检查", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """开始检查/提交合格/提交到期未换/完成换新；跳级、缺检查人、重复提交都会被拦下。"""
    entry, message = service.run_action(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
