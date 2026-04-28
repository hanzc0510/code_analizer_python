#!/usr/bin/env python3
"""
深度代码分析功能测试脚本
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config import Config
from src.core.llm_client import LLMClient
from src.core.deep_analyzer import DeepAnalyzer


async def test_simple():
    """测试深度分析引擎"""
    print("[Test] Deep Code Analyzer\n")

    # 加载配置
    config = Config()
    llm = LLMClient(config)

    if not llm.llm_enabled:
        print("[ERROR] LLM not configured, please set .env")
        return

    print("[OK] LLM Client initialized")
    print(f"   Model: {llm.config.llm.model}")
    print(f"   Base URL: {llm.config.llm.base_url}")

    # 创建一个测试用的简单 Project
    from src.models.project import Project, Module, ClassDef, FunctionDef, Language

    project = Project(root_path=Path("."), name="test_project")

    # 创建测试用的方法
    test_func = FunctionDef(
        name="calculate_total",
        start_line=10,
        end_line=25,
        content="""
def calculate_total(items, tax_rate=0.1):
    \"\"\"Calculate order total price\"\"\"
    total = 0
    for item in items:
        price = item.get('price', 0)
        quantity = item.get('quantity', 1)
        total += price * quantity

    # Calculate tax
    tax = total * tax_rate
    final_price = total + tax

    # Round to 2 decimal places
    return round(final_price, 2)
""".strip(),
        parameters=[],
        calls=[]
    )

    # 创建测试用的类
    test_class = ClassDef(
        name="OrderProcessor",
        start_line=1,
        end_line=50,
        methods=[test_func],
        bases=[]
    )

    # 创建模块
    module = Module(
        file_path=Path("order.py"),
        relative_path="order.py",
        language=Language.PYTHON,
        classes=[test_class],
        functions=[]
    )
    project.modules.append(module)

    print(f"\n[OK] Test project created: {len(project.modules)} modules")

    # 创建分析器
    db_path = Path("./output/test_project/knowledge.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    analyzer = DeepAnalyzer(project=project, llm_client=llm, db_path=str(db_path))
    print("[OK] Deep Analyzer initialized")

    # 分析方法
    print("\n[Analyzing] OrderProcessor.calculate_total")
    result = await analyzer.analyze_function(
        func=test_func,
        class_name="OrderProcessor",
        module_path="order.py"
    )

    print("\n" + "="*80)
    print("Analysis Result")
    print("="*80)
    print(f"Target: {result.target_name} ({result.target_type})")
    print(f"Summary: {result.summary}")
    print(f"Purpose: {result.purpose[:100]}...")
    print(f"Flow: {result.flow[:100]}...")
    print(f"Dependencies: {', '.join(result.dependencies) if result.dependencies else 'None'}")
    print(f"Side Effects: {', '.join(result.side_effects) if result.side_effects else 'None'}")
    print(f"Performance: {result.performance_notes or 'None'}")
    print(f"Edge Cases: {', '.join(result.edge_cases) if result.edge_cases else 'None'}")
    print(f"Security: {result.security_notes or 'None'}")
    print(f"Context Used: {len(result.context_used)} snippets")
    print(f"Code Hash: {result.code_hash}")
    print("="*80)

    print("\n[OK] Test completed!")

    # 测试缓存
    print("\n[Testing] Cache reuse...")
    cached_result = await analyzer.analyze_function(
        func=test_func,
        class_name="OrderProcessor",
        module_path="order.py"
    )
    print("[OK] Cache hit! Analysis result reused")


if __name__ == "__main__":
    asyncio.run(test_simple())
