"""机坪消防设施（灭火器材）业务规则。

状态只能顺着 待检查→检查中→合格 这条线往前走；检查中发现超期未换的流转到
待更换，换新完成后重新回到合格并开启新的检查周期。每一步都记录检查人与时间，
同一具器材同一检查批次的提交只生效第一次。设施台账、检查明细与总览的待检查数
都由本模块在每次动作后统一重算。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "firecontrol"
RECORD_MODULE = "firecontrol_records"

REQUIRED_FIELDS = ["器材编号", "器材类型", "归属区域", "存放位置", "检查批次"]

# 状态机：只允许沿下列边顺向流转，不允许跳级（如 待检查 直接标 合格）
STATUS_FLOW: dict[str, dict[str, str]] = {
    "待检查": {"开始检查": "检查中"},
    "检查中": {"提交合格": "合格", "提交到期未换": "待更换"},
    "合格": {},
    "待更换": {"完成换新": "合格"},
}
ALL_STATUSES = ["待检查", "检查中", "合格", "待更换"]
PENDING_STATUS = "待检查"
ABNORMAL_STATUS = "待更换"

# 换新后开启的新检查周期（月）
INSPECTION_CYCLE_MONTHS = 12

# 需要检查人的动作：检查人缺失时一律不允许结束/推进检查
INSPECTOR_ACTIONS = ["开始检查", "提交合格", "提交到期未换", "完成换新"]
# 会结束一次检查的动作，做“同一批次只生效第一次”的幂等控制
SUBMIT_ACTIONS = ["提交合格", "提交到期未换"]

# 初始化为模块装载时标记检查明细为内部表，不进总览模块列表（集中在 Store 初始化处声明）


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    # 月末日期做钳制（如 1/31 加一个月落在 2 月时取 2 月最后一天）
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_of_month = date.fromordinal(next_month_first.toordinal() - 1)
    return date(year, month, min(day.day, last_of_month.day))


def _today() -> date:
    return date.today()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class FirecontrolService:
    # ---------- 设施台账 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        area: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("器材编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if area:
            rows = [row for row in rows if area in str(row.get("归属区域", ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        code = str(values.get("器材编号") or "").strip()
        if any(str(row.get("器材编号") or "").strip() == code for row in rows):
            return None, ["器材编号重复"]
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        entry.update({
            "规格型号": str(values.get("规格型号") or "").strip(),
            "status": "待检查",
            "pending": True,
            "abnormal": False,
            "检查人": "",
            "检查时间": "",
            "检查结果": "",
            "上次检查日": "",
            "下次检查日": "",
            "到期原因": "",
            "更换人": "",
            "更换时间": "",
        })
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"灭火器材 {entry_id} 不存在或已下架"

        action = str(values.get("action") or "").strip()
        known_actions = {name for edge in STATUS_FLOW.values() for name in edge}
        if action not in known_actions:
            return None, f"动作「{action}」不属于灭火器材检查可执行范围"

        inspector = str(values.get("检查人") or "").strip()
        if action in INSPECTOR_ACTIONS and not inspector:
            return None, f"检查人缺失，不允许{action}；请先登记检查人再结束本次检查"

        batch = str(entry.get("检查批次") or "").strip()
        records = store.rows(RECORD_MODULE)

        # 幂等：同一具器材、同一检查批次的检查提交只生效第一次。
        # 放在状态校验之前，保证并发/重放的第二次提交即使在状态已变更后也能被明确拦下。
        if action in SUBMIT_ACTIONS:
            for record in records:
                if (
                    str(record.get("器材编号") or "") == str(entry.get("器材编号") or "")
                    and str(record.get("检查批次") or "") == batch
                    and str(record.get("动作") or "") in SUBMIT_ACTIONS
                ):
                    return None, (
                        f"器材 {entry.get('器材编号')} 在检查批次「{batch}」已提交过检查结果"
                        f"（{record.get('动作')}），同一批次重复提交只生效第一次"
                    )

        current = str(entry.get("status") or "")
        allowed = STATUS_FLOW.get(current, {})
        if action not in allowed:
            return None, f"器材当前为「{current}」，不能执行「{action}」，状态只能顺向流转，不允许跳级"

        stamp = _now_text()
        target = allowed[action]
        result = str(values.get("检查结果") or "").strip()
        reason = str(values.get("到期原因") or "").strip()

        if action == "开始检查":
            entry["检查人"] = inspector
            entry["检查时间"] = stamp
            record_action = action
        elif action == "提交合格":
            entry["检查人"] = inspector
            entry["检查时间"] = stamp
            entry["检查结果"] = result or "合格"
            today = _today()
            entry["上次检查日"] = today.isoformat()
            entry["下次检查日"] = _add_months(today, INSPECTION_CYCLE_MONTHS).isoformat()
            entry["到期原因"] = ""
            record_action = action
        elif action == "提交到期未换":
            entry["检查人"] = inspector
            entry["检查时间"] = stamp
            entry["检查结果"] = "到期未换"
            entry["到期原因"] = reason or "检查周期已超期，器材未按期更换"
            record_action = action
        else:  # 完成换新
            entry["更换人"] = inspector
            entry["更换时间"] = stamp
            entry["检查人"] = inspector
            entry["检查时间"] = stamp
            entry["检查结果"] = result or "换新后合格"
            entry["到期原因"] = ""
            today = _today()
            entry["上次检查日"] = today.isoformat()
            entry["下次检查日"] = _add_months(today, INSPECTION_CYCLE_MONTHS).isoformat()
            record_action = action

        entry["status"] = target
        self._recompute_flags(entry)

        records.append({
            "id": max((int(row.get("id", 0)) for row in records), default=0) + 1,
            "器材编号": entry.get("器材编号", ""),
            "归属区域": entry.get("归属区域", ""),
            "检查批次": batch,
            "动作": record_action,
            "检查人": inspector,
            "时间": stamp,
            "检查结果": entry.get("检查结果", ""),
            "到期原因": entry.get("到期原因", ""),
        })
        return entry, f"器材 {entry.get('器材编号')} 已{action}，当前状态：{target}"

    def _recompute_flags(self, entry: dict[str, Any]) -> None:
        """台账行的待处理/异常标记跟随检查明细状态一起重算。"""
        status = str(entry.get("status") or "")
        entry["pending"] = status == PENDING_STATUS
        entry["abnormal"] = status == ABNORMAL_STATUS

    # ---------- 检查明细 ----------
    def list_records(
        self,
        *,
        keyword: str | None = None,
        area: str | None = None,
        batch: str | None = None,
        day: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(RECORD_MODULE))
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("器材编号", ""))]
        if area:
            rows = [row for row in rows if area in str(row.get("归属区域", ""))]
        if batch:
            rows = [row for row in rows if batch in str(row.get("检查批次", ""))]
        if day:
            rows = [row for row in rows if str(row.get("时间", "")).startswith(day)]
        # 明细按时间倒序，最新动作在最前
        rows.sort(key=lambda row: str(row.get("时间", "")), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    # ---------- 汇总指标：与检查明细、台账状态同源重算 ----------
    def stats(self) -> dict[str, int]:
        rows = store.rows(MODULE)
        counts = {status: 0 for status in ALL_STATUSES}
        for row in rows:
            status = str(row.get("status") or "")
            if status in counts:
                counts[status] += 1
        return {
            "待检查": counts["待检查"],
            "检查中": counts["检查中"],
            "合格": counts["合格"],
            "待更换": counts["待更换"],
            "器材总数": len(rows),
        }
