#!/usr/bin/env python3
"""分析若依项目 V2 版本 - 使用知识库存储和新版报告"""
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
from src.models.project import Project


async def main():
    project_root = Path(r"D:\projects\Java\ruoyi-vue-pro")
    print(f"开始分析: {project_root}")

    config = Config()
    config.set_project_root(str(project_root))
    config.analysis.use_llm = False

    # 1. 初始化知识库
    print("\n[1/6] 初始化知识库...")
    kb = KnowledgeBase("./output/knowledge.db")
    project_id = kb.get_or_create_project(str(project_root), "ruoyi-vue-pro")
    print("  知识库已就绪")

    # 2. 扫描
    print("\n[2/6] 扫描代码文件...")
    scanner = CodeScanner(config)
    code_files = scanner.scan_directory(str(project_root))
    print(f"  发现 {len(code_files)} 个代码文件")

    # 统计语言
    lang_count = {}
    for _, lang in code_files:
        lang_count[lang.value] = lang_count.get(lang.value, 0) + 1
    print("  语言分布:")
    for lang, count in lang_count.items():
        print(f"    - {lang}: {count} 个文件")

    # 检查增量
    unchanged = 0
    to_analyze = []
    for file_path, lang in code_files:
        if kb.is_file_unchanged(str(file_path), file_path.stat().st_size, file_path.stat().st_mtime):
            unchanged += 1
        else:
            to_analyze.append((file_path, lang))

    print(f"  未变更文件: {unchanged} 个")
    print(f"  待分析文件: {len(to_analyze)} 个")

    # 3. 解析
    print(f"\n[3/6] 解析代码 AST... (共 {len(to_analyze)} 个文件)")
    project = Project(root_path=project_root, name=project_root.name)
    parser = ASTParser(config)

    for idx, (file_path, lang) in enumerate(to_analyze, 1):
        if idx % 100 == 0:
            print(f"  进度: {idx}/{len(to_analyze)}")

        source_code = CodeScanner.read_file(file_path)
        if not source_code:
            continue

        module = parser.parse_file(file_path, lang, source_code)
        if module:
            try:
                module.relative_path = str(file_path.relative_to(project_root))
            except ValueError:
                module.relative_path = str(file_path)
            project.modules.append(module)

    print(f"  解析完成: {len(project.modules)} 个新文件")

    # 4. 保存到知识库
    print("\n[4/6] 保存到知识库...")
    for idx, module in enumerate(project.modules, 1):
        if idx % 100 == 0:
            print(f"  保存进度: {idx}/{len(project.modules)}")
        kb.save_module(project_id, module)

    # 更新项目统计
    # 这里需要从知识库读取所有模块来统计
    summary = kb.get_project_summary(project_id)
    project.total_files = summary['project']['total_files']
    project.total_lines = summary['project']['total_lines']
    print(f"  保存完成: {summary['class_count']} 个类, {summary['function_count']} 个函数")

    # 5. 构建调用图
    print("\n[5/6] 构建调用图...")
    call_graph = CallGraph(project)
    call_graph.build()
    project.entry_points = call_graph.find_entry_points()[:50]
    print(f"  调用图: {call_graph.graph.number_of_nodes()} 个节点, {call_graph.graph.number_of_edges()} 条边")

    # 6. 生成报告
    print("\n[6/6] 生成报告...")
    reporter = ReportGeneratorV2("./output")

    # 生成精简版报告
    light_report = reporter.generate_light_report(project)
    print(f"  精简报告: {light_report}")

    # 生成分拆版报告
    split_report = reporter.generate_full_split_report(project)
    print(f"  分拆报告: {split_report}")

    kb.close()

    print("\n" + "=" * 60)
    print("分析完成！")
    print("=" * 60)
    print(f"\n项目摘要:")
    print(f"  总文件数: {summary['project']['total_files']}")
    print(f"  总代码行: {summary['project']['total_lines']:,}")
    print(f"  类数量: {summary['class_count']}")
    print(f"  函数数量: {summary['function_count']}")

    print(f"\n知识库位置: ./output/knowledge.db")
    print(f"报告位置: ./output/")


if __name__ == "__main__":
    asyncio.run(main())
