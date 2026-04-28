from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional
from tree_sitter import Parser, Language as TSLanguage, Tree, Node
from ..models.project import Module, FunctionDef, ClassDef, VariableDef, Import, Language
from ..utils.logger import get_logger


logger = get_logger()


class BaseAnalyzer(ABC):
    """代码分析器基类"""

    language: Language
    tree_sitter_language: TSLanguage

    def __init__(self):
        self.parser = Parser(self.tree_sitter_language)

    def parse(self, source_bytes: bytes, file_path: Path) -> Optional[Module]:
        """
        解析代码文件

        Args:
            source_bytes: 源代码字节内容
            file_path: 文件路径

        Returns:
            Module 对象
        """
        if not source_bytes:
            return None

        try:
            tree = self.parser.parse(source_bytes)
        except Exception as e:
            logger.error(f"Failed to parse {file_path}: {e}")
            return None

        module = Module(
            file_path=file_path,
            language=self.language,
            relative_path=str(file_path),
            size=len(source_bytes),
            line_count=source_bytes.count(b'\n') + 1
        )

        try:
            self._extract_imports(tree.root_node, source_bytes, module)
            self._extract_classes(tree.root_node, source_bytes, module)
            self._extract_functions(tree.root_node, source_bytes, module)
            self._extract_variables(tree.root_node, source_bytes, module)
        except Exception as e:
            logger.error(f"Error extracting elements from {file_path}: {e}")

        return module

    def _get_node_text(self, node: Node, source: bytes) -> str:
        """获取节点对应的源代码文本"""
        return source[node.start_byte:node.end_byte].decode('utf-8', errors='replace')

    @abstractmethod
    def _extract_imports(self, root_node: Node, source: bytes, module: Module):
        """提取导入语句"""
        pass

    @abstractmethod
    def _extract_classes(self, root_node: Node, source: bytes, module: Module):
        """提取类定义"""
        pass

    @abstractmethod
    def _extract_functions(self, root_node: Node, source: bytes, module: Module):
        """提取函数定义"""
        pass

    @abstractmethod
    def _extract_variables(self, root_node: Node, source: bytes, module: Module):
        """提取变量定义"""
        pass

    def find_calls(self, node: Node, source: bytes) -> List[str]:
        """
        查找节点中的所有函数调用

        Args:
            node: AST 节点
            source: 源代码字节

        Returns:
            被调用的函数名列表
        """
        calls = []
        self._find_calls_recursive(node, source, calls)
        return list(set(calls))

    def _find_calls_recursive(self, node: Node, source: bytes, calls: List[str]):
        """递归查找函数调用"""
        if node.type == 'call_expression':
            # 不同语言的调用表达式结构可能不同，子类可以重写
            func_name = self._extract_call_name(node, source)
            if func_name:
                calls.append(func_name)

        for child in node.children:
            self._find_calls_recursive(child, source, calls)

    def _extract_call_name(self, node: Node, source: bytes) -> Optional[str]:
        """从调用表达式中提取函数名 - 子类重写"""
        return None
