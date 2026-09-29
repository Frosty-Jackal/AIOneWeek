"""采集编排：幂等、补采、成本累计、降级（Spec1 §5.1 / §5.4 / §5.5 / §9）。"""

from __future__ import annotations

import json
import logging
from datetime import date as date_cls
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import deepseek, parser
from .config import settings
from .db import SessionLocal, now_iso
from .models import AdminAudit, DailyRun, DailyTech, SourceSite

logger = logging.getLogger(__name__)

DEGRADE_SUFFIX = "（未经联网核验）"

# Spec1 §5.1 —— 模板原样，不得改写
PROMPT_TEMPLATE = """请爬 {date} 的 AI 前沿技术，要求有创新或者性能相较以前有明显提升，若性能提升或创新性不足，甚至可以不用列出，列出的技术个数最多不超过 {max_items} 个，无则 return 无，参考以下网站：
{sites}

给出技术名字，这个技术大概是干嘛的（从应用的角度），这个技术相比于以前的技术创新 or 性能明显提高在哪里，可能能应用的场景（列 3 个），发布时间，参考链接。
示例，你仅能返回这样的格式：
【技术名】StableDiffusionv2.1
【技术内容】输入条件（例如文本），输出符合条件的图像
【技术创新】让图像生成性能大增
【应用场景】海报制作、图像超分、图像修复
【发布时间】2022年9月10日
【参考链接】xxxx
"""


# --- 日期工具（全项目统一 YYYY-MM-DD 存储）---


def today_str() -> str:
    return date_cls.today().isoformat()


def week_dates(today: str | None = None) -> list[str]:
    """当天 + 前 6 天，共 7 天，倒序（Spec1 §6.2 步骤 1）。"""
    base = date_cls.fromisoformat(today) if today else date_cls.today()
    return [(base - timedelta(days=i)).isoformat() for i in range(settings.week_window_days)]


def format_prompt_date(day: str) -> str:
    """Prompt 内的日期统一用 YYYY年M月D日（Spec1 §5.1 二选一）。"""
    d = date_cls.fromisoformat(day)
    return f"{d.year}年{d.month}月{d.day}日"


# --- 查询helper ---


def enabled_sites(db: Session) -> list[str]:
    rows = db.scalars(
        select(SourceSite).where(SourceSite.enabled == 1).order_by(SourceSite.id)
    ).all()
    return [row.url for row in rows]


def daily_cost(db: Session, day: str) -> float:
    """当日所有 daily_run.cost_cny 之和（Spec1 §9）。"""
    total = db.scalar(
        select(func.coalesce(func.sum(DailyRun.cost_cny), 0.0)).where(DailyRun.date == day)
    )
    return float(total or 0.0)


def build_prompt(db: Session, day: str) -> str:
    sites = "\n".join(enabled_sites(db)) or "（未配置参考网站，请凭已有知识回答）"
    return PROMPT_TEMPLATE.format(
        date=format_prompt_date(day),
        max_items=settings.max_items_per_day,
        sites=sites,
    )


def write_audit(db: Session, admin_id: int | None, action: str, target: str | None = None) -> None:
    """Spec1 §10 审计。系统自动触发时 admin_id 记为 0。"""
    db.add(
        AdminAudit(
            admin_id=admin_id or 0,
            action=action,
            target=target,
            created_at=now_iso(),
        )
    )


# --- 采集主流程 ---


def collect(
    day: str,
    force: bool = False,
    db: Session | None = None,
    admin_id: int | None = None,
) -> DailyRun:
    """对指定日期执行一次采集。对同一日期重复调用不产生重复条目、不重复计费。"""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        return _collect(db, day, force, admin_id)
    finally:
        if own_session:
            db.close()


def _collect(db: Session, day: str, force: bool, admin_id: int | None) -> DailyRun:
    run = db.scalar(select(DailyRun).where(DailyRun.date == day))

    # 幂等：非强制刷新时，已有终态记录直接返回（§5.4）
    if run and not force and run.status in (parser.STATUS_SUCCESS, parser.STATUS_EMPTY):
        return run

    # 成本护栏（§9）→ 降级（§5.5）
    degrade_mode = daily_cost(db, day) >= settings.cost_daily_limit_cny

    prompt = build_prompt(db, day)
    stamp = now_iso()

    try:
        result = deepseek.call_deepseek(prompt, use_search=not degrade_mode)
    except deepseek.DeepSeekError as exc:
        logger.warning("采集 %s 失败：%s", day, exc)
        # 错误描述必须留在最前面：上游限流判定读的就是这一段。
        # 原始返回附在其后，否则失败日只剩一句笼统描述，事后无从追查。
        raw = f"[调用失败] {exc}"
        if exc.raw:
            raw = f"{raw}\n\n--- 原始返回 ---\n{exc.raw[:20000]}"
        run = _upsert_run(db, run, day, parser.STATUS_FAILED, prompt, raw, 0, 0.0, stamp)
        db.commit()
        db.refresh(run)
        return run

    status, items = parser.parse(result.text, settings.max_items_per_day)

    if degrade_mode:
        write_audit(db, admin_id, "cost_limit_degrade", day)
        # §5.5 要求降级结果标记为 success 并加后缀；但若模型确实没给出可解析
        # 条目，强行写 success 会造出「success 却 0 条」的空卡片，故此处保留
        # 解析出的真实状态（empty / parse_failed），只对有条目的情况打标。
        if items:
            for item in items:
                item["tech_name"] = f"{item['tech_name']}{DEGRADE_SUFFIX}"
            status = parser.STATUS_SUCCESS

    run = _upsert_run(
        db, run, day, status, prompt, result.raw, len(items), result.cost_cny, stamp
    )

    # 重采时先清旧条目，保证 seq 无重复（§5.4）
    db.execute(delete(DailyTech).where(DailyTech.date == day))
    if status == parser.STATUS_SUCCESS:
        for seq, item in enumerate(items):
            db.add(
                DailyTech(
                    date=day,
                    seq=seq,
                    tech_name=item["tech_name"],
                    tech_content=item["tech_content"],
                    innovation=item["innovation"],
                    scenarios=json.dumps(item["scenarios"], ensure_ascii=False),
                    publish_date=item.get("publish_date"),
                    ref_link=item.get("ref_link"),
                )
            )

    db.commit()
    db.refresh(run)
    return run


def _upsert_run(
    db: Session,
    run: DailyRun | None,
    day: str,
    status: str,
    prompt: str,
    raw: str | None,
    item_count: int,
    cost_cny: float,
    stamp: str,
) -> DailyRun:
    if run is None:
        run = DailyRun(
            date=day,
            status=status,
            prompt=prompt,
            raw_response=raw,
            item_count=item_count,
            cost_cny=cost_cny,
            created_at=stamp,
            updated_at=stamp,
        )
        db.add(run)
    else:
        run.status = status
        run.prompt = prompt
        run.raw_response = raw
        run.item_count = item_count
        run.cost_cny = cost_cny  # 覆盖而非累加：同日期不重复计费
        run.updated_at = stamp
    db.flush()
    return run
