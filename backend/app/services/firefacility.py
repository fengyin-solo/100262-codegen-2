"""机坪消防设施业务规则：灭火器材检查状态流转、检查记录与台账重算都收在这里。

状态主线：待检查 → 检查中 → 合格；超期未换流转到 待更换，完成换新后回到 合格
并留下新的检查周期。状态只能顺着这条线走，不允许跳级，也不允许回退。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "firefacility"
REQUIRED_FIELDS = ["器材编号", "器材类型", "归属区域"]
STATUS_ORDER = ["待检查", "检查中", "待更换", "合格"]
FINAL_STATUS = "合格"
DEFAULT_CYCLE_MONTHS = 12

# 每个动作允许的起始状态与目标状态：跳级（如待检查直接标合格）在这里被拦下
ACTION_RULES: dict[str, dict[str, Any]] = {
    "开始检查": {"from": {"待检查"}, "to": "检查中"},
    "检查合格": {"from": {"检查中"}, "to": "合格"},
    "标记超期": {"from": {"待检查", "检查中"}, "to": "待更换"},
    "完成换新": {"from": {"待更换"}, "to": "合格"},
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _add_months(today: date, months: int) -> date:
    """推算 n 个月后的日期，作为换新后的下一次检查日期。"""
    month = today.month - 1 + months
    year = today.year + month // 12
    month = month % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(today.day, days[month - 1]))


class FirefacilityService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("器材编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        for row in rows:
            self._normalize(row)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            self._normalize(entry)
        return entry

    def stats(self) -> dict[str, Any]:
        """按状态实时清点台账：总览页与页首统计卡都以这份明细为准。"""
        counts = {status: 0 for status in STATUS_ORDER}
        for row in store.rows(MODULE):
            counts[row.get("status", "")] = counts.get(row.get("status", ""), 0) + 1
        return {"total": sum(counts.values()), "counts": counts}

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}（跨区域的器材必须写明归属区域）"
        rows = store.rows(MODULE)
        code = str(values.get("器材编号")).strip()
        if any(str(row.get("器材编号", "")).strip() == code for row in rows):
            return None, f"器材编号 {code} 已登记，同一具灭火器材不能重复建账"
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ["器材编号", "器材类型", "归属区域", "存放位置", "下次检查日期"]:
            entry[field] = values.get(field)
        entry["检查人"] = ""
        entry["检查时间"] = ""
        entry["status"] = STATUS_ORDER[0]
        entry["器材状态"] = STATUS_ORDER[0]
        entry["检查周期月数"] = DEFAULT_CYCLE_MONTHS
        entry["检查记录"] = []
        entry["已受理单号"] = []
        self._normalize(entry)
        rows.append(entry)
        return entry, "灭火器材已登记入账，状态为待检查"

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str = "",
        ticket: str = "",
        cycle_months: Any = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"灭火器材 {entry_id} 不存在或已注销"
        self._normalize(entry)
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于灭火器材检查可执行范围"
        ticket = ticket.strip()
        if ticket and ticket in entry["已受理单号"]:
            return entry, f"检查单 {ticket} 已受理过，同一具器材的同一次检查只生效第一次，本次重复提交未再流转"
        operator = operator.strip()
        if not operator:
            if action == "检查合格":
                return None, "检查人缺失，不允许结束检查"
            return None, f"请填写检查人后再执行「{action}」，每一步都要记下检查人和时间"
        rule = ACTION_RULES[action]
        current = str(entry.get("status", ""))
        if current not in rule["from"]:
            expected = "、".join(sorted(rule["from"], key=STATUS_ORDER.index))
            return None, (
                f"当前状态为「{current}」，不能执行「{action}」（需处于：{expected}）；"
                "状态只能按 待检查→检查中→合格 顺线流转，不允许跳级直接标合格"
            )
        target = str(rule["to"])
        entry["status"] = target
        entry["器材状态"] = target
        entry["检查人"] = operator
        entry["检查时间"] = _now()
        extra = ""
        if action == "完成换新":
            months = self._cycle_months(cycle_months, entry)
            entry["检查周期月数"] = months
            entry["下次检查日期"] = _add_months(date.today(), months).isoformat()
            extra = f"，新检查周期 {months} 个月，下次检查日期 {entry['下次检查日期']}"
        entry["检查记录"].append({
            "时间": entry["检查时间"],
            "动作": action,
            "原状态": current,
            "新状态": target,
            "检查人": operator,
            "检查单号": ticket,
        })
        if ticket:
            entry["已受理单号"].append(ticket)
        self._normalize(entry)
        return entry, f"灭火器材已{action}，当前状态：{target}{extra}"

    def _cycle_months(self, cycle_months: Any, entry: dict[str, Any]) -> int:
        try:
            months = int(cycle_months or entry.get("检查周期月数") or DEFAULT_CYCLE_MONTHS)
        except (TypeError, ValueError):
            months = DEFAULT_CYCLE_MONTHS
        return months if months > 0 else DEFAULT_CYCLE_MONTHS

    def _normalize(self, entry: dict[str, Any]) -> None:
        """台账派生字段跟着检查明细重算：待处理、异常与镜像状态都以当前状态为准。"""
        entry.setdefault("检查记录", [])
        entry.setdefault("已受理单号", [])
        entry.setdefault("检查周期月数", DEFAULT_CYCLE_MONTHS)
        entry["器材状态"] = entry.get("status", STATUS_ORDER[0])
        entry["pending"] = entry.get("status") != FINAL_STATUS
        entry["abnormal"] = entry.get("status") == "待更换"
