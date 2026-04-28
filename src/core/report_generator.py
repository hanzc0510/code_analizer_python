from pathlib import Path
from typing import Optional
from ..models.project import Project
from ..utils.logger import get_logger


logger = get_logger()


class ReportGenerator:
    """Markdown 报告生成器"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_full_report(self, project: Project, filename: str = "analysis_report.md") -> str:
        """生成完整分析报告"""
        logger.info(f"Generating report: {filename}")

        lines = []
        lines.append(f"# {project.name} 代码分析报告")
        lines.append("")
        lines.append("## 项目概览")
        lines.append("")
        lines.append(f"- **项目路径**: {project.root_path}")
        lines.append(f"- **代码文件数**: {project.total_files}")
        lines.append(f"- **总代码行数**: {project.total_lines}")
        lines.append("")

        if project.language_stats:
            lines.append("### 语言分布")
            lines.append("")
            for lang, count in project.language_stats.items():
                lines.append(f"- {lang.value}: {count} 个文件")
            lines.append("")

        if project.architecture_summary:
            lines.append("## 架构分析")
            lines.append("")
            lines.append(project.architecture_summary)
            lines.append("")

        if project.business_overview:
            lines.append("## 业务逻辑分析")
            lines.append("")
            lines.append(project.business_overview)
            lines.append("")

        if project.entry_points:
            lines.append("## 入口点分析")
            lines.append("")
            lines.append("主要入口函数:")
            lines.append("")
            for entry in project.entry_points[:10]:
                lines.append(f"- `{entry}`")
            lines.append("")

        lines.append("## 模块详情")
        lines.append("")

        for module in project.modules:
            lines.append(f"### {module.relative_path}")
            lines.append("")
            lines.append(f"> 语言: {module.language.value}, 代码行数: {module.line_count}")
            lines.append("")

            if module.summary:
                lines.append("**模块摘要**:")
                lines.append("")
                lines.append(module.summary)
                lines.append("")

            if module.imports:
                lines.append("**导入**:")
                lines.append("")
                for imp in module.imports:
                    lines.append(f"- `{imp.module}`")
                lines.append("")

            if module.depends_on:
                lines.append("**依赖模块**:")
                lines.append("")
                for dep in module.depends_on:
                    lines.append(f"- `{dep}`")
                lines.append("")

            if module.classes:
                lines.append("#### 类定义")
                lines.append("")
                for cls in module.classes:
                    lines.append(f"##### {cls.name} (第 {cls.start_line}-{cls.end_line} 行)")
                    lines.append("")
                    if cls.modifiers:
                        lines.append(f"修饰符: `{', '.join(cls.modifiers)}`")
                    if cls.bases:
                        lines.append(f"父类: `{', '.join(cls.bases)}`")
                    lines.append("")

                    if cls.summary:
                        lines.append(cls.summary)
                        lines.append("")

                    if cls.methods:
                        lines.append("**方法**:")
                        lines.append("")
                        for method in cls.methods:
                            params = ', '.join(p.name for p in method.parameters)
                            ret = f" -> `{method.return_type}`" if method.return_type else ""
                            lines.append(f"- `{method.name}({params})`{ret}")
                        lines.append("")

                lines.append("")

            if module.functions:
                lines.append("#### 函数定义")
                lines.append("")
                for func in module.functions:
                    lines.append(f"##### {func.name} (第 {func.start_line}-{func.end_line} 行)")
                    lines.append("")
                    params = ', '.join(p.name for p in func.parameters)
                    ret = f" -> `{func.return_type}`" if func.return_type else ""
                    lines.append(f"签名: `{func.name}({params})`{ret}")
                    lines.append("")

                    if func.summary:
                        lines.append(func.summary)
                        lines.append("")

                    if func.calls:
                        calls_str = ', '.join(func.calls[:10])
                        more = "..." if len(func.calls) > 10 else ""
                        lines.append(f"调用: `{calls_str}`{more}")
                        lines.append("")

                lines.append("")

            lines.append("---")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("*由 code_analysis_agent 生成*")

        report_content = '\n'.join(lines)

        output_path = self.output_dir / filename
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report_content)

        logger.info(f"Report saved to: {output_path}")
        return str(output_path)

    def generate_summary_report(self, project: Project, filename: str = "summary.md") -> str:
        """生成摘要报告"""
        lines = [
            f"# {project.name} 项目摘要",
            "",
            "## 概览",
            f"- 文件数: {project.total_files}",
            f"- 代码行数: {project.total_lines}",
            "",
            "## 架构",
            project.architecture_summary or "暂未分析",
            "",
            "## 业务逻辑",
            project.business_overview or "暂未分析",
            "",
            "## 核心模块",
            "",
        ]

        for module in project.modules[:10]:
            lines.append(f"### {module.relative_path}")
            lines.append(module.summary or "暂无摘要")
            lines.append("")

        report_content = '\n'.join(lines)

        output_path = self.output_dir / filename
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report_content)

        return str(output_path)
