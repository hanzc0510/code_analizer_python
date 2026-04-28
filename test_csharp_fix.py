#!/usr/bin/env python3
"""测试 C# 分析器修复"""
import sys
from pathlib import Path
sys.path.insert(0, '.')

from src.analyzers.csharp_analyzer import CSharpAnalyzer

source = """using System;

namespace Dapper
{
    public static class SqlMapper
    {
        public static IEnumerable<T> Query<T>(this IDbConnection cnn, string sql)
        {
            cnn.Open();
            var result = cnn.Execute(sql);
            return new List<T>();
        }
    }
}
"""

source_bytes = source.encode('utf-8')
analyzer = CSharpAnalyzer()
module = analyzer.parse(source_bytes, "test.cs")

print("=" * 60)
print("解析结果:")
print("=" * 60)
print(f"模块路径: {module.file_path}")
print(f"类数量: {len(module.classes)}")

for cls in module.classes:
    print(f"\n类: {cls.name}")
    print(f"  修饰符: {cls.modifiers}")
    print(f"  方法数: {len(cls.methods)}")
    for method in cls.methods:
        print(f"    方法: {method.name}")
        print(f"      返回类型: {method.return_type}")
        print(f"      参数: {[p.name for p in method.parameters]}")
        print(f"      调用: {method.calls}")

print("\n" + "=" * 60)
print("导入:")
print("=" * 60)
for imp in module.imports:
    print(f"  {imp.module}")
