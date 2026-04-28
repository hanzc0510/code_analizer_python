#!/usr/bin/env python3
"""
代码分析工具 - 复刻 DeepWiki 功能
支持 Python, Java, C#, JavaScript, TypeScript
"""

import asyncio
import click
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from src.utils.config import Config
from src.utils.logger import get_logger
from src.core.scanner import CodeScanner
from src.core.ast_parser import ASTParser
from src.core.call_graph import CallGraph
from src.core.llm_client import LLMClient
from src.core.report_generator import ReportGenerator
from src.models.project import Project


console = Console()
logger = get_logger()


async def analyze_project(
    root_path: str,
    output_dir: str = "./output",
    config_file: str = None,
    use_llm: bool = True,
    skip_llm: bool = False,
) -> Project:
    """
    分析项目代码

    Args:
        root_path: 项目根目录
        output_dir: 输出目录
        config_file: 配置文件路径
        use_llm: 是否使用 LLM 进行深度分析
        skip_llm: 跳过 LLM 分析（强制）

    Returns:
        Project 对象
    """
    root = Path(root_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Project path not found: {root}")

    config = Config(config_file)
    config.set_project_root(str(root))

    # 如果 output_dir 是默认值 ./output，则自动使用项目名作为子目录
    if output_dir == './output':
        output_dir = f'./output/{root.name}'

    config.set_output_dir(output_dir)

    if skip_llm:
        config.analysis.use_llm = False
    else:
        config.analysis.use_llm = use_llm

    console.print(f"\n[bold blue]开始分析项目:[/] {root}")
    console.print(f"输出目录: {config.output_dir}\n")

    # 1. 扫描代码文件
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        scan_task = progress.add_task("扫描代码文件...", total=None)

        scanner = CodeScanner(config)
        code_files = scanner.scan_directory(str(root))

        if not code_files:
            console.print("[yellow]警告: 未找到任何支持的代码文件[/]")
            return Project(root_path=root, name=root.name)

        progress.update(scan_task, description=f"发现 {len(code_files)} 个代码文件 ✓")

        # 2. 解析 AST
        parse_task = progress.add_task("解析代码...", total=None)

        project = Project(root_path=root, name=root.name)
        parser = ASTParser(config)
        project = parser.parse_project(project, code_files)

        progress.update(parse_task, description=f"解析完成: {project.total_files} 个文件, {project.total_lines} 行代码 ✓")

        # 3. 构建调用图
        cg_task = progress.add_task("构建调用图...", total=None)

        call_graph = CallGraph(project)
        call_graph.build()

        # 分析架构
        arch_analysis = call_graph.analyze_architecture()
        project.entry_points = call_graph.find_entry_points()
        project.core_modules = arch_analysis.get("core_modules", [])

        progress.update(cg_task, description=f"调用图构建完成: {call_graph.graph.number_of_nodes()} 个节点, {call_graph.graph.number_of_edges()} 条边 ✓")

    # 4. LLM 深度分析
    if config.analysis.use_llm:
        console.print("\n[bold blue]开始 LLM 深度分析...[/]")

        llm_client = LLMClient(config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:

            def progress_callback(phase, current, total):
                if phase == "function":
                    progress.update(func_task, completed=current, total=total)
                elif phase == "class":
                    progress.update(class_task, completed=current, total=total)
                elif phase == "module":
                    progress.update(module_task, completed=current, total=total)

            all_funcs = project.get_all_functions()
            all_classes = project.get_all_classes()

            func_task = progress.add_task(f"分析函数 ({len(all_funcs)})", total=len(all_funcs))
            class_task = progress.add_task(f"分析类 ({len(all_classes)})", total=len(all_classes))
            module_task = progress.add_task(f"分析模块 ({len(project.modules)})", total=len(project.modules))

            await llm_client.analyze_project(project, progress_callback)

        console.print("[green]LLM 分析完成[/]")

    # 5. 生成报告
    console.print("\n[bold blue]生成分析报告...[/]")

    report_generator = ReportGenerator(str(config.output_dir))

    # 生成完整报告
    report_path = report_generator.generate_full_report(project)
    summary_path = report_generator.generate_summary_report(project)

    console.print(f"[green]完整报告已生成:[/] {report_path}")
    console.print(f"[green]摘要报告已生成:[/] {summary_path}\n")

    # 打印项目摘要
    console.print("[bold]项目摘要[/]")
    console.print(f"  总文件数: {project.total_files}")
    console.print(f"  总代码行: {project.total_lines}")

    if project.language_stats:
        console.print("  语言分布:")
        for lang, count in project.language_stats.items():
            console.print(f"    {lang.value}: {count} 个文件")

    return project


@click.group()
def cli():
    """代码分析工具 - 复刻 DeepWiki 功能"""
    pass


@cli.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('--output', '-o', default='./output', help='输出目录')
@click.option('--config', '-c', default=None, help='配置文件路径')
@click.option('--skip-llm', is_flag=True, help='跳过 LLM 分析')
def analyze(path, output, config, skip_llm):
    """分析项目代码并生成报告"""
    asyncio.run(analyze_project(
        root_path=path,
        output_dir=output,
        config_file=config,
        skip_llm=skip_llm,
    ))


@cli.command()
def version():
    """显示版本信息"""
    console.print("code_analysis_agent v0.1.0")
    console.print("支持语言: Python, Java, C#, JavaScript, TypeScript")


if __name__ == "__main__":
    cli()
