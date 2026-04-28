from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Any
from enum import Enum


class Language(Enum):
    """支持的编程语言"""
    PYTHON = "python"
    JAVA = "java"
    CSHARP = "csharp"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    UNKNOWN = "unknown"


@dataclass
class CodeElement:
    """代码元素基类"""
    name: str
    start_line: int
    end_line: int
    content: str = ""
    docstring: str = ""
    summary: str = ""  # LLM 生成的摘要


@dataclass
class VariableDef(CodeElement):
    """变量定义"""
    type_hint: str = ""
    is_global: bool = False


@dataclass
class Parameter:
    """函数参数"""
    name: str
    type_hint: str = ""
    default_value: str = ""


@dataclass
class FunctionDef(CodeElement):
    """函数定义"""
    parameters: List[Parameter] = field(default_factory=list)
    return_type: str = ""
    is_async: bool = False
    is_static: bool = False
    is_private: bool = False
    decorators: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)  # 调用的函数列表
    called_by: List[str] = field(default_factory=list)  # 被哪些函数调用
    modifiers: List[str] = field(default_factory=list)  # public/private/protected 等


@dataclass
class ClassDef(CodeElement):
    """类定义"""
    bases: List[str] = field(default_factory=list)  # 父类
    methods: List[FunctionDef] = field(default_factory=list)
    attributes: List[VariableDef] = field(default_factory=list)
    nested_classes: List['ClassDef'] = field(default_factory=list)
    modifiers: List[str] = field(default_factory=list)


@dataclass
class Import:
    """导入语句"""
    module: str
    alias: str = ""
    names: List[str] = field(default_factory=list)  # from X import a, b, c 中的 a, b, c
    is_relative: bool = False


@dataclass
class Module:
    """模块（文件）"""
    file_path: Path
    language: Language
    relative_path: str = ""
    size: int = 0
    line_count: int = 0

    imports: List[Import] = field(default_factory=list)
    functions: List[FunctionDef] = field(default_factory=list)
    classes: List[ClassDef] = field(default_factory=list)
    variables: List[VariableDef] = field(default_factory=list)

    summary: str = ""  # 模块摘要
    business_logic: str = ""  # 业务逻辑分析

    # 依赖关系
    depends_on: List[str] = field(default_factory=list)  # 依赖的模块
    depended_by: List[str] = field(default_factory=list)  # 被哪些模块依赖


@dataclass
class Project:
    """整个项目"""
    root_path: Path
    name: str = ""
    total_files: int = 0
    total_lines: int = 0

    modules: List[Module] = field(default_factory=list)
    language_stats: Dict[Language, int] = field(default_factory=dict)

    # 分析结果
    architecture_summary: str = ""
    business_overview: str = ""
    core_modules: List[str] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)

    # 调用图
    call_graph: Optional[Any] = None  # networkx Graph

    def get_module_by_path(self, path: str) -> Optional[Module]:
        """根据路径获取模块"""
        for module in self.modules:
            if str(module.file_path) == path or module.relative_path == path:
                return module
        return None

    def get_all_functions(self) -> List[FunctionDef]:
        """获取所有函数（包括类方法）"""
        all_funcs = []
        for module in self.modules:
            all_funcs.extend(module.functions)
            for cls in module.classes:
                all_funcs.extend(cls.methods)
        return all_funcs

    def get_all_classes(self) -> List[ClassDef]:
        """获取所有类"""
        all_classes = []
        for module in self.modules:
            all_classes.extend(module.classes)
            for cls in module.classes:
                all_classes.extend(cls.nested_classes)
        return all_classes
