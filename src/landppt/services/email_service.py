"""
Email service for LandPPT - handles sending verification codes
"""

import smtplib
import random
import string
import time
import logging
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Tuple

from ..core.config import app_config

logger = logging.getLogger(__name__)


def generate_verification_code(length: int = 6) -> str:
    """Generate a random numeric verification code"""
    return ''.join(random.choices(string.digits, k=length))


async def send_email(to_email: str, subject: str, html_content: str) -> Tuple[bool, str]:
    """
    Send email via configured provider.
    Returns (success, message) tuple.
    """
    provider = (app_config.email_provider or "smtp").strip().lower()

    if provider == "resend":
        if not app_config.resend_api_key:
            logger.warning("Resend not configured, skipping email send")
            return False, "邮件服务未配置"
        if not app_config.resend_from_email:
            return False, "请配置 RESEND_FROM_EMAIL"

        try:
            try:
                import resend
            except ModuleNotFoundError:
                return False, "Resend 依赖未安装"

            def _send():
                resend.api_key = app_config.resend_api_key
                from_name = (app_config.resend_from_name or "LandPPT").strip()
                from_value = (
                    f"{from_name} <{app_config.resend_from_email}>"
                    if from_name
                    else app_config.resend_from_email
                )
                params: resend.Emails.SendParams = {
                    "from": from_value,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_content,
                }
                return resend.Emails.send(params)

            await asyncio.to_thread(_send)
            logger.info(f"Email sent successfully to {to_email} via Resend")
            return True, "发送成功"

        except Exception as e:
            logger.error(f"Resend error: {e}")
            return False, f"邮件发送失败: {str(e)}"

    # Default to SMTP
    if not app_config.smtp_host or not app_config.smtp_user:
        logger.warning("SMTP not configured, skipping email send")
        return False, "邮件服务未配置"
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{app_config.smtp_from_name} <{app_config.smtp_from_email or app_config.smtp_user}>"
        msg['To'] = to_email
        
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        
        if app_config.smtp_use_ssl:
            server = smtplib.SMTP_SSL(app_config.smtp_host, app_config.smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(app_config.smtp_host, app_config.smtp_port, timeout=30)
            server.starttls()
        
        server.login(app_config.smtp_user, app_config.smtp_password)
        server.sendmail(
            app_config.smtp_from_email or app_config.smtp_user,
            [to_email],
            msg.as_string()
        )
        server.quit()
        
        logger.info(f"Email sent successfully to {to_email}")
        return True, "发送成功"
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication error: {e}")
        return False, "邮件服务认证失败"
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        return False, f"邮件发送失败: {str(e)}"
    except Exception as e:
        logger.error(f"Email error: {e}")
        return False, f"邮件发送失败: {str(e)}"


async def create_verification_code(
    email: str,
    code_type: str  # 'register' or 'reset'
) -> Tuple[bool, str, Optional[str]]:
    """
    Create and store a verification code for email.
    Returns (success, message, code) tuple.
    """
    from sqlalchemy import select, delete
    from ..database.database import AsyncSessionLocal
    from ..database.models import VerificationCode
    
    code = generate_verification_code()
    expires_at = time.time() + (app_config.verification_code_expire_minutes * 60)
    
    try:
        async with AsyncSessionLocal() as session:
            # Delete old codes for this email and type
            await session.execute(
                delete(VerificationCode).where(
                    VerificationCode.email == email,
                    VerificationCode.code_type == code_type
                )
            )
            
            # Create new code
            verification = VerificationCode(
                email=email,
                code=code,
                code_type=code_type,
                expires_at=expires_at
            )
            session.add(verification)
            await session.commit()
            
            return True, "验证码已创建", code
            
    except Exception as e:
        logger.error(f"Error creating verification code: {e}")
        return False, f"创建验证码失败: {str(e)}", None


async def verify_code(
    email: str,
    code: str,
    code_type: str
) -> Tuple[bool, str]:
    """
    Verify a verification code.
    Returns (success, message) tuple.
    """
    from sqlalchemy import select
    from ..database.database import AsyncSessionLocal
    from ..database.models import VerificationCode
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(VerificationCode).where(
                    VerificationCode.email == email,
                    VerificationCode.code == code,
                    VerificationCode.code_type == code_type
                )
            )
            verification = result.scalar_one_or_none()
            
            if not verification:
                return False, "验证码无效"
            
            if verification.is_used:
                return False, "验证码已使用"
            
            if time.time() > verification.expires_at:
                return False, "验证码已过期"
            
            # Mark as used
            verification.is_used = True
            await session.commit()
            
            return True, "验证成功"
            
    except Exception as e:
        logger.error(f"Error verifying code: {e}")
        return False, f"验证失败: {str(e)}"


async def send_verification_email(
    email: str,
    code_type: str  # 'register' or 'reset'
) -> Tuple[bool, str]:
    """
    Generate and send verification code to email.
    Returns (success, message) tuple.
    """
    # Create code
    success, message, code = await create_verification_code(email, code_type)
    if not success:
        return False, message
    
    # Prepare email content
    if code_type == 'register':
        subject = "LandPPT 注册验证码"
        action = "注册账户"
    else:
        subject = "LandPPT 密码重置验证码"
        action = "重置密码"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Inter', Arial, sans-serif; background: #f5f5f5; padding: 20px; }}
            .container {{ max-width: 500px; margin: 0 auto; background: #fff; border-radius: 16px; padding: 40px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }}
            .logo {{ font-size: 28px; font-weight: 700; color: #111; margin-bottom: 20px; }}
            .code {{ font-size: 36px; font-weight: 700; letter-spacing: 8px; color: #111; background: #f0f0f0; padding: 20px; border-radius: 8px; text-align: center; margin: 20px 0; }}
            .info {{ color: #666; font-size: 14px; margin-top: 20px; }}
            .footer {{ color: #999; font-size: 12px; margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">LandPPT</div>
            <p>您好，</p>
            <p>您正在{action}，请使用以下验证码完成验证：</p>
            <div class="code">{code}</div>
            <p class="info">验证码有效期为 {app_config.verification_code_expire_minutes} 分钟。如果您没有进行此操作，请忽略此邮件。</p>
            <div class="footer">
                © LandPPT - AI PPT 生成平台
            </div>
        </div>
    </body>
    </html>
    """
    
    # Send email
    return await send_email(email, subject, html_content)
