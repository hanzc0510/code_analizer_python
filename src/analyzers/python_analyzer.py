from tree_sitter import Node, Language as TSLanguage
from tree_sitter_python import language as python_language
from typing import Optional, List
from .base import BaseAnalyzer
from ..models.project import (
    Module,
    FunctionDef,
    ClassDef,
    VariableDef,
    Import,
    Parameter,
    Language,
)
from ..utils.logger import get_logger


logger = get_logger()


class PythonAnalyzer(BaseAnalyzer):
    """Python 代码分析器"""

    language = Language.PYTHON
    tree_sitter_language = TSLanguage(python_language())

    def _extract_imports(self, root_node: Node, source: bytes, module: Module):
        """提取 Python 导入语句"""

        def visit_imports(node: Node):
            if node.type == 'import_statement':
                # import X, import X as Y
                for child in node.children:
                    if child.type == 'dotted_name':
                        name = self._get_node_text(child, source)
                        module.imports.append(Import(module=name))
                    elif child.type == 'aliased_import':
                        # X as Y
                        for sub in child.children:
                            if sub.type == 'dotted_name':
                                name = self._get_node_text(sub, source)
                            elif sub.type == 'identifier':
                                alias = self._get_node_text(sub, source)
                        module.imports.append(Import(module=name, alias=alias))

            elif node.type == 'import_from_statement':
                # from X import Y
                module_name = ""
                names = []

                for child in node.children:
                    if child.type == 'dotted_name':
                        module_name = self._get_node_text(child, source)
                    elif child.type == 'wildcard_import':
                        names.append('*')
                    elif child.type == 'import_from_clause':
                        for sub in child.children:
                            if sub.type == 'dotted_name':
                                names.append(self._get_node_text(sub, source))
                            elif sub.type == 'aliased_import':
                                for s in sub.children:
                                    if s.type == 'dotted_name':
                                        names.append(self._get_node_text(s, source))

                if module_name:
                    module.imports.append(Import(module=module_name, names=names))

            for child in node.children:
                visit_imports(child)

        visit_imports(root_node)

    def _extract_classes(self, root_node: Node, source: bytes, module: Module):
        """提取 Python 类定义"""

        def visit_classes(node: Node, parent_class: Optional[ClassDef] = None):
            if node.type == 'class_definition':
                cls = self._parse_class_definition(node, source)
                if cls:
                    if parent_class:
                        parent_class.nested_classes.append(cls)
                    else:
                        module.classes.append(cls)

                    # 提取类内部的方法
                    for child in node.children:
                        if child.type == 'block':
                            for sub in child.children:
                                if sub.type == 'function_definition':
                                    method = self._parse_function_definition(sub, source)
                                    if method:
                                        cls.methods.append(method)
                                elif sub.type == 'class_definition':
                                    visit_classes(sub, cls)
            else:
                for child in node.children:
                    visit_classes(child, parent_class)

        visit_classes(root_node)

    def _extract_functions(self, root_node: Node, source: bytes, module: Module):
        """提取 Python 函数定义（模块级别）"""

        def visit_funcs(node: Node):
            if node.type == 'function_definition' and node.parent and node.parent.type != 'block':
                func = self._parse_function_definition(node, source)
                if func:
                    module.functions.append(func)
            else:
                for child in node.children:
                    visit_funcs(child)

        visit_funcs(root_node)

    def _extract_variables(self, root_node: Node, source: bytes, module: Module):
        """提取 Python 全局变量"""
        # 简单实现：提取模块级别赋值语句
        for node in root_node.children:
            if node.type == 'expression_statement':
                for child in node.children:
                    if child.type == 'assignment':
                        left = child.child_by_field_name('left')
                        if left and left.type == 'identifier':
                            var_name = self._get_node_text(left, source)
                            module.variables.append(VariableDef(
                                name=var_name,
                                start_line=left.start_point[0] + 1,
                                end_line=left.end_point[0] + 1,
                                is_global=True
                            ))

    def _parse_class_definition(self, node: Node, source: bytes) -> Optional[ClassDef]:
        """解析类定义"""
        name_node = node.child_by_field_name('name')
        if not name_node:
            return None

        name = self._get_node_text(name_node, source)
        bases = []

        # 提取父类
        superclass_node = node.child_by_field_name('superclasses')
        if superclass_node:
            for child in superclass_node.children:
                if child.type == 'dotted_name':
                    bases.append(self._get_node_text(child, source))

        # 提取 docstring
        docstring = ""
        body_node = node.child_by_field_name('body')
        if body_node:
            docstring = self._extract_docstring(body_node, source)

        return ClassDef(
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            content=self._get_node_text(node, source),
            docstring=docstring,
            bases=bases
        )

    def _parse_function_definition(self, node: Node, source: bytes) -> Optional[FunctionDef]:
        """解析函数定义"""
        name_node = node.child_by_field_name('name')
        if not name_node:
            return None

        name = self._get_node_text(name_node, source)

        # 提取参数
        params = []
        params_node = node.child_by_field_name('parameters')
        if params_node:
            for child in params_node.children:
                if child.type in ['typed_parameter', 'parameter']:
                    param_name = ""
                    type_hint = ""
                    for sub in child.children:
                        if sub.type == 'identifier':
                            param_name = self._get_node_text(sub, source)
                        elif sub.type == 'type':
                            type_hint = self._get_node_text(sub, source)
                    if param_name:
                        params.append(Parameter(name=param_name, type_hint=type_hint))
                elif child.type == 'identifier':
                    # 简单参数
                    params.append(Parameter(name=self._get_node_text(child, source)))

        # 提取返回类型
        return_type = ""
        return_node = node.child_by_field_name('return_type')
        if return_node:
            return_type = self._get_node_text(return_node, source)

        # 提取装饰器
        decorators = []
        for child in node.children:
            if child.type == 'decorator':
                decorators.append(self._get_node_text(child, source))

        # 提取 docstring
        docstring = ""
        body_node = node.child_by_field_name('body')
        if body_node:
            docstring = self._extract_docstring(body_node, source)

        # 提取函数调用
        calls = []
        if body_node:
            calls = self.find_calls(body_node, source)

        # 判断是否是私有函数
        is_private = name.startswith('_') and not name.startswith('__')
        is_async = node.type == 'async_function_definition'

        return FunctionDef(
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            content=self._get_node_text(node, source),
            docstring=docstring,
            parameters=params,
            return_type=return_type,
            is_async=is_async,
            is_private=is_private,
            decorators=decorators,
            calls=calls
        )

    def _extract_docstring(self, body_node: Node, source: bytes) -> str:
        """从函数/类体中提取 docstring"""
        for child in body_node.children:
            if child.type == 'expression_statement':
                for sub in child.children:
                    if sub.type in ['string', 'concatenated_string']:
                        text = self._get_node_text(sub, source)
                        # 去除引号
                        text = text.strip('"\'').strip('"""').strip("'''")
                        return text
        return ""

    def _extract_call_name(self, node: Node, source: bytes) -> Optional[str]:
        """从调用表达式中提取函数名"""
        func_node = node.child_by_field_name('function')
        if func_node:
            if func_node.type == 'identifier':
                return self._get_node_text(func_node, source)
            elif func_node.type == 'attribute':
                # 处理 a.b.c() 的情况
                attr_name = func_node.child_by_field_name('attribute')
                if attr_name:
                    return self._get_node_text(attr_name, source)
        return None
