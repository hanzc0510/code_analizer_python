from tree_sitter import Node, Language as TSLanguage
from tree_sitter_javascript import language as js_language
from typing import Optional
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


class JSAnalyzer(BaseAnalyzer):
    """JavaScript/TypeScript 代码分析器"""

    language = Language.JAVASCRIPT
    tree_sitter_language = TSLanguage(js_language())

    def _extract_imports(self, root_node: Node, source: bytes, module: Module):
        """提取 ES6 import 语句"""
        def visit_imports(node: Node):
            if node.type == 'import_statement':
                module_name = ""
                names = []

                source_node = node.child_by_field_name('source')
                if source_node:
                    module_name = self._get_node_text(source_node, source).strip('"\'')

                import_clause = node.child_by_field_name('import_clause')
                if import_clause:
                    for child in import_clause.children:
                        if child.type == 'named_imports':
                            for spec in child.children:
                                if spec.type == 'import_specifier':
                                    name_node = spec.child_by_field_name('name')
                                    if name_node:
                                        names.append(self._get_node_text(name_node, source))
                        elif child.type == 'identifier':
                            names.append(self._get_node_text(child, source))
                        elif child.type == 'namespace_import':
                            names.append('*')

                if module_name:
                    module.imports.append(Import(module=module_name, names=names))

            elif node.type == 'variable_declaration':
                # CommonJS require: const x = require('x')
                for child in node.children:
                    if child.type == 'variable_declarator':
                        init = child.child_by_field_name('init')
                        if init and init.type == 'call_expression':
                            func = init.child_by_field_name('function')
                            if func and self._get_node_text(func, source) == 'require':
                                args = init.child_by_field_name('arguments')
                                if args:
                                    for arg in args.children:
                                        if arg.type in ['string', 'string_fragment']:
                                            module_name = self._get_node_text(arg, source).strip('"\'')
                                            name_node = child.child_by_field_name('name')
                                            names = []
                                            if name_node:
                                                names.append(self._get_node_text(name_node, source))
                                            module.imports.append(Import(module=module_name, names=names))

            for child in node.children:
                visit_imports(child)

        visit_imports(root_node)

    def _extract_classes(self, root_node: Node, source: bytes, module: Module):
        """提取类定义"""
        def visit_classes(node: Node, parent_class: Optional[ClassDef] = None):
            if node.type == 'class_declaration' or node.type == 'class':
                cls = self._parse_class(node, source)
                if cls:
                    if parent_class:
                        parent_class.nested_classes.append(cls)
                    else:
                        module.classes.append(cls)

                    # 查找内部类
                    body = node.child_by_field_name('body')
                    if body:
                        for child in body.children:
                            visit_classes(child, cls)

            for child in node.children:
                visit_classes(child, parent_class)

        visit_classes(root_node)

    def _extract_functions(self, root_node: Node, source: bytes, module: Module):
        """提取函数定义"""
        def visit_funcs(node: Node, in_class=False):
            if in_class:
                return

            if node.type == 'function_declaration':
                func = self._parse_function(node, source)
                if func:
                    module.functions.append(func)
            elif node.type == 'variable_declaration':
                # 函数表达式: const f = function() {} 或 const f = () => {}
                for child in node.children:
                    if child.type == 'variable_declarator':
                        init = child.child_by_field_name('init')
                        if init and init.type in ['function', 'arrow_function']:
                            name_node = child.child_by_field_name('name')
                            if name_node:
                                func = self._parse_function(init, source)
                                if func:
                                    func.name = self._get_node_text(name_node, source)
                                    module.functions.append(func)

            for child in node.children:
                visit_funcs(child, in_class)

        visit_funcs(root_node)

    def _extract_variables(self, root_node: Node, source: bytes, module: Module):
        """提取变量"""
        pass

    def _parse_class(self, node: Node, source: bytes) -> Optional[ClassDef]:
        """解析类定义"""
        name_node = node.child_by_field_name('name')
        if not name_node:
            return None

        name = self._get_node_text(name_node, source)

        # 父类
        bases = []
        heritage = node.child_by_field_name('heritage')
        if heritage:
            for child in heritage.children:
                if child.type == 'identifier':
                    bases.append(self._get_node_text(child, source))

        # 方法
        methods = []
        body = node.child_by_field_name('body')
        if body:
            for child in body.children:
                if child.type == 'method_definition':
                    method = self._parse_method(child, source)
                    if method:
                        methods.append(method)

        return ClassDef(
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            content=self._get_node_text(node, source),
            bases=bases,
            methods=methods
        )

    def _parse_function(self, node: Node, source: bytes, name: str = "") -> Optional[FunctionDef]:
        """解析函数定义"""
        if not name:
            name_node = node.child_by_field_name('name')
            if name_node:
                name = self._get_node_text(name_node, source)

        if not name:
            name = "<anonymous>"

        # 参数
        params = []
        params_node = node.child_by_field_name('parameters')
        if params_node:
            for child in params_node.children:
                if child.type in ['identifier', 'rest_pattern']:
                    param_name = self._get_node_text(child, source)
                    params.append(Parameter(name=param_name))

        # 调用关系
        body = node.child_by_field_name('body')
        calls = []
        if body:
            calls = self.find_calls(body, source)

        is_async = node.type == 'async_function'

        return FunctionDef(
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            content=self._get_node_text(node, source),
            parameters=params,
            is_async=is_async,
            calls=calls
        )

    def _parse_method(self, node: Node, source: bytes) -> Optional[FunctionDef]:
        """解析类方法"""
        name_node = node.child_by_field_name('name')
        if not name_node:
            return None

        name = self._get_node_text(name_node, source)

        # 参数
        params = []
        params_node = node.child_by_field_name('parameters')
        if params_node:
            for child in params_node.children:
                if child.type == 'identifier':
                    param_name = self._get_node_text(child, source)
                    params.append(Parameter(name=param_name))

        # 调用关系
        body = node.child_by_field_name('body')
        calls = []
        if body:
            calls = self.find_calls(body, source)

        is_static = False
        for child in node.children:
            if child.type == 'static':
                is_static = True
                break

        is_async = False
        for child in node.children:
            if child.type == 'async':
                is_async = True
                break

        return FunctionDef(
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            content=self._get_node_text(node, source),
            parameters=params,
            is_static=is_static,
            is_async=is_async,
            calls=calls
        )

    def _extract_call_name(self, node: Node, source: bytes) -> Optional[str]:
        """从调用表达式中提取函数名"""
        func_node = node.child_by_field_name('function')
        if func_node:
            if func_node.type == 'identifier':
                return self._get_node_text(func_node, source)
            elif func_node.type == 'member_expression':
                prop = func_node.child_by_field_name('property')
                if prop:
                    return self._get_node_text(prop, source)
        return None
