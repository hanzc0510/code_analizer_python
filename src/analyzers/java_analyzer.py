from tree_sitter import Node, Language as TSLanguage
from tree_sitter_java import language as java_language
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


class JavaAnalyzer(BaseAnalyzer):
    """Java 代码分析器"""

    language = Language.JAVA
    tree_sitter_language = TSLanguage(java_language())

    def _extract_imports(self, root_node: Node, source: bytes, module: Module):
        """提取 Java 导入语句"""
        for node in root_node.children:
            if node.type == 'import_declaration':
                is_static = False
                module_name = ""
                is_wildcard = False

                for child in node.children:
                    if child.type == 'static':
                        is_static = True
                    elif child.type == 'asterisk':
                        is_wildcard = True
                    elif child.type == 'identifier':
                        module_name = self._get_node_text(child, source)
                    elif child.type == 'scoped_identifier':
                        module_name = self._get_node_text(child, source)

                if module_name:
                    names = ['*'] if is_wildcard else []
                    module.imports.append(Import(
                        module=module_name,
                        names=names,
                    ))

    def _extract_classes(self, root_node: Node, source: bytes, module: Module):
        """提取 Java 类定义"""
        for node in root_node.children:
            if node.type == 'class_declaration':
                cls = self._parse_class(node, source)
                if cls:
                    module.classes.append(cls)
            elif node.type == 'interface_declaration':
                # 接口也作为类处理
                cls = self._parse_class(node, source)
                if cls:
                    module.classes.append(cls)

    def _extract_functions(self, root_node: Node, source: bytes, module: Module):
        """Java 函数都在类中，这里不用处理"""
        pass

    def _extract_variables(self, root_node: Node, source: bytes, module: Module):
        """提取字段"""
        for node in root_node.children:
            if node.type == 'field_declaration':
                self._extract_field_from_declaration(node, source, module.variables)

    def _parse_class(self, node: Node, source: bytes) -> Optional[ClassDef]:
        """解析类定义"""
        name_node = node.child_by_field_name('name')
        if not name_node:
            return None

        name = self._get_node_text(name_node, source)

        # 父类和接口
        bases = []
        superclass = node.child_by_field_name('superclass')
        if superclass:
            for child in superclass.children:
                if child.type == 'type_identifier':
                    bases.append(self._get_node_text(child, source))

        interfaces = node.child_by_field_name('interfaces')
        if interfaces:
            for child in interfaces.children:
                if child.type == 'type_identifier':
                    bases.append(self._get_node_text(child, source))

        # 修饰符
        modifiers = []
        for child in node.children:
            if child.type == 'modifiers':
                for mod in child.children:
                    modifiers.append(self._get_node_text(mod, source))

        # 提取方法和字段
        methods = []
        attributes = []
        body_node = node.child_by_field_name('body')
        if body_node:
            for child in body_node.children:
                if child.type == 'method_declaration':
                    method = self._parse_method(child, source)
                    if method:
                        methods.append(method)
                elif child.type == 'constructor_declaration':
                    # 构造函数
                    method = self._parse_constructor(child, source)
                    if method:
                        methods.append(method)
                elif child.type == 'field_declaration':
                    self._extract_field_from_declaration(child, source, attributes)

        return ClassDef(
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            content=self._get_node_text(node, source),
            bases=bases,
            methods=methods,
            attributes=attributes,
            modifiers=modifiers
        )

    def _parse_method(self, node: Node, source: bytes) -> Optional[FunctionDef]:
        """解析方法定义"""
        name_node = node.child_by_field_name('name')
        if not name_node:
            return None

        name = self._get_node_text(name_node, source)

        # 返回类型
        return_type = ""
        type_node = node.child_by_field_name('type')
        if type_node:
            return_type = self._get_node_text(type_node, source)

        # 参数
        params = []
        params_node = node.child_by_field_name('parameters')
        if params_node:
            for child in params_node.children:
                if child.type == 'formal_parameter':
                    param_name = ""
                    type_hint = ""
                    for sub in child.children:
                        if sub.type == 'identifier':
                            param_name = self._get_node_text(sub, source)
                        elif sub.type in ['type_identifier', 'integral_type', 'floating_point_type']:
                            type_hint = self._get_node_text(sub, source)
                    if param_name:
                        params.append(Parameter(name=param_name, type_hint=type_hint))

        # 修饰符
        modifiers = []
        is_static = False
        is_private = False
        for child in node.children:
            if child.type == 'modifiers':
                for mod in child.children:
                    mod_text = self._get_node_text(mod, source)
                    modifiers.append(mod_text)
                    if mod_text == 'static':
                        is_static = True
                    if mod_text == 'private':
                        is_private = True

        # 调用关系
        body_node = node.child_by_field_name('body')
        calls = []
        if body_node:
            calls = self.find_calls(body_node, source)

        return FunctionDef(
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            content=self._get_node_text(node, source),
            parameters=params,
            return_type=return_type,
            is_static=is_static,
            is_private=is_private,
            calls=calls,
            modifiers=modifiers
        )

    def _parse_constructor(self, node: Node, source: bytes) -> Optional[FunctionDef]:
        """解析构造函数"""
        name_node = node.child_by_field_name('name')
        if not name_node:
            return None

        name = self._get_node_text(name_node, source)

        # 参数
        params = []
        params_node = node.child_by_field_name('parameters')
        if params_node:
            for child in params_node.children:
                if child.type == 'formal_parameter':
                    param_name = ""
                    for sub in child.children:
                        if sub.type == 'identifier':
                            param_name = self._get_node_text(sub, source)
                    if param_name:
                        params.append(Parameter(name=param_name))

        return FunctionDef(
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            content=self._get_node_text(node, source),
            parameters=params,
            return_type="constructor",
        )

    def _extract_field_from_declaration(self, node: Node, source: bytes, var_list: list):
        """从字段声明中提取变量"""
        var_type = ""

        for child in node.children:
            if child.type in ['type_identifier', 'integral_type', 'floating_point_type']:
                var_type = self._get_node_text(child, source)
            elif child.type == 'variable_declarator_list':
                for sub in child.children:
                    if sub.type == 'variable_declarator':
                        name_node = sub.child_by_field_name('name')
                        if name_node:
                            var_name = self._get_node_text(name_node, source)
                            var_list.append(VariableDef(
                                name=var_name,
                                start_line=node.start_point[0] + 1,
                                end_line=node.end_point[0] + 1,
                                type_hint=var_type
                            ))

    def _extract_call_name(self, node: Node, source: bytes) -> Optional[str]:
        """从调用表达式中提取函数名"""
        func_node = node.child_by_field_name('function')
        if func_node:
            if func_node.type == 'identifier':
                return self._get_node_text(func_node, source)
            elif func_node.type == 'field_access':
                field = func_node.child_by_field_name('field')
                if field:
                    return self._get_node_text(field, source)
        return None
