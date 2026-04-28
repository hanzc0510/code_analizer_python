#!/usr/bin/env python3
"""分析 Dapper 项目"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config import Config
from src.core.scanner import CodeScanner
from src.core.ast_parser import ASTParser
from src.core.call_graph import CallGraph
from src.core.knowledge_base import KnowledgeBase
from src.core.report_generator_v2 import ReportGeneratorV2
from src.core.llm_client import LLMClient
from src.models.project import Project


async def main():
    project_root = Path(r"D:\GitHub\Dapper-main")
    print(f"开始分析: {project_root}")

    config = Config()
    config.set_project_root(str(project_root))
    output_dir = f"./output/{project_root.name}"
    print(f"输出目录: {output_dir}")

    # 1. 扫描
    print("\n[1/6] 扫描代码文件...")
    scanner = CodeScanner(config)
    code_files = scanner.scan_directory(str(project_root))
    print(f"  发现 {len(code_files)} 个代码文件")

    lang_count = {}
    for _, lang in code_files:
        lang_count[lang.value] = lang_count.get(lang.value, 0) + 1
    print("  语言分布:")
    for lang, count in lang_count.items():
        print(f"    - {lang}: {count} 个文件")

    if not code_files:
        print("没有找到代码文件！")
        return

    # 2. 检查缓存 - 如果知识库已存在且文件无变更，直接使用现有结果
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    kb = KnowledgeBase(f"{output_dir}/knowledge.db")
    project_id = kb.get_or_create_project(str(project_root), project_root.name)

    # 检查有多少文件未变更
    unchanged_count = 0
    for file_path, lang in code_files:
        file_size = file_path.stat().st_size
        file_mtime = file_path.stat().st_mtime
        if kb.is_file_unchanged(str(file_path), file_size, file_mtime):
            unchanged_count += 1

    # 如果全部命中缓存，直接使用现有数据库
    if unchanged_count == len(code_files):
        print("\n[2/6] 全部文件已缓存，跳过解析")
        kb.close()

        # 读取项目统计用于显示
        kb2 = KnowledgeBase(f"{output_dir}/knowledge.db")
        summary = kb2.get_project_summary(project_id)
        kb2.close()

        project = Project(root_path=project_root, name=project_root.name)
        project.total_files = summary.get('class_count', 0) + summary.get('function_count', 0)
        project.total_files = len(code_files)

        print(f"  已缓存文件: {len(code_files)}")

        # 跳过后续步骤，直接完成
        print("\n[3/6] 调用图已缓存 ✓")
        print("\n[4/6] 知识库已缓存 ✓")
        print("\n[5/6] 报告已缓存 ✓")

    else:
        kb.close()
        # 有文件变更，完整重新分析
        print(f"\n[2/6] 解析代码 AST ({len(code_files) - unchanged_count} 个文件需重新解析)...")

        project = Project(root_path=project_root, name=project_root.name)
        parser = ASTParser(config)

        for idx, (file_path, lang) in enumerate(code_files, 1):
            if idx % 10 == 0:
                print(f"  进度: {idx}/{len(code_files)}")

            source_bytes = CodeScanner.read_file_bytes(file_path)
            if not source_bytes:
                continue

            analyzer = parser.get_analyzer(lang)
            if analyzer:
                module = analyzer.parse(source_bytes, file_path)
                if module:
                    module.relative_path = str(file_path.relative_to(project_root))
                    project.modules.append(module)

        project.total_files = len(project.modules)
        project.total_lines = sum(m.line_count for m in project.modules)
        print(f"  解析完成: {project.total_files} 个文件, {project.total_lines} 行代码")

        # 3. 构建调用图
        print("\n[3/6] 构建调用图...")
        call_graph = CallGraph(project)
        call_graph.build()
        project.entry_points = call_graph.find_entry_points()
        arch = call_graph.analyze_architecture()
        project.core_modules = arch.get('core_modules', [])
        print(f"  调用图: {call_graph.graph.number_of_nodes()} 节点, {call_graph.graph.number_of_edges()} 边")

        # 4. 保存到知识库
        print("\n[4/6] 保存到知识库...")
        kb = KnowledgeBase(f"{output_dir}/knowledge.db")
        project_id = kb.get_or_create_project(str(project_root), project.name)

        for module in project.modules:
            kb.save_module(project_id, module)

        # 保存调用图数据
        edges_data = [
            {"source": u, "target": v}
            for u, v in call_graph.graph.edges()
        ]
        kb.save_metadata(project_id, "call_graph", {"nodes": list(call_graph.graph.nodes()), "edges": edges_data})
        kb.save_metadata(project_id, "entry_points", project.entry_points)

        kb.close()
        print("  知识库已保存")

        # 5. 生成报告
        print("\n[5/6] 生成报告...")
        reporter = ReportGeneratorV2(output_dir)
        reporter.generate_light_report(project)
        reporter.generate_full_split_report(project)
        print(f"  报告已生成到: {output_dir}/")

    # 6. LLM 深度分析
    print("\n[6/6] LLM 深度分析...")
    config.analysis.use_llm = True
    llm = LLMClient(config)

    if llm.llm_enabled:
        print("  正在生成架构分析...")
        project.architecture_summary = await llm.analyze_architecture(project)
        print("  架构分析完成")
    else:
        print("  LLM 未启用，跳过深度分析")
        print("  如需启用，请配置环境变量 LLM_API_KEY")

    print("\n" + "=" * 60)
    print("分析完成！")
    print("=" * 60)
    print(f"\n项目: {project.name}")
    print(f"文件数: {project.total_files}")
    print(f"代码行: {project.total_lines}")
    print(f"\n报告目录: {output_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
