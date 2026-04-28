#!/usr/bin/env python3
"""调试方法提取"""
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

parser = Parser(Language(csharp_language()))
tree = parser.parse(bytes(source, 'utf-8'))

def print_node(node, indent=0):
    prefix = "  " * indent
    print(f"{prefix}{node.type}: `{source[node.start_byte:node.end_byte][:60]}`")
    for child in node.children:
        print_node(child, indent + 1)

# 查找类声明
def find_class(node):
    if node.type == 'class_declaration':
        return node
    for child in node.children:
        result = find_class(child)
        if result:
            return result
    return None

class_node = find_class(tree.root_node)
print("类节点的子节点:")
print_node(class_node)
