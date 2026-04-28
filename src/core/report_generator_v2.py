"""新版报告生成器 - 支持多种格式和精简报告"""
from pathlib import Path
from typing import Optional
from jinja2 import Template
from ..models.project import Project
from ..utils.logger import get_logger

logger = get_logger()


class ReportGeneratorV2:
    """新版报告生成器"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_light_report(self, project: Project) -> str:
        """生成精简版报告 - 快速查看"""
        lines = []
        lines.append(f"# {project.name} 代码分析报告（精简版）")
        lines.append("")
        lines.append("## 项目概览")
        lines.append("")
        lines.append(f"- **项目路径**: {project.root_path}")
        lines.append(f"- **代码文件数**: {project.total_files}")
        lines.append(f"- **总代码行数**: {project.total_lines:,}")
        lines.append("")

        # 语言分布
        if project.language_stats:
            lines.append("### 语言分布")
            lines.append("")
            for lang, count in project.language_stats.items():
                lines.append(f"- {lang.value}: {count} 个文件")
            lines.append("")

        # 入口点
        if project.entry_points:
            lines.append("## 主要入口点")
            lines.append("")
            for entry in project.entry_points[:20]:
                # 简化显示
                short_name = entry.split('\\')[-1] if '\\' in entry else entry
                lines.append(f"- `{short_name}`")
            lines.append("")

        # 项目结构摘要 - 按目录分组
        lines.append("## 项目结构摘要")
        lines.append("")
        module_tree = self._build_module_tree(project)
        self._render_module_tree(lines, module_tree, 0, max_depth=3)
        lines.append("")

        # 核心模块 Top 20（类和方法最多的模块）
        lines.append("## 核心模块 Top 20")
        lines.append("")
        scored_modules = []
        for module in project.modules:
            score = len(module.classes) * 10 + len(module.functions)
            scored_modules.append((score, module))

        scored_modules.sort(key=lambda x: x[0], reverse=True)
        for score, module in scored_modules[:20]:
            lines.append(f"- **{module.relative_path}**")
            lines.append(f"  - 类: {len(module.classes)}, 函数: {len(module.functions)}")
        lines.append("")

        report_path = self.output_dir / "report_light.md"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"精简报告已生成: {report_path}")
        return str(report_path)

    def generate_full_split_report(self, project: Project) -> str:
        """生成分拆版报告 - 按目录拆分多个文件"""
        index_lines = []
        index_lines.append(f"# {project.name} 代码分析报告")
        index_lines.append("")
        index_lines.append("## 目录")
        index_lines.append("")
        index_lines.append("- [项目概览](00_overview.md)")
        index_lines.append("- [入口点分析](01_entrypoints.md)")
        index_lines.append("- [核心模块](02_core_modules.md)")
        index_lines.append("- [模块详情](03_modules.md)")
        index_lines.append("")

        # 1. 项目概览
        overview_lines = []
        overview_lines.append(f"# {project.name} - 项目概览")
        overview_lines.append("")
        overview_lines.append(f"- **路径**: {project.root_path}")
        overview_lines.append(f"- **文件数**: {project.total_files}")
        overview_lines.append(f"- **代码行数**: {project.total_lines:,}")
        overview_lines.append("")
        if project.language_stats:
            overview_lines.append("### 语言分布")
            overview_lines.append("")
            for lang, count in project.language_stats.items():
                overview_lines.append(f"- {lang.value}: {count} 个文件")
        with open(self.output_dir / "00_overview.md", 'w', encoding='utf-8') as f:
            f.write('\n'.join(overview_lines))

        # 2. 入口点分析
        entry_lines = []
        entry_lines.append("# 入口点分析")
        entry_lines.append("")
        if project.entry_points:
            for entry in project.entry_points[:50]:
                entry_lines.append(f"- `{entry}`")
        with open(self.output_dir / "01_entrypoints.md", 'w', encoding='utf-8') as f:
            f.write('\n'.join(entry_lines))

        # 3. 核心模块
        core_lines = []
        core_lines.append("# 核心模块")
        core_lines.append("")
        for module in sorted(project.modules, key=lambda m: len(m.classes) + len(m.functions), reverse=True)[:50]:
            core_lines.append(f"## {module.relative_path}")
            core_lines.append("")
            core_lines.append(f"- 类: {len(module.classes)}, 函数: {len(module.functions)}")
            core_lines.append("")
            if module.classes:
                core_lines.append("### 类")
                for cls in module.classes:
                    base_str = f" extends {', '.join(cls.bases)}" if cls.bases else ""
                    core_lines.append(f"- `{cls.name}`{base_str} ({len(cls.methods)} 个方法)")
                core_lines.append("")
        with open(self.output_dir / "02_core_modules.md", 'w', encoding='utf-8') as f:
            f.write('\n'.join(core_lines))

        # 4. 模块详情 - 按目录分组
        modules_lines = []
        modules_lines.append("# 模块详情")
        modules_lines.append("")

        modules_by_dir = {}
        for module in project.modules:
            parent = str(Path(module.relative_path).parent)
            if parent not in modules_by_dir:
                modules_by_dir[parent] = []
            modules_by_dir[parent].append(module)

        for dir_name in sorted(modules_by_dir.keys()):
            modules_lines.append(f"## {dir_name or '根目录'}")
            modules_lines.append("")
            for module in modules_by_dir[dir_name]:
                modules_lines.append(f"### {Path(module.relative_path).name}")
                modules_lines.append("")
                modules_lines.append(f"- 代码行: {module.line_count}")
                modules_lines.append(f"- 类: {len(module.classes)}")
                modules_lines.append(f"- 函数: {len(module.functions)}")
                if module.classes:
                    modules_lines.append("")
                    modules_lines.append("**类**:")
                    for cls in module.classes[:20]:
                        modules_lines.append(f"- `{cls.name}`")
                    if len(module.classes) > 20:
                        modules_lines.append(f"- 还有 {len(module.classes) - 20} 个类...")
                modules_lines.append("")

        with open(self.output_dir / "03_modules.md", 'w', encoding='utf-8') as f:
            f.write('\n'.join(modules_lines))

        # 生成索引文件
        with open(self.output_dir / "README.md", 'w', encoding='utf-8') as f:
            f.write('\n'.join(index_lines))

        logger.info(f"分拆报告已生成: {self.output_dir}")
        return str(self.output_dir)

    def _build_module_tree(self, project: Project) -> Dict:
        """构建模块目录树"""
        root = {"children": {}, "modules": [], "count": 0}

        for module in project.modules:
            parts = Path(module.relative_path).parts
            current = root

            for i, part in enumerate(parts[:-1]):
                if part not in current["children"]:
                    current["children"][part] = {"children": {}, "modules": [], "count": 0}
                current = current["children"][part]
                current["count"] += 1

            current["modules"].append(module)

        return root

    def _render_module_tree(self, lines: list, node: dict, depth: int, max_depth: int = 3):
        """渲染模块树"""
        if depth > max_depth:
            return

        indent = "  " * depth
        for name, child in sorted(node["children"].items()):
            lines.append(f"{indent}- **{name}/** ({child['count']} 个文件)")
            self._render_module_tree(lines, child, depth + 1, max_depth)
