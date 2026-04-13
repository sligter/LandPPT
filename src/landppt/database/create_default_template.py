"""
Create default global master template
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any
from .database import AsyncSessionLocal
from .service import DatabaseService

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ page_title }}</title>
    <!-- 默认模板保持自包含，避免预置国内访问不稳定的外部 CDN。 -->
    <style>
        body {
            width: 1280px;
            height: 720px;
            margin: 0;
            padding: 0;
            position: relative;
            overflow: hidden;
            background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
            font-family: 'Microsoft YaHei', 'PingFang SC', 'Helvetica Neue', Arial, sans-serif;
        }
        
        .slide-container {
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            color: white;
            position: relative;
        }
        
        .slide-header {
            padding: 40px 60px 20px 60px;
            border-bottom: 2px solid rgba(96, 165, 250, 0.3);
        }
        
        .slide-title {
            font-size: clamp(2rem, 4vw, 3.5rem);
            font-weight: bold;
            color: #60a5fa;
            margin: 0;
            line-height: 1.2;
            max-height: 80px;
            overflow: hidden;
        }
        
        .slide-content {
            flex: 1;
            padding: 30px 60px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            max-height: 580px;
            overflow: hidden;
        }
        
        .content-main {
            font-size: clamp(1rem, 2.5vw, 1.4rem);
            line-height: 1.5;
            color: #e2e8f0;
        }
        
        .content-points {
            list-style: none;
            padding: 0;
            margin: 0;
        }
        
        .content-points li {
            margin-bottom: 15px;
            padding-left: 30px;
            position: relative;
        }
        
        .content-points li:before {
            content: "▶";
            position: absolute;
            left: 0;
            color: #60a5fa;
            font-size: 0.8em;
        }
        
        .slide-footer {
            position: absolute;
            bottom: 20px;
            right: 30px;
            font-size: 14px;
            color: #94a3b8;
            font-weight: 600;
        }
        
        .chart-container {
            max-height: 300px;
            margin: 20px 0;
        }
        
        .highlight-box {
            background: rgba(96, 165, 250, 0.1);
            border-left: 4px solid #60a5fa;
            padding: 20px;
            margin: 20px 0;
            border-radius: 0 8px 8px 0;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        
        .stat-card {
            background: rgba(255, 255, 255, 0.1);
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            border: 1px solid rgba(96, 165, 250, 0.3);
        }
        
        .stat-number {
            font-size: 2.5rem;
            font-weight: bold;
            color: #60a5fa;
            display: block;
        }
        
        .stat-label {
            font-size: 1rem;
            color: #cbd5e1;
            margin-top: 5px;
        }
        
        /* 响应式调整 */
        @media (max-width: 1280px) {
            body {
                width: 100vw;
                height: 56.25vw;
                max-height: 100vh;
            }
        }
    </style>
</head>
<body>
    <div class="slide-container">
        <div class="slide-header">
            <h1 class="slide-title">{{ main_heading }}</h1>
        </div>
        
        <div class="slide-content">
            <div class="content-main">
                {{ page_content }}
            </div>
        </div>
        
        <div class="slide-footer">
            {{ current_page_number }} / {{ total_page_count }}
        </div>
    </div>
</body>
</html>"""

def get_template_examples_path() -> Path:
    """Get the path to template_examples directory"""
    # 从当前文件位置向上查找项目根目录
    current_file = Path(__file__)
    # 从 src/landppt/database/create_default_template.py 向上四级到项目根目录
    project_root = current_file.parent.parent.parent.parent
    template_examples_path = project_root / "template_examples"

    logger.info(f"Looking for template_examples at: {template_examples_path}")

    if not template_examples_path.exists():
        logger.warning(f"Template examples directory not found at: {template_examples_path}")
        return None

    return template_examples_path


def load_template_from_json(json_file_path: Path) -> Dict[str, Any]:
    """Load template data from JSON file"""
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            template_data = json.load(f)

        # 移除导出信息，因为这是新导入的模板
        if 'export_info' in template_data:
            del template_data['export_info']

        # 确保必要字段存在
        if 'template_name' not in template_data or 'html_template' not in template_data:
            logger.error(f"Invalid template JSON file: {json_file_path}")
            return None

        # 设置默认值
        template_data.setdefault('description', '')
        template_data.setdefault('tags', [])
        template_data.setdefault('is_default', False)
        template_data.setdefault('is_active', True)
        template_data.setdefault('created_by', 'system')

        return template_data

    except Exception as e:
        logger.error(f"Error loading template from {json_file_path}: {e}")
        return None


