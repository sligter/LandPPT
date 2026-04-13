"""
Enhanced Report Generator for Comprehensive Research Reports

This module provides flexible, detailed report generation without rigid module divisions,
focusing on comprehensive content analysis and professional presentation.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from .enhanced_research_service import EnhancedResearchReport, EnhancedResearchStep

logger = logging.getLogger(__name__)


class EnhancedReportGenerator:
    """Generate comprehensive, flexible research reports"""
    
    def __init__(self, reports_dir: str = "research_reports"):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(exist_ok=True)
        logger.info(f"Enhanced research reports directory: {self.reports_dir.absolute()}")
    
    def generate_markdown_report(self, report: EnhancedResearchReport) -> str:
        """Generate comprehensive Markdown formatted research report"""
        
        # Build comprehensive report content
        markdown_content = self._build_enhanced_markdown_content(report)
        return markdown_content
    
    def save_report_to_file(self, report: EnhancedResearchReport, 
                          custom_filename: Optional[str] = None) -> str:
        """Save enhanced research report to file"""
        
        try:
            # Generate filename
            if custom_filename:
                filename = custom_filename
                if not filename.endswith('.md'):
                    filename += '.md'
            else:
                safe_topic = self._sanitize_filename(report.topic)
                timestamp = report.created_at.strftime("%Y%m%d_%H%M%S")
                filename = f"enhanced_research_{safe_topic}_{timestamp}.md"
            
            # Generate full path
            file_path = self.reports_dir / filename
            
            # Generate markdown content
            markdown_content = self._build_enhanced_markdown_content(report)
            
            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            
            logger.info(f"Enhanced research report saved to: {file_path.absolute()}")
            return str(file_path.absolute())
            
        except Exception as e:
            logger.error(f"Failed to save enhanced research report: {e}")
            raise
    
    def _build_enhanced_markdown_content(self, report: EnhancedResearchReport) -> str:
        """Build simplified markdown content focusing on topic-related findings only"""
        
        content = []
        
        # Header with minimal metadata
        content.append(f"# 深度研究报告：{report.topic}")
        content.append("")
        content.append("---")
        content.append("")
        
        # Minimal report info
        content.append(f"**研究主题**: {report.topic}")
        content.append(f"**生成时间**: {report.created_at.strftime('%Y年%m月%d日 %H:%M:%S')}")
        content.append("")
        
        # Executive Summary
        content.append("## 📋 执行摘要")
        content.append("")
        content.append(report.executive_summary)
        content.append("")
        
        # Comprehensive Analysis (if available)
        if report.content_analysis and report.content_analysis.get('comprehensive_analysis'):
            content.append("## 🔬 综合分析")
            content.append("")
            content.append(report.content_analysis['comprehensive_analysis'])
            content.append("")
        
        # Key Findings - 只保留主题相关的发现
        if report.key_findings:
            content.append("## 🔍 关键发现")
            content.append("")
            for i, finding in enumerate(report.key_findings, 1):
                content.append(f"{i}. {finding}")
                content.append("")
        
        # Research Analysis - 只保留分析结论，移除搜索步骤细节
        analysis_content = []
        for step in report.steps:
            if step.analysis and step.analysis.strip():
                # 只添加非空的分析内容
                analysis_content.append(step.analysis)
        
        if analysis_content:
            content.append("## 📚 研究分析")
            content.append("")
            for analysis in analysis_content:
                content.append(analysis)
                content.append("")
        
        # Recommendations
        if report.recommendations:
            content.append("## 💡 建议与推荐")
            content.append("")
            for i, recommendation in enumerate(report.recommendations, 1):
                content.append(f"{i}. {recommendation}")
                content.append("")
        
        # Sources - 精简格式
        if report.sources:
            content.append("## 📖 参考来源")
            content.append("")
            # 只显示前10个来源
            for i, source in enumerate(report.sources[:10], 1):
                content.append(f"{i}. {source}")
            if len(report.sources) > 10:
                content.append(f"... 共 {len(report.sources)} 个参考来源")
            content.append("")
        
        # Minimal footer
        content.append("---")
        content.append("")
        content.append(f"*本报告由 LandPPT 增强研究系统生成 - {datetime.now().strftime('%Y年%m月%d日')}*")
        
        return "\n".join(content)

    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for safe file system usage"""
        # Remove or replace invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Remove extra spaces and limit length
        filename = re.sub(r'\s+', '_', filename.strip())
        return filename[:50] if len(filename) > 50 else filename
    
    def list_reports(self) -> List[Dict[str, Any]]:
        """List all saved research reports"""
        reports = []
        
        try:
            for file_path in self.reports_dir.glob("*.md"):
                if file_path.is_file():
                    stat = file_path.stat()
                    reports.append({
                        'filename': file_path.name,
                        'path': str(file_path.absolute()),
                        'size': stat.st_size,
                        'created': datetime.fromtimestamp(stat.st_ctime),
                        'modified': datetime.fromtimestamp(stat.st_mtime)
                    })
            
            # Sort by modification time (newest first)
            reports.sort(key=lambda x: x['modified'], reverse=True)
            
        except Exception as e:
            logger.error(f"Failed to list reports: {e}")
        
        return reports
