#!/usr/bin/env python3
"""分析若依项目"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config import Config
from src.core.scanner import CodeScanner
from src.core.ast_parser import ASTParser
from src.core.call_graph import CallGraph
from src.core.report_generator import ReportGenerator
from src.models.project import Project


async def main():
    project_root = Path(r"D:\projects\Java\ruoyi-vue-pro")
    print(f"开始分析: {project_root}")

    config = Config()
    config.set_project_root(str(project_root))
    config.analysis.use_llm = False

    # 1. 扫描
    print("\n[1/4] 扫描代码文件...")
    scanner = CodeScanner(config)
    code_files = scanner.scan_directory(str(project_root))
    print(f"发现 {len(code_files)} 个代码文件")

    # 统计语言
    lang_count = {}
    for _, lang in code_files:
        lang_count[lang.value] = lang_count.get(lang.value, 0) + 1
    print("语言分布:")
    for lang, count in lang_count.items():
        print(f"  - {lang}: {count} 个文件")

    # 2. 解析
    print("\n[2/4] 解析代码 AST...")
    project = Project(root_path=project_root, name=project_root.name)
    parser = ASTParser(config)
    project = parser.parse_project(project, code_files)
    print(f"解析完成: {project.total_files} 个文件, {project.total_lines} 行代码")

    # 统计
    total_classes = sum(len(m.classes) for m in project.modules)
    total_functions = sum(len(m.functions) for m in project.modules)
    total_methods = sum(len(cls.methods) for m in project.modules for cls in m.classes)
    print(f"统计: {total_classes} 个类, {total_functions} 个函数, {total_methods} 个方法")

    # 3. 调用图
    print("\n[3/4] 构建调用图...")
    call_graph = CallGraph(project)
    call_graph.build()
    print(f"调用图: {call_graph.graph.number_of_nodes()} 个节点, {call_graph.graph.number_of_edges()} 条边")

    arch = call_graph.analyze_architecture()
    project.entry_points = call_graph.find_entry_points()[:20]
    project.core_modules = arch['core_modules'][:10]

    # 4. 生成报告
    print("\n[4/4] 生成报告...")
    reporter = ReportGenerator("./output")
    report_path = reporter.generate_full_report(project)
    reporter.generate_summary_report(project)
    print(f"报告已生成: {report_path}")

    print("\n" + "=" * 60)
    print("分析完成！")
    print(f"报告位置: {Path(report_path).absolute()}")
    print("=" * 60)

    # 打印摘要
    print("\n项目摘要:")
    print(f"  总文件数: {project.total_files}")
    print(f"  总代码行: {project.total_lines}")
    print(f"  核心模块数: {len(project.core_modules)}")

    print("\n入口点 (前10个):")
    for i, entry in enumerate(project.entry_points[:10]):
        print(f"  {i+1}. {entry}")


if __name__ == "__main__":
    asyncio.run(main())
