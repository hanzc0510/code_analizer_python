from tree_sitter import Node, Language as TSLanguage
from tree_sitter_c_sharp import language as csharp_language
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


class CSharpAnalyzer(BaseAnalyzer):
    """C# 代码分析器"""

    language = Language.CSHARP
    tree_sitter_language = TSLanguage(csharp_language())

    def _extract_imports(self, root_node: Node, source: bytes, module: Module):
        """提取 C# using 语句"""
        for node in root_node.children:
            if node.type == 'using_directive':
                for child in node.children:
                    if child.type == 'qualified_name':
                        module_name = self._get_node_text(child, source)
                        module.imports.append(Import(module=module_name))
                    elif child.type == 'identifier':
                        module_name = self._get_node_text(child, source)
                        module.imports.append(Import(module=module_name))

    def _extract_classes(self, root_node: Node, source: bytes, module: Module):
        """提取 C# 类定义"""
        def visit_classes(node: Node, parent_class: Optional[ClassDef] = None):
            if node.type == 'class_declaration':
                cls = self._parse_class(node, source)
                if cls:
                    if parent_class:
                        parent_class.nested_classes.append(cls)
                    else:
                        module.classes.append(cls)
                    # 递归查找内部类 - 找 declaration_list
                    for child in node.children:
                        if child.type == 'declaration_list':
                            for sub in child.children:
                                visit_classes(sub, cls)
                            break

            for child in node.children:
                visit_classes(child, parent_class)

        for node in root_node.children:
            if node.type == 'namespace_declaration':
                # 命名空间内容在 declaration_list 中
                for child in node.children:
                    if child.type == 'declaration_list':
                        for sub in child.children:
                            visit_classes(sub)
                        break
            else:
                visit_classes(node)

    def _extract_functions(self, root_node: Node, source: bytes, module: Module):
        """C# 方法都在类中"""
        pass

    def _extract_variables(self, root_node: Node, source: bytes, module: Module):
        """提取字段变量"""
        pass

    def _parse_class(self, node: Node, source: bytes) -> Optional[ClassDef]:
        """解析类定义"""
        # 找类名 - 在子节点中找 identifier 类型
        name_node = None
        for child in node.children:
            if child.type == 'identifier':
                name_node = child
                break
        if not name_node:
            return None

        name = self._get_node_text(name_node, source)

        # 基类
        bases = []
        for child in node.children:
            if child.type == 'base_list':
                for sub in child.children:
                    if sub.type in ['identifier', 'qualified_name']:
                        bases.append(self._get_node_text(sub, source))
                break

        # 修饰符
        modifiers = []
        for child in node.children:
            if child.type == 'modifier':
                modifiers.append(self._get_node_text(child, source))

        # 提取方法和字段 - 找 declaration_list
        methods = []
        attributes = []
        for child in node.children:
            if child.type == 'declaration_list':
                for sub in child.children:
                    if sub.type == 'method_declaration':
                        method = self._parse_method(sub, source)
                        if method:
                            methods.append(method)
                    elif sub.type == 'constructor_declaration':
                        method = self._parse_method(sub, source)
                        if method:
                            methods.append(method)
                    elif sub.type == 'field_declaration':
                        self._extract_field(sub, source, attributes)
                break

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
        # 找方法名和返回类型
        # 规则: 方法名是 parameter_list 之前的最后一个 identifier
        #       返回类型是方法名之前的类型节点
        name_node = None
        return_type = ""
        before_params = True

        for child in node.children:
            if child.type == 'parameter_list':
                before_params = False
            if before_params:
                if child.type == 'identifier':
                    # 如果已经有返回类型了，这个就是方法名
                    if return_type or name_node:
                        # 之前的 name_node 实际上是返回类型
                        if name_node and not return_type:
                            return_type = self._get_node_text(name_node, source)
                        name_node = child
                    else:
                        # 暂存，可能是返回类型也可能是方法名（void 方法）
                        name_node = child
                elif child.type in ['generic_name', 'qualified_name', 'predefined_type']:
                    return_type = self._get_node_text(child, source)

        if not name_node:
            return None

        name = self._get_node_text(name_node, source)

        # 参数 - 找 parameter_list
        params = []
        for child in node.children:
            if child.type == 'parameter_list':
                for sub in child.children:
                    if sub.type == 'parameter':
                        param_name = ""
                        type_hint = ""
                        for p_sub in sub.children:
                            if p_sub.type == 'identifier':
                                param_name = self._get_node_text(p_sub, source)
                            elif p_sub.type in ['identifier', 'predefined_type', 'generic_name', 'qualified_name']:
                                type_hint = self._get_node_text(p_sub, source)
                        if param_name:
                            params.append(Parameter(name=param_name, type_hint=type_hint))
                break

        # 修饰符
        modifiers = []
        is_static = False
        is_private = False
        for child in node.children:
            if child.type == 'modifier':
                mod_text = self._get_node_text(child, source)
                modifiers.append(mod_text)
                if mod_text == 'static':
                    is_static = True
                if mod_text == 'private':
                    is_private = True

        # 调用关系 - 找 block
        calls = []
        for child in node.children:
            if child.type == 'block':
                calls = self.find_calls(child, source)
                break

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

    def _extract_field(self, node: Node, source: bytes, var_list: list):
        """提取字段"""
        var_type = ""
        for child in node.children:
            if child.type in ['identifier', 'predefined_type', 'generic_name']:
                var_type = self._get_node_text(child, source)
            elif child.type == 'variable_declarator':
                name_node = child.child_by_field_name('name')
                if name_node:
                    var_name = self._get_node_text(name_node, source)
                    var_list.append(VariableDef(
                        name=var_name,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        type_hint=var_type
                    ))

    def _find_calls_recursive(self, node: Node, source: bytes, calls: List[str]):
        """递归查找函数调用 - C# 中是 invocation_expression"""
        if node.type == 'invocation_expression':
            func_name = self._extract_call_name(node, source)
            if func_name:
                calls.append(func_name)

        for child in node.children:
            self._find_calls_recursive(child, source, calls)

    def _extract_call_name(self, node: Node, source: bytes) -> Optional[str]:
        """从调用表达式中提取函数名"""
        # 查找 expression 字段，里面可能是 identifier 或 member_access_expression
        for child in node.children:
            if child.type == 'identifier':
                return self._get_node_text(child, source)
            elif child.type == 'member_access_expression':
                # 在 member_access_expression 中找最后一个 identifier（方法名）
                last_id = None
                for sub in child.children:
                    if sub.type == 'identifier':
                        last_id = sub
                if last_id:
                    return self._get_node_text(last_id, source)
        return None
