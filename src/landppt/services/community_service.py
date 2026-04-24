"""
Community operations service:
- daily check-in
- registration invite codes
- sponsor thank-you page
- site notice banner
"""

from __future__ import annotations

import logging
import random
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ..database.database import AsyncSessionLocal
from ..database.models import (
    CreditTransaction,
    DailyCheckIn,
    InviteCode,
    InviteCodeUsage,
    SponsorProfile,
    UserConfig,
    User,
)
from ..database.repositories import UserConfigRepository

logger = logging.getLogger(__name__)


class CommunityService:
    SETTINGS_CATEGORY = "community_ops"
    CHECKIN_RESET_HOUR = 8
    CHECKIN_TIMEZONE = timezone(timedelta(hours=8))
    CHECKIN_TIMEZONE_NAME = "Asia/Shanghai"
    INVITE_CHANNEL_UNIVERSAL = "universal"
    INVITE_CHANNELS = {"github", "linuxdo", "authentik", "mail", INVITE_CHANNEL_UNIVERSAL}
    INVITE_CHANNEL_LABELS = {
        "github": "GitHub",
        "linuxdo": "LinuxDo",
        "authentik": "Authentik",
        "mail": "Mail",
        INVITE_CHANNEL_UNIVERSAL: "通用渠道",
    }
    SETTINGS_SCHEMA = {
        "daily_checkin_enabled": {"type": "boolean", "default": False},
        "daily_checkin_reward_mode": {"type": "text", "default": "fixed"},
        "daily_checkin_reward_fixed": {"type": "number", "default": 5},
        "daily_checkin_reward_min": {"type": "number", "default": 2},
        "daily_checkin_reward_max": {"type": "number", "default": 8},
        "invite_code_required_for_registration": {"type": "boolean", "default": True},
        "sponsor_page_enabled": {"type": "boolean", "default": False},
        "site_notice_enabled": {"type": "boolean", "default": False},
        "site_notice_level": {"type": "text", "default": "info"},
        "site_notice_title": {"type": "text", "default": ""},
        "site_notice_message": {"type": "text", "default": ""},
        "site_notice_start_at": {"type": "number", "default": 0},
        "site_notice_end_at": {"type": "number", "default": 0},
    }

    def _convert_setting_value(self, value: Any, value_type: str) -> Any:
        if value is None:
            return None
        if value_type == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "on"}
        if value_type == "number":
            try:
                if "." in str(value):
                    return float(value)
                return int(value)
            except Exception:
                return 0
        return str(value).strip()

    def _serialize_setting_value(self, value: Any, value_type: str) -> str:
        if value is None:
            return ""
        if value_type == "boolean":
            return "true" if bool(value) else "false"
        return str(value)

    def _normalize_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, meta in self.SETTINGS_SCHEMA.items():
            raw_value = settings.get(key, meta["default"])
            result[key] = self._convert_setting_value(raw_value, meta["type"])

        reward_mode = str(result["daily_checkin_reward_mode"] or "fixed").strip().lower()
        if reward_mode not in {"fixed", "random"}:
            reward_mode = "fixed"
        result["daily_checkin_reward_mode"] = reward_mode

        result["daily_checkin_reward_fixed"] = max(0, int(result["daily_checkin_reward_fixed"] or 0))
        result["daily_checkin_reward_min"] = max(0, int(result["daily_checkin_reward_min"] or 0))
        result["daily_checkin_reward_max"] = max(0, int(result["daily_checkin_reward_max"] or 0))
        if result["daily_checkin_reward_min"] > result["daily_checkin_reward_max"]:
            result["daily_checkin_reward_min"], result["daily_checkin_reward_max"] = (
                result["daily_checkin_reward_max"],
                result["daily_checkin_reward_min"],
            )

        notice_level = str(result["site_notice_level"] or "info").strip().lower()
        if notice_level not in {"info", "success", "warning", "danger"}:
            notice_level = "info"
        result["site_notice_level"] = notice_level
        result["site_notice_title"] = str(result["site_notice_title"] or "").strip()
        result["site_notice_message"] = str(result["site_notice_message"] or "").strip()

        for key in ("site_notice_start_at", "site_notice_end_at"):
            value = result.get(key)
            try:
                ts_value = float(value or 0)
            except Exception:
                ts_value = 0.0
            result[key] = ts_value if ts_value > 0 else None

        if (
            result["site_notice_start_at"] is not None
            and result["site_notice_end_at"] is not None
            and result["site_notice_start_at"] > result["site_notice_end_at"]
        ):
            result["site_notice_start_at"], result["site_notice_end_at"] = (
                result["site_notice_end_at"],
                result["site_notice_start_at"],
            )
        return result

    def build_public_site_notice(
        self,
        settings: Dict[str, Any],
        *,
        now_ts: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_settings(settings or {})
        if not normalized["site_notice_enabled"]:
            return None

        title = normalized["site_notice_title"]
        message = normalized["site_notice_message"]
        if not title and not message:
            return None

        current_ts = float(time.time() if now_ts is None else now_ts)
        start_at = normalized["site_notice_start_at"]
        end_at = normalized["site_notice_end_at"]

        if start_at is not None and current_ts < float(start_at):
            return None
        if end_at is not None and current_ts > float(end_at):
            return None

        return {
            "active": True,
            "level": normalized["site_notice_level"],
            "title": title,
            "message": message,
            "start_at": start_at,
            "end_at": end_at,
        }

    def build_public_settings_payload(
        self,
        settings: Dict[str, Any],
        *,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        normalized = self._normalize_settings(settings or {})
        return {
            "sponsor_page_enabled": bool(normalized.get("sponsor_page_enabled")),
            "sponsor_page_url": "/sponsors",
            "site_notice": self.build_public_site_notice(normalized, now_ts=now_ts),
        }

    async def _get_settings_with_session(self, session: AsyncSession) -> Dict[str, Any]:
        repo = UserConfigRepository(session)
        loaded: Dict[str, Any] = {}
        for key, meta in self.SETTINGS_SCHEMA.items():
            value = await repo.get_config(None, key)
            if value is None:
                value = meta["default"]
            loaded[key] = value
        return self._normalize_settings(loaded)

    async def get_settings(self) -> Dict[str, Any]:
        async with AsyncSessionLocal() as session:
            return await self._get_settings_with_session(session)

    async def update_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        async with AsyncSessionLocal() as session:
            repo = UserConfigRepository(session)
            current = await self._get_settings_with_session(session)
            merged = {**current, **(updates or {})}
            normalized = self._normalize_settings(merged)

            for key, meta in self.SETTINGS_SCHEMA.items():
                await repo.set_config(
                    user_id=None,
                    key=key,
                    value=self._serialize_setting_value(normalized[key], meta["type"]),
                    config_type=meta["type"],
                    category=self.SETTINGS_CATEGORY,
                )

            await session.commit()
            return normalized

    def _get_setting_with_sync_db(self, db: Session, key: str) -> Any:
        meta = self.SETTINGS_SCHEMA.get(key)
        if not meta:
            raise KeyError(f"Unknown community setting: {key}")

        if db is None:
            return meta["default"]

        record = (
            db.query(UserConfig)
            .filter(
                UserConfig.user_id.is_(None),
                UserConfig.category == self.SETTINGS_CATEGORY,
                UserConfig.config_key == key,
            )
            .order_by(UserConfig.updated_at.desc(), UserConfig.id.desc())
            .first()
        )
        if not record:
            return meta["default"]

        value_type = str(record.config_type or meta["type"]).strip() or meta["type"]
        return self._convert_setting_value(record.config_value, value_type)

    def is_invite_code_required_for_registration(self, db: Session | None = None) -> bool:
        """Return whether first-time registration currently requires an invite code."""
        default_value = bool(self.SETTINGS_SCHEMA["invite_code_required_for_registration"]["default"])
        if db is None:
            return default_value

        try:
            value = self._get_setting_with_sync_db(db, "invite_code_required_for_registration")
            return bool(value)
        except Exception as exc:
            logger.warning("Failed to load invite registration switch from DB: %s", exc)
            return default_value

    def resolve_registration_invite(
        self,
        db: Session,
        raw_code: Optional[str],
        channel: str,
    ) -> Optional[InviteCode]:
        """
        Resolve the invite-code policy for a new registration attempt.

        - When the switch is on: invite code is required.
        - When the switch is off: invite code is optional, but if provided it must be valid.
        """
        code = str(raw_code or "").strip()
        invite_required = self.is_invite_code_required_for_registration(db)

        if not code:
            if invite_required:
                raise ValueError("当前注册方式需要邀请码")
            return None

        return self.validate_invite_code(db, code, channel)

    @classmethod
    def _checkin_window(cls, now_ts: Optional[float] = None) -> tuple[str, float]:
        ts = time.time() if now_ts is None else float(now_ts)
        current = datetime.fromtimestamp(ts, tz=cls.CHECKIN_TIMEZONE)
        reset_point = current.replace(hour=cls.CHECKIN_RESET_HOUR, minute=0, second=0, microsecond=0)

        if current < reset_point:
            checkin_date = (current - timedelta(days=1)).date().isoformat()
            next_reset = reset_point
        else:
            checkin_date = current.date().isoformat()
            next_reset = reset_point + timedelta(days=1)

        return checkin_date, next_reset.timestamp()

    @classmethod
    def _today_key(cls, now_ts: Optional[float] = None) -> str:
        checkin_date, _ = cls._checkin_window(now_ts)
        return checkin_date

    def _build_checkin_payload(self, settings: Dict[str, Any], today: str, *, enabled: Optional[bool] = None) -> Dict[str, Any]:
        _, next_reset_at = self._checkin_window()
        return {
            "enabled": bool(settings["daily_checkin_enabled"]) if enabled is None else bool(enabled),
            "today": today,
            "reward_preview": self._checkin_reward_preview(settings),
            "next_reset_at": next_reset_at,
            "reset_hour": self.CHECKIN_RESET_HOUR,
            "reset_timezone": self.CHECKIN_TIMEZONE_NAME,
            "reset_description": f"每日 {self.CHECKIN_RESET_HOUR:02d}:00 重置签到状态",
        }

    def _checkin_reward_preview(self, settings: Dict[str, Any]) -> str:
        if settings["daily_checkin_reward_mode"] == "random":
            return f"{settings['daily_checkin_reward_min']} ~ {settings['daily_checkin_reward_max']} 积分"
        return f"{settings['daily_checkin_reward_fixed']} 积分"

    def _resolve_checkin_reward(self, settings: Dict[str, Any]) -> int:
        if settings["daily_checkin_reward_mode"] == "random":
            low = int(settings["daily_checkin_reward_min"] or 0)
            high = int(settings["daily_checkin_reward_max"] or 0)
            if high < low:
                low, high = high, low
            if low == high:
                return low
            return random.SystemRandom().randint(low, high)
        return int(settings["daily_checkin_reward_fixed"] or 0)

    async def get_checkin_status(self, user_id: int) -> Dict[str, Any]:
        async with AsyncSessionLocal() as session:
            settings = await self._get_settings_with_session(session)
            today = self._today_key()
            stmt = select(DailyCheckIn).where(
                DailyCheckIn.user_id == user_id,
                DailyCheckIn.checkin_date == today,
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            return {
                **self._build_checkin_payload(settings, today),
                "already_checked_in": record is not None,
                "today_reward": record.reward_points if record else None,
            }

    async def perform_checkin(self, user_id: int) -> Tuple[bool, str, Dict[str, Any]]:
        async with AsyncSessionLocal() as session:
            settings = await self._get_settings_with_session(session)
            today = self._today_key()
            if not settings["daily_checkin_enabled"]:
                return False, "签到功能未开启", {
                    **self._build_checkin_payload(settings, today, enabled=False),
                    "already_checked_in": False,
                    "today_reward": None,
                }

            existing_stmt = select(DailyCheckIn).where(
                DailyCheckIn.user_id == user_id,
                DailyCheckIn.checkin_date == today,
            )
            existing_result = await session.execute(existing_stmt)
            existing = existing_result.scalar_one_or_none()
            if existing:
                return False, "今天已经签到过了", {
                    **self._build_checkin_payload(settings, today, enabled=True),
                    "already_checked_in": True,
                    "today_reward": existing.reward_points,
                }

            user = await session.get(User, user_id)
            if not user:
                return False, "用户不存在", {
                    **self._build_checkin_payload(settings, today, enabled=True),
                    "already_checked_in": False,
                    "today_reward": None,
                }

            reward = self._resolve_checkin_reward(settings)
            new_balance = int(user.credits_balance or 0) + reward
            user.credits_balance = new_balance

            session.add(
                DailyCheckIn(
                    user_id=user_id,
                    checkin_date=today,
                    reward_points=reward,
                )
            )
            session.add(
                CreditTransaction(
                    user_id=user_id,
                    amount=reward,
                    balance_after=new_balance,
                    transaction_type="daily_checkin",
                    description=f"每日签到奖励 ({today})",
                    reference_id=today,
                )
            )

            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False, "今天已经签到过了", {
                    **self._build_checkin_payload(settings, today, enabled=True),
                    "already_checked_in": True,
                    "today_reward": None,
                }

            return True, f"签到成功，获得 {reward} 积分", {
                **self._build_checkin_payload(settings, today, enabled=True),
                "already_checked_in": True,
                "today_reward": reward,
                "new_balance": new_balance,
            }

    def normalize_channel(self, channel: str) -> str:
        normalized = str(channel or "").strip().lower()
        if normalized not in self.INVITE_CHANNELS:
            raise ValueError("不支持的邀请码渠道")
        return normalized

    def channel_label(self, channel: str) -> str:
        normalized = self.normalize_channel(channel)
        return self.INVITE_CHANNEL_LABELS.get(normalized, normalized)

    def validate_invite_code(self, db: Session, raw_code: str, channel: str) -> InviteCode:
        normalized_channel = self.normalize_channel(channel)
        code = str(raw_code or "").strip().upper()
        if not code:
            raise ValueError("请输入邀请码")

        record = db.query(InviteCode).filter(func.upper(InviteCode.code) == code).first()
        if not record:
            raise ValueError("邀请码不存在")
        if not record.is_active:
            raise ValueError("邀请码已停用")
        if record.expires_at and record.expires_at < time.time():
            raise ValueError("邀请码已过期")
        if record.used_count >= max(1, int(record.max_uses or 1)):
            raise ValueError("邀请码可用次数已耗尽")
        record_channel = (record.channel or "").strip().lower()
        if record_channel != self.INVITE_CHANNEL_UNIVERSAL and record_channel != normalized_channel:
            raise ValueError(f"该邀请码仅限 {self.channel_label(record.channel)} 渠道使用")
        return record

    def apply_invite_code_to_user(
        self,
        db: Session,
        user: User,
        invite_code: InviteCode,
        channel: str,
    ) -> InviteCodeUsage:
        normalized_channel = self.normalize_channel(channel)

        existing_usage = db.query(InviteCodeUsage).filter(InviteCodeUsage.user_id == user.id).first()
        if existing_usage:
            raise ValueError("当前账号已使用过邀请码")

        if not invite_code.is_valid_for(normalized_channel):
            raise ValueError("邀请码已失效，请更换后重试")

        now_ts = time.time()
        credits_granted = max(0, int(invite_code.credits_amount or 0))
        invite_code.used_count = int(invite_code.used_count or 0) + 1

        user.registration_channel = normalized_channel
        user.invite_code_id = invite_code.id

        if credits_granted > 0:
            new_balance = int(user.credits_balance or 0) + credits_granted
            user.credits_balance = new_balance
            db.add(
                CreditTransaction(
                    user_id=user.id,
                    amount=credits_granted,
                    balance_after=new_balance,
                    transaction_type="invite_reward",
                    description=f"邀请码注册赠送积分 ({invite_code.code})",
                    reference_id=invite_code.code,
                )
            )

        usage = InviteCodeUsage(
            invite_code_id=invite_code.id,
            user_id=user.id,
            channel=normalized_channel,
            credits_granted=credits_granted,
            created_at=now_ts,
        )
        db.add(usage)
        return usage

    def _generate_invite_code(self, channel: str) -> str:
        prefix = {
            "github": "GH",
            "linuxdo": "LD",
            "authentik": "AK",
            "mail": "ML",
            self.INVITE_CHANNEL_UNIVERSAL: "UN",
        }.get(channel, "IV")
        token = secrets.token_urlsafe(6).replace("-", "").replace("_", "").upper()
        return f"{prefix}{token[:10]}"

    async def create_invite_codes(
        self,
        *,
        count: int,
        channel: str,
        credits_amount: int,
        max_uses: int,
        created_by: int,
        expires_at: Optional[float] = None,
        description: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        normalized_channel = self.normalize_channel(channel)
        count = max(1, min(int(count or 1), 100))
        credits_amount = max(0, int(credits_amount or 0))
        max_uses = max(1, int(max_uses or 1))

        created_codes: list[InviteCode] = []
        async with AsyncSessionLocal() as session:
            existing_codes: set[str] = set()
            while len(created_codes) < count:
                code = self._generate_invite_code(normalized_channel)
                if code in existing_codes:
                    continue
                stmt = select(InviteCode.id).where(InviteCode.code == code)
                result = await session.execute(stmt)
                if result.scalar_one_or_none() is not None:
                    continue
                existing_codes.add(code)
                invite = InviteCode(
                    code=code,
                    channel=normalized_channel,
                    credits_amount=credits_amount,
                    max_uses=max_uses,
                    used_count=0,
                    is_active=True,
                    expires_at=expires_at,
                    created_by=created_by,
                    description=(description or "").strip() or None,
                )
                session.add(invite)
                created_codes.append(invite)

            await session.commit()
            for item in created_codes:
                await session.refresh(item)
            return [item.to_dict() for item in created_codes]

    async def list_invite_codes(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        channel: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[list[Dict[str, Any]], int]:
        async with AsyncSessionLocal() as session:
            stmt = select(InviteCode)
            count_stmt = select(func.count(InviteCode.id))

            if search:
                pattern = f"%{search.strip()}%"
                filters = or_(
                    InviteCode.code.ilike(pattern),
                    InviteCode.description.ilike(pattern),
                )
                stmt = stmt.where(filters)
                count_stmt = count_stmt.where(filters)

            if channel:
                normalized_channel = self.normalize_channel(channel)
                stmt = stmt.where(InviteCode.channel == normalized_channel)
                count_stmt = count_stmt.where(InviteCode.channel == normalized_channel)

            if is_active is not None:
                stmt = stmt.where(InviteCode.is_active == is_active)
                count_stmt = count_stmt.where(InviteCode.is_active == is_active)

            stmt = stmt.order_by(InviteCode.created_at.desc(), InviteCode.id.desc())
            stmt = stmt.offset(max(page - 1, 0) * page_size).limit(page_size)

            result = await session.execute(stmt)
            count_result = await session.execute(count_stmt)
            records = result.scalars().all()
            total = count_result.scalar() or 0
            return [item.to_dict() for item in records], total

    async def update_invite_code(self, invite_code_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
        async with AsyncSessionLocal() as session:
            invite = await session.get(InviteCode, invite_code_id)
            if not invite:
                raise ValueError("邀请码不存在")

            if "channel" in updates and updates["channel"] is not None:
                invite.channel = self.normalize_channel(updates["channel"])
            if "credits_amount" in updates and updates["credits_amount"] is not None:
                invite.credits_amount = max(0, int(updates["credits_amount"] or 0))
            if "max_uses" in updates and updates["max_uses"] is not None:
                invite.max_uses = max(1, int(updates["max_uses"] or 1))
                if invite.used_count > invite.max_uses:
                    invite.used_count = invite.max_uses
            if "is_active" in updates and updates["is_active"] is not None:
                invite.is_active = bool(updates["is_active"])
            if "description" in updates:
                invite.description = (str(updates["description"] or "").strip() or None)
            if "expires_at" in updates:
                invite.expires_at = updates["expires_at"]

            await session.commit()
            await session.refresh(invite)
            return invite.to_dict()

    async def delete_invite_code(self, invite_code_id: int) -> bool:
        async with AsyncSessionLocal() as session:
            invite = await session.get(InviteCode, invite_code_id)
            if not invite:
                return False
            if int(invite.used_count or 0) > 0:
                raise ValueError("邀请码已被使用，不能删除")
            await session.delete(invite)
            await session.commit()
            return True

    async def list_sponsors(self, include_inactive: bool = True) -> list[Dict[str, Any]]:
        async with AsyncSessionLocal() as session:
            stmt = select(SponsorProfile)
            if not include_inactive:
                stmt = stmt.where(SponsorProfile.is_active == True)  # noqa: E712
            stmt = stmt.order_by(SponsorProfile.sort_order.asc(), SponsorProfile.created_at.desc())
            result = await session.execute(stmt)
            return [item.to_dict() for item in result.scalars().all()]

    async def create_sponsor(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with AsyncSessionLocal() as session:
            sponsor = SponsorProfile(
                nickname=str(payload.get("nickname") or "").strip(),
                avatar_url=(str(payload.get("avatar_url") or "").strip() or None),
                bio=(str(payload.get("bio") or "").strip() or None),
                link_url=(str(payload.get("link_url") or "").strip() or None),
                amount=(str(payload.get("amount") or "").strip() or None),
                note=(str(payload.get("note") or "").strip() or None),
                sort_order=int(payload.get("sort_order") or 0),
                is_active=bool(payload.get("is_active", True)),
            )
            if not sponsor.nickname:
                raise ValueError("赞助人昵称不能为空")
            session.add(sponsor)
            await session.commit()
            await session.refresh(sponsor)
            return sponsor.to_dict()

    async def update_sponsor(self, sponsor_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with AsyncSessionLocal() as session:
            sponsor = await session.get(SponsorProfile, sponsor_id)
            if not sponsor:
                raise ValueError("赞助人不存在")

            if "nickname" in payload:
                sponsor.nickname = str(payload.get("nickname") or "").strip()
            if "avatar_url" in payload:
                sponsor.avatar_url = (str(payload.get("avatar_url") or "").strip() or None)
            if "bio" in payload:
                sponsor.bio = (str(payload.get("bio") or "").strip() or None)
            if "link_url" in payload:
                sponsor.link_url = (str(payload.get("link_url") or "").strip() or None)
            if "amount" in payload:
                sponsor.amount = (str(payload.get("amount") or "").strip() or None)
            if "note" in payload:
                sponsor.note = (str(payload.get("note") or "").strip() or None)
            if "sort_order" in payload and payload.get("sort_order") is not None:
                sponsor.sort_order = int(payload.get("sort_order") or 0)
            if "is_active" in payload and payload.get("is_active") is not None:
                sponsor.is_active = bool(payload.get("is_active"))

            if not sponsor.nickname:
                raise ValueError("赞助人昵称不能为空")

            await session.commit()
            await session.refresh(sponsor)
            return sponsor.to_dict()

    async def delete_sponsor(self, sponsor_id: int) -> bool:
        async with AsyncSessionLocal() as session:
            sponsor = await session.get(SponsorProfile, sponsor_id)
            if not sponsor:
                return False
            await session.delete(sponsor)
            await session.commit()
            return True

    async def get_public_sponsors(self) -> list[Dict[str, Any]]:
        return await self.list_sponsors(include_inactive=False)


community_service = CommunityService()
