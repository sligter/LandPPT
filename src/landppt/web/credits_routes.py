"""
User credits routes for viewing balance, redeeming codes, and transaction history
"""

import logging
from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ..database.database import AsyncSessionLocal
from ..database.models import User
from ..auth.middleware import get_current_user_required
from ..services.credits_service import CreditsService
from ..services.community_service import community_service
from ..core.config import app_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/credits", tags=["credits"])
templates = Jinja2Templates(directory="src/landppt/web/templates")


class RedeemCodeRequest(BaseModel):
    code: str


# User credits page
@router.get("", response_class=HTMLResponse)
async def user_credits_page(
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """User credits dashboard page"""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=404, detail="积分系统未启用")
    
    return templates.TemplateResponse(
        "pages/account/user_credits.html",
        {
            "request": request,
            "user": user
        }
    )


# API endpoints
@router.get("/api/balance")
async def get_balance(
    user: User = Depends(get_current_user_required)
):
    """Get current user's credit balance"""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=400, detail="积分系统未启用")
    
    async with AsyncSessionLocal() as session:
        credits_service = CreditsService(session)
        stats = await credits_service.get_user_stats(user.id)
        
        return {
            "balance": stats["balance"],
            "total_consumed": stats["total_consumed"],
            "total_recharged": stats["total_recharged"],
            "transaction_count": stats["transaction_count"]
        }


@router.get("/api/transactions")
async def get_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    transaction_type: Optional[str] = None,
    user: User = Depends(get_current_user_required)
):
    """Get current user's transaction history"""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=400, detail="积分系统未启用")
    
    async with AsyncSessionLocal() as session:
        credits_service = CreditsService(session)
        transactions, total = await credits_service.get_transaction_history(
            user_id=user.id,
            page=page,
            page_size=page_size,
            transaction_type=transaction_type
        )
        
        return {
            "transactions": transactions,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }


@router.post("/api/redeem")
async def redeem_code(
    data: RedeemCodeRequest,
    user: User = Depends(get_current_user_required)
):
    """Redeem a code for credits"""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=400, detail="积分系统未启用")
    
    if not data.code or not data.code.strip():
        raise HTTPException(status_code=400, detail="请输入兑换码")
    
    async with AsyncSessionLocal() as session:
        credits_service = CreditsService(session)
        success, message = await credits_service.redeem_code(user.id, data.code.strip())
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        # Get updated balance
        new_balance = await credits_service.get_balance(user.id)
        
        return {
            "success": True,
            "message": message,
            "new_balance": new_balance
        }


@router.get("/api/pricing")
async def get_pricing(
    user: User = Depends(get_current_user_required)
):
    """Get credits pricing for different operations"""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=400, detail="积分系统未启用")
    
    return {
        "enabled": True,
        "pricing": {
            "outline_generation": {
                "cost": 3,
                "description": "大纲生成（每次LLM调用）"
            },
            "slide_generation": {
                "cost": 5,
                "description": "幻灯片生成（每页）"
            },
            "template_generation": {
                "cost": 10,
                "description": "模板生成"
            },
            "ai_edit": {
                "cost": 3,
                "description": "AI编辑（每次）"
            },
            "ai_other": {
                "cost": 1,
                "description": "其他AI操作"
            }
        }
    }


@router.get("/api/checkin-status")
async def get_checkin_status(
    user: User = Depends(get_current_user_required)
):
    """Get current user's daily check-in status."""
    if not app_config.enable_credits_system:
        return {
            "enabled": False,
            "already_checked_in": False,
            "today": community_service._today_key(),
            "reward_preview": None,
            "today_reward": None,
            "next_reset_at": community_service._checkin_window()[1],
            "reset_hour": community_service.CHECKIN_RESET_HOUR,
            "reset_timezone": community_service.CHECKIN_TIMEZONE_NAME,
            "reset_description": f"每日 {community_service.CHECKIN_RESET_HOUR:02d}:00 重置签到状态",
        }

    return await community_service.get_checkin_status(user.id)


@router.post("/api/checkin")
async def check_in(
    user: User = Depends(get_current_user_required)
):
    """Daily user check-in."""
    if not app_config.enable_credits_system:
        raise HTTPException(status_code=400, detail="积分系统未启用")

    success, message, payload = await community_service.perform_checkin(user.id)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {
        "success": True,
        "message": message,
        **payload,
    }


@router.get("/api/check")
async def check_credits(
    operation: str,
    quantity: int = 1,
    user: User = Depends(get_current_user_required)
):
    """Check if user has enough credits for an operation"""
    if not app_config.enable_credits_system:
        # If credits system is disabled, always allow
        return {"allowed": True, "required": 0, "balance": 0}
    
    async with AsyncSessionLocal() as session:
        credits_service = CreditsService(session)
        required = credits_service.get_operation_cost(operation, quantity)
        balance = await credits_service.get_balance(user.id)
        
        return {
            "allowed": balance >= required,
            "required": required,
            "balance": balance
        }
