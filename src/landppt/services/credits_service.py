"""
Credits service for managing user credits consumption and recharge
"""

import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.repositories import UserRepository, CreditTransactionRepository, RedemptionCodeRepository
from ..database.models import User, CreditTransaction

logger = logging.getLogger(__name__)


class CreditsService:
    """Service for managing user credits"""
    
    # Credit costs for different operations (user-confirmed pricing)
    COSTS = {
        "outline_generation": 3,      # 大纲生成（按LLM调用次数）3积分/次
        "slide_generation": 5,        # 幻灯片每页 5积分
        "template_generation": 10,    # 模板生成 10积分
        "ai_edit": 3,                 # AI编辑每次 3积分
        "ai_other": 1,                # 其他AI操作每次 1积分
    }
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_repo = UserRepository(session)
        self.transaction_repo = CreditTransactionRepository(session)
        self.redemption_repo = RedemptionCodeRepository(session)
    
    async def get_balance(self, user_id: int) -> int:
        """Get user's current credit balance"""
        user = await self.user_repo.get_by_id(user_id)
        return user.credits_balance if user else 0
    
    async def check_balance(self, user_id: int, required: int) -> bool:
        """Check if user has enough credits"""
        balance = await self.get_balance(user_id)
        return balance >= required
    
    async def consume_credits(
        self, 
        user_id: int, 
        operation_type: str,
        quantity: int = 1,
        description: Optional[str] = None,
        reference_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Consume credits for an operation.
        
        Args:
            user_id: User ID
            operation_type: Type of operation (from COSTS)
            quantity: Number of items (e.g., number of slides)
            description: Optional description
            reference_id: Optional reference (project_id, etc.)
        
        Returns:
            Tuple of (success, message)
        """
        # Get cost per item
        cost_per_item = self.COSTS.get(operation_type, self.COSTS.get("ai_other", 1))
        total_cost = cost_per_item * quantity
        
        # Check balance
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return False, "用户不存在"
        
        if user.credits_balance < total_cost:
            return False, f"积分不足。需要 {total_cost} 积分，当前余额 {user.credits_balance} 积分"
        
        # Deduct credits
        new_balance = user.credits_balance - total_cost
        await self.user_repo.update_credits_balance(user_id, new_balance)
        
        # Record transaction
        if not description:
            description = self._get_default_description(operation_type, quantity)
        
        await self.transaction_repo.create({
            "user_id": user_id,
            "amount": -total_cost,
            "balance_after": new_balance,
            "transaction_type": "consume",
            "description": description,
            "reference_id": reference_id
        })
        
        logger.info(f"User {user_id} consumed {total_cost} credits for {operation_type}. New balance: {new_balance}")
        return True, f"消费成功。扣除 {total_cost} 积分，余额 {new_balance} 积分"
    
    async def add_credits(
        self,
        user_id: int,
        amount: int,
        transaction_type: str,
        description: str,
        reference_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Add credits to user account.
        
        Args:
            user_id: User ID
            amount: Amount to add (positive)
            transaction_type: Type (recharge, redemption, admin_adjust, refund)
            description: Description
            reference_id: Optional reference
        
        Returns:
            Tuple of (success, message)
        """
        if amount <= 0:
            return False, "充值金额必须为正数"
        
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return False, "用户不存在"
        
        new_balance = user.credits_balance + amount
        await self.user_repo.update_credits_balance(user_id, new_balance)
        
        # Record transaction
        await self.transaction_repo.create({
            "user_id": user_id,
            "amount": amount,
            "balance_after": new_balance,
            "transaction_type": transaction_type,
            "description": description,
            "reference_id": reference_id
        })
        
        logger.info(f"User {user_id} received {amount} credits ({transaction_type}). New balance: {new_balance}")
        return True, f"充值成功。增加 {amount} 积分，余额 {new_balance} 积分"
    
    async def redeem_code(self, user_id: int, code: str) -> Tuple[bool, str]:
        """
        Redeem a code for credits.
        
        Args:
            user_id: User ID
            code: Redemption code
        
        Returns:
            Tuple of (success, message)
        """
        # Check if code exists and is valid
        redemption_code = await self.redemption_repo.get_by_code(code)
        if not redemption_code:
            return False, "兑换码不存在"
        
        if not redemption_code.is_valid():
            if redemption_code.is_used:
                return False, "该兑换码已被使用"
            else:
                return False, "该兑换码已过期"
        
        # Use the code
        await self.redemption_repo.use_code(code, user_id)
        
        # Add credits
        success, message = await self.add_credits(
            user_id=user_id,
            amount=redemption_code.credits_amount,
            transaction_type="redemption",
            description=f"兑换码充值: {code}",
            reference_id=code
        )
        
        if success:
            return True, f"兑换成功！获得 {redemption_code.credits_amount} 积分"
        return False, message
    
    async def get_transaction_history(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        transaction_type: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user's transaction history"""
        transactions, total = await self.transaction_repo.get_user_transactions(
            user_id, page, page_size, transaction_type
        )
        return [t.to_dict() for t in transactions], total
    
    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """Get user's credit statistics"""
        balance = await self.get_balance(user_id)
        stats = await self.transaction_repo.get_user_stats(user_id)
        return {
            "balance": balance,
            **stats
        }
    
    def _get_default_description(self, operation_type: str, quantity: int) -> str:
        """Generate default description for operation"""
        descriptions = {
            "outline_generation": "大纲生成",
            "slide_generation": f"幻灯片生成 ({quantity}页)",
            "template_generation": "模板生成",
            "ai_edit": "AI编辑",
            "ai_other": "AI操作"
        }
        return descriptions.get(operation_type, f"操作: {operation_type}")
    
    def get_operation_cost(self, operation_type: str, quantity: int = 1) -> int:
        """Get the cost for an operation without consuming"""
        cost_per_item = self.COSTS.get(operation_type, self.COSTS.get("ai_other", 1))
        return cost_per_item * quantity


# Convenience function to get credits service
def get_credits_service(session: AsyncSession) -> CreditsService:
    """Get credits service instance"""
    return CreditsService(session)