async def import_templates_from_examples() -> List[int]:
    """Import all templates from template_examples directory"""
    template_examples_path = get_template_examples_path()
    if not template_examples_path:
        logger.warning("Template examples directory not found, skipping import")
        return []

    imported_template_ids = []

    try:
        async with AsyncSessionLocal() as session:
            db_service = DatabaseService(session)

            # 获取所有JSON文件
            json_files = list(template_examples_path.glob("*.json"))
            logger.info(f"Found {len(json_files)} template files in {template_examples_path}")

            for json_file in json_files:
                logger.info(f"Processing template file: {json_file.name}")

                # 加载模板数据
                template_data = load_template_from_json(json_file)
                if not template_data:
                    continue

                # 检查模板是否已存在
                existing = await db_service.get_global_master_template_by_name(template_data['template_name'])
                if existing:
                    logger.info(f"Template '{template_data['template_name']}' already exists, skipping")
                    continue

                # 创建模板
                try:
                    template = await db_service.create_global_master_template(template_data)
                    imported_template_ids.append(template.id)
                    logger.info(f"Successfully imported template '{template_data['template_name']}' with ID: {template.id}")
                except Exception as e:
                    logger.error(f"Failed to create template '{template_data['template_name']}': {e}")
                    continue

            logger.info(f"Successfully imported {len(imported_template_ids)} templates from examples")
            return imported_template_ids

    except Exception as e:
        logger.error(f"Error importing templates from examples: {e}")
        return imported_template_ids


async def create_default_global_template():
    """Create default global master template (fallback if no examples found)"""
    try:
        async with AsyncSessionLocal() as session:
            db_service = DatabaseService(session)

            # Check if default template already exists
            existing = await db_service.get_global_master_template_by_name("默认商务模板")
            if existing:
                logger.info("Default global master template already exists")
                return existing.id

            # Create default template
            template_data = {
                "template_name": "默认商务模板",
                "description": "现代简约的商务PPT模板，适用于各种商务演示场景。采用深色背景和蓝色主色调，支持多种内容类型展示。",
                "html_template": DEFAULT_TEMPLATE_HTML,
                "tags": ["默认", "商务", "现代", "简约", "深色"],
                "is_default": True,
                "is_active": True,
                "created_by": "system"
            }

            template = await db_service.create_global_master_template(template_data)
            logger.info(f"Created default global master template with ID: {template.id}")
            return template.id

    except Exception as e:
        logger.error(f"Error creating default global master template: {e}")
        raise

async def ensure_default_templates_exist(force_import: bool = False):
    """Ensure default templates exist, import from examples or create fallback

    Args:
        force_import: If True, always try to import templates regardless of existing templates
    """
    try:
        # 检查是否已有模板（除非强制导入）
        if not force_import:
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)
                existing_templates = await db_service.get_all_global_master_templates(active_only=False)

                if existing_templates:
                    logger.info(f"Found {len(existing_templates)} existing templates, skipping import")
                    return [template.id for template in existing_templates]

        # 首先尝试从template_examples导入模板
        imported_ids = await import_templates_from_examples()

        if imported_ids:
            logger.info(f"Successfully imported {len(imported_ids)} templates from examples")

            # 检查是否有默认模板，如果没有则设置第一个导入的模板为默认
            async with AsyncSessionLocal() as session:
                db_service = DatabaseService(session)
                default_template = await db_service.get_default_global_master_template()

                if not default_template and imported_ids:
                    # 设置第一个导入的模板为默认模板
                    await db_service.update_global_master_template(imported_ids[0], {"is_default": True})
                    logger.info(f"Set template ID {imported_ids[0]} as default template")

            return imported_ids
        else:
            # 如果没有成功导入任何模板，则创建默认模板
            logger.info("No templates imported from examples, creating fallback default template")
            template_id = await create_default_global_template()
            logger.info(f"Fallback default template created with ID: {template_id}")
            return [template_id] if template_id else []

    except Exception as e:
        logger.error(f"Failed to ensure default templates exist: {e}")
        return []


async def ensure_default_templates_exist_first_time():
    """Ensure default templates exist on first time database creation"""
    return await ensure_default_templates_exist(force_import=True)


async def ensure_default_template_exists():
    """Ensure default template exists, create if not (legacy function for compatibility)"""
    try:
        template_ids = await ensure_default_templates_exist()
        if template_ids:
            return template_ids[0]  # 返回第一个模板ID以保持兼容性
        return None
    except Exception as e:
        logger.error(f"Failed to ensure default template exists: {e}")
        return None

if __name__ == "__main__":
    # Run the script to import templates from examples and create default templates
    asyncio.run(ensure_default_templates_exist())
