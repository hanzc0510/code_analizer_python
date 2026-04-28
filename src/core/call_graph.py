import networkx as nx
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from ..models.project import Project, Module, FunctionDef, ClassDef
from ..utils.logger import get_logger


logger = get_logger()


class CallGraph:
    """调用图构建和分析器"""

    def __init__(self, project: Project):
        self.project = project
        self.graph = nx.DiGraph()
        self._function_map: Dict[str, FunctionDef] = {}
        self._build_function_map()

    def _build_function_map(self):
        """构建函数名到函数对象的映射"""
        for module in self.project.modules:
            module_prefix = module.relative_path

            # 模块级函数
            for func in module.functions:
                full_name = f"{module_prefix}:{func.name}"
                self._function_map[full_name] = func
                self.graph.add_node(full_name, type="function", module=module_prefix)

            # 类方法
            for cls in module.classes:
                for method in cls.methods:
                    full_name = f"{module_prefix}:{cls.name}.{method.name}"
                    self._function_map[full_name] = method
                    self.graph.add_node(full_name, type="method", class_name=cls.name, module=module_prefix)

    def build(self):
        """构建调用图"""
        logger.info("Building call graph...")

        for full_name, func in self._function_map.items():
            for call_name in func.calls:
                # 尝试匹配被调用的函数
                called_funcs = self._find_called_functions(full_name, call_name)
                for target_name in called_funcs:
                    self.graph.add_edge(full_name, target_name, label="calls")
                    # 更新被调用列表
                    if target_name in self._function_map:
                        func.called_by.append(target_name)

        # 构建模块依赖图
        self._build_module_dependencies()

        self.project.call_graph = self.graph
        logger.info(f"Call graph built: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")

    def _find_called_functions(self, caller: str, call_name: str) -> List[str]:
        """根据调用名查找可能的函数"""
        results = []

        # 首先查找同名函数
        for full_name in self._function_map:
            # 提取函数名部分
            if ':' in full_name:
                _, func_part = full_name.split(':', 1)
                if '.' in func_part:
                    _, func_name = func_part.rsplit('.', 1)
                else:
                    func_name = func_part

                if func_name == call_name:
                    results.append(full_name)

        # 如果只有一个匹配，直接返回
        if len(results) == 1:
            return results

        # 如果有多个匹配，优先同模块的
        caller_module = caller.split(':')[0] if ':' in caller else ""
        same_module = [r for r in results if r.startswith(caller_module + ':')]
        if same_module:
            return same_module[:1]  # 取第一个同模块匹配

        return results[:3]  # 最多返回 3 个匹配

    def _build_module_dependencies(self):
        """构建模块依赖关系"""
        for module in self.project.modules:
            # 分析导入
            for imp in module.imports:
                # 查找匹配的模块
                for target in self.project.modules:
                    target_path = target.relative_path.replace('\\', '/').replace('/', '.')
                    if imp.module in target_path or target_path in imp.module:
                        if target.relative_path not in module.depends_on:
                            module.depends_on.append(target.relative_path)
                        if module.relative_path not in target.depended_by:
                            target.depended_by.append(module.relative_path)

    def get_function_callers(self, func_name: str) -> List[str]:
        """获取调用某个函数的所有函数"""
        if func_name in self.graph:
            return list(self.graph.predecessors(func_name))
        return []

    def get_function_callees(self, func_name: str) -> List[str]:
        """获取某个函数调用的所有函数"""
        if func_name in self.graph:
            return list(self.graph.successors(func_name))
        return []

    def get_call_chain(self, start_func: str, max_depth: int = 10) -> Dict:
        """获取从某个函数开始的调用链"""
        if start_func not in self.graph:
            return {}

        chain = {}
        visited = set()

        def dfs(node: str, depth: int):
            if depth > max_depth or node in visited:
                return
            visited.add(node)
            children = list(self.graph.successors(node))
            chain[node] = children
            for child in children:
                dfs(child, depth + 1)

        dfs(start_func, 0)
        return chain

    def find_entry_points(self) -> List[str]:
        """查找入口点（没有被其他函数调用的函数）"""
        entries = []
        for node in self.graph.nodes:
            if self.graph.in_degree(node) == 0:
                entries.append(node)
        return sorted(entries, key=lambda x: self.graph.out_degree(x), reverse=True)

    def get_circular_dependencies(self) -> List[List[str]]:
        """查找循环依赖"""
        try:
            cycles = list(nx.simple_cycles(self.graph))
            return [cycle for cycle in cycles if len(cycle) > 1]
        except:
            return []

    def get_most_called_functions(self, top_n: int = 10) -> List[Tuple[str, int]]:
        """获取被调用最多的函数"""
        in_degrees = [(node, self.graph.in_degree(node)) for node in self.graph.nodes]
        in_degrees.sort(key=lambda x: x[1], reverse=True)
        return in_degrees[:top_n]

    def generate_mermaid_graph(self) -> str:
        """生成 Mermaid 调用图"""
        lines = ["```mermaid", "graph TD"]

        for u, v in self.graph.edges:
            # 简化显示名称
            u_short = u.split(':')[-1].replace('.', '_')
            v_short = v.split(':')[-1].replace('.', '_')
            lines.append(f"    {u_short} --> {v_short}")

        lines.append("```")
        return '\n'.join(lines)

    def get_module_call_graph(self) -> nx.DiGraph:
        """获取模块级别的调用图"""
        module_graph = nx.DiGraph()

        # 添加模块节点
        for module in self.project.modules:
            module_graph.add_node(module.relative_path, type="module")

        # 添加模块间调用边
        for u, v in self.graph.edges:
            u_module = u.split(':')[0] if ':' in u else u
            v_module = v.split(':')[0] if ':' in v else v

            if u_module != v_module and u_module and v_module:
                if module_graph.has_edge(u_module, v_module):
                    module_graph[u_module][v_module]['count'] += 1
                else:
                    module_graph.add_edge(u_module, v_module, count=1)

        return module_graph

    def analyze_architecture(self) -> Dict:
        """分析架构特征"""
        module_graph = self.get_module_call_graph()

        # 计算各模块的入度和出度
        in_degrees = dict(module_graph.in_degree())
        out_degrees = dict(module_graph.out_degree())

        # 核心模块（被很多模块依赖）
        core_modules = sorted(
            [m for m, d in in_degrees.items() if d > 0],
            key=lambda x: in_degrees[x],
            reverse=True
        )

        # 入口模块（依赖很多其他模块）
        entry_modules = sorted(
            [m for m, d in out_degrees.items() if d > 0],
            key=lambda x: out_degrees[x],
            reverse=True
        )

        # 独立模块（没有依赖）
        independent_modules = [
            m for m in module_graph.nodes
            if in_degrees.get(m, 0) == 0 and out_degrees.get(m, 0) == 0
        ]

        return {
            "total_modules": module_graph.number_of_nodes(),
            "module_dependencies": module_graph.number_of_edges(),
            "core_modules": core_modules[:10],
            "entry_modules": entry_modules[:10],
            "independent_modules": independent_modules[:10],
            "circular_dependencies": self.get_circular_dependencies(),
        }
