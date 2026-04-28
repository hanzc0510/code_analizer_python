#!/usr/bin/env python3
"""调试 C# 分析器"""
import sys
from pathlib import Path
sys.path.insert(0, '.')

from tree_sitter import Parser, Language
from tree_sitter_c_sharp import language as csharp_language

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

# 解析
parser = Parser(Language(csharp_language()))
tree = parser.parse(bytes(source, 'utf-8'))

def print_node(node, indent=0):
    print("  " * indent + f"{node.type} [{node.start_point[0]}-{node.end_point[0]}]: `{source[node.start_byte:node.end_byte][:50]}`")
    for child in node.children:
        print_node(child, indent + 1)

print("=" * 80)
print("C# AST Tree:")
print("=" * 80)
print_node(tree.root_node)

# 查找类声明
print("\n" + "=" * 80)
print("查找类声明节点:")
print("=" * 80)

def find_classes(node):
    if node.type == 'class_declaration':
        print(f"\n类节点:")
        for i, child in enumerate(node.children):
            print(f"  [{i}] {child.type}: `{source[child.start_byte:child.end_byte]}`")
            for k, n in enumerate(child.children):
                print(f"    [{k}] {n.type}: `{source[n.start_byte:n.end_byte]}`")
    for child in node.children:
        find_classes(child)

find_classes(tree.root_node)
