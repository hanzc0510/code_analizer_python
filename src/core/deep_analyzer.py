"""
深度代码分析引擎 v1
- 智能上下文感知：分析方法时自动检索依赖
- 模型自主决策：让 LLM 自己决定要看什么代码
- 本地持久化缓存：分析结果存本地，优先复用
- 增量更新：代码变了自动重分析
- 聊天纠正：支持人工引导修正分析结果
"""
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import re
import json
import sqlite3
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple, Any
from dataclasses import dataclass, asdict
from collections import defaultdict

from ..models.project import Project, Module, ClassDef, FunctionDef
from ..utils.logger import get_logger
from .code_rag import CodeRAG, CodeSnippet


logger = get_logger()


@dataclass
class AnalysisResult:
    """分析结果（可持久化）"""
    target_type: str  # "function", "class", "module"
    target_name: str
    file_path: str
    start_line: int
    end_line: int

    # 核心分析内容
    summary: str = ""  # 一句话总结
    purpose: str = ""  # 用途/职责
    flow: str = ""  # 执行流程
    dependencies: List[str] = None  # 依赖的外部组件
    side_effects: List[str] = None  # 副作用
    performance_notes: str = ""  # 性能注意点
    edge_cases: List[str] = None  # 边界情况
    security_notes: str = ""  # 安全风险
    improvements: List[str] = None  # 具体改进建议

    # 上下文信息
    context_used: List[Dict] = None  # 实际用了哪些代码片段
    token_usage: Dict = None  # Token 消耗

    # 元数据
    analysis_version: str = "1.0"
    created_at: str = ""
    updated_at: str = ""
    code_hash: str = ""  # 代码哈希，用于检测变更
    manually_corrected: bool = False  # 是否被人工纠正过

    def __post_init__(self):
        for field in ['dependencies', 'side_effects', 'edge_cases', 'improvements', 'context_used', 'token_usage']:
            if getattr(self, field) is None:
                setattr(self, field, [])


class DeepAnalyzer:
    """深度代码分析引擎"""

    def __init__(self, project: Project, llm_client, db_path: str):
        self.project = project
        self.llm = llm_client
        self.db_path = db_path
        self.rag = CodeRAG(db_path)
        self._init_cache_db()

        # 方法调用图（快速查找）
        self._call_graph_index = self._build_call_graph_index()

    def _init_cache_db(self):
        """初始化缓存数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deep_analysis_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_type TEXT NOT NULL,
                target_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                start_line INTEGER,
                end_line INTEGER,
                code_hash TEXT NOT NULL,
                result_json TEXT NOT NULL,
                manually_corrected INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(target_type, target_name, file_path)
            )
        """)

        # 聊天历史表（用于纠正对话）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(analysis_id) REFERENCES deep_analysis_cache(id)
            )
        """)

        conn.commit()
        conn.close()

    def _build_call_graph_index(self) -> Dict[str, Set[str]]:
        """构建方法调用索引，快速查找相关方法"""
        index = defaultdict(set)

        # 仅当 project 存在时构建索引（列表查询场景不需要）
        if self.project:
            for module in self.project.modules:
                for func in module.functions:
                    if func.calls:
                        for called in func.calls:
                            index[func.name].add(called)
                            index[called].add(func.name)  # 双向关联

                for cls in module.classes:
                    for method in cls.methods:
                        full_name = f"{cls.name}.{method.name}"
                        if method.calls:
                            for called in method.calls:
                                index[full_name].add(called)
                                index[called].add(full_name)

        return dict(index)

    def _compute_code_hash(self, code: str) -> str:
        """计算代码哈希，用于检测变更"""
        # 标准化：移除空格、换行、注释
        normalized = re.sub(r'\s+', '', code)
        normalized = re.sub(r'//.*?\n', '', normalized)
        normalized = re.sub(r'/\*.*?\*/', '', normalized)
        return hashlib.md5(normalized.encode('utf-8')).hexdigest()

    def _get_cached_analysis(self, target_type: str, target_name: str,
                              file_path: str, code_hash: str) -> Optional[AnalysisResult]:
        """获取缓存的分析结果（代码没变且没被纠正过就复用）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Normalize path separator: convert backslashes to forward slashes in DB
        cursor.execute("""
            SELECT result_json, code_hash, manually_corrected
            FROM deep_analysis_cache
            WHERE target_type = ? AND target_name = ?
              AND REPLACE(file_path, '\\', '/') = ?
            ORDER BY updated_at DESC
            LIMIT 1
        """, (target_type, target_name, file_path.replace("\\", "/")))

        row = cursor.fetchone()
        conn.close()

        if row:
            cached_hash = row[1]
            manually_corrected = bool(row[2])

            # 如果被人工纠正过，或者代码没变 -> 直接复用
            if manually_corrected or cached_hash == code_hash:
                data = json.loads(row[0])
                return AnalysisResult(**data)

        return None

    def _save_analysis(self, result: AnalysisResult):
        """保存分析结果到缓存"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO deep_analysis_cache
                (target_type, target_name, file_path, start_line, end_line,
                 code_hash, result_json, manually_corrected, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                result.target_type,
                result.target_name,
                result.file_path.replace("\\", "/"),  # Normalize to forward slashes
                result.start_line,
                result.end_line,
                result.code_hash,
                json.dumps(asdict(result), ensure_ascii=False),
                1 if result.manually_corrected else 0
            ))
            conn.commit()
        except Exception as e:
            logger.warning(f"Failed to save analysis cache: {e}")
        finally:
            conn.close()

    def _get_smart_context(self, func: FunctionDef, cls_name: str = None,
                           max_snippets: int = 20) -> List[CodeSnippet]:
        """智能获取上下文：让模型需要的都能拿到
        优先级：
        1. 方法自身 + 完整代码
        2. 直接调用的方法（完整代码）
        3. 调用这个方法的其他方法（反向调用）
        4. 同个类的其他方法（代码+签名）
        5. 父类/接口定义
        6. 同模块其他相关类
        7. RAG 检索相关代码
        """
        snippets = []

        func_name = f"{cls_name}.{func.name}" if cls_name else func.name

        # ========== 1. 方法自身（完整代码） ==========
        if func.content:
            snippets.append(CodeSnippet(
                type="function",
                name=func_name,
                file_path="",
                start_line=func.start_line,
                end_line=func.end_line,
                content=func.content,
                signature=self._get_func_signature(func),
                relevance=100.0
            ))

        # ========== 2. 直接调用的方法（完整代码） ==========
        if func.calls:
            for called in list(func.calls)[:10]:
                called_func = self._find_function(called)
                if called_func:
                    snippets.append(CodeSnippet(
                        type="function",
                        name=called,
                        file_path=called_func.get('file', ''),
                        start_line=called_func.get('start_line', 0),
                        end_line=called_func.get('end_line', 0),
                        content=called_func.get('content', '')[:4000],
                        signature=called_func.get('signature', ''),
                        relevance=85.0
                    ))

        # ========== 3. 调用这个方法的其他方法（反向调用） ==========
        reverse_callers = self._find_callers(func_name)
        for caller_name, caller_info in list(reverse_callers.items())[:6]:
            snippets.append(CodeSnippet(
                type="function",
                name=caller_name,
                file_path=caller_info.get('file', ''),
                start_line=caller_info.get('start_line', 0),
                end_line=caller_info.get('end_line', 0),
                content=f"// 调用了 {func_name} 的方法\n{caller_info.get('content', '')[:3000]}",
                signature=caller_info.get('signature', ''),
                relevance=75.0
            ))

        # ========== 4. 同个类的其他方法（如果是类方法） ==========
        if cls_name:
            parent_cls = self._find_class(cls_name)
            if parent_cls:
                for method in parent_cls.methods[:12]:
                    if method.name != func.name:
                        sig = self._get_func_signature(method)
                        snippets.append(CodeSnippet(
                            type="function",
                            name=f"{cls_name}.{method.name}",
                            file_path="",
                            start_line=method.start_line,
                            end_line=method.end_line,
                            content=f"// {cls_name}.{method.name}\n{method.content[:2000]}" if method.content else sig,
                            signature=sig,
                            relevance=65.0
                        ))

                # 4.1 父类/基类定义（理解继承关系）
                for base_name in parent_cls.bases[:3]:
                    base_cls = self._find_class(base_name)
                    if base_cls:
                        snippets.append(CodeSnippet(
                            type="class",
                            name=base_name,
                            file_path="",
                            start_line=base_cls.start_line,
                            end_line=base_cls.end_line,
                            content=f"// 父类 {base_name} 定义\n" +
                                    "\n".join([self._get_func_signature(m) for m in base_cls.methods[:10]]),
                            signature="",
                            relevance=70.0
                        ))

        # ========== 4. RAG 检索相关代码 ==========
        rag_results = self.rag.search(func_name + " " + (func.content or ""),
                                        max_results=10, max_tokens=5000)
        for r in rag_results:
            if r.name != func_name:  # 排除自己
                r.relevance = r.relevance * 0.5  # 降低权重
                snippets.append(r)

        # ========== 5. 去重 + 按相关性排序 ==========
        seen = set()
        unique_snippets = []
        for s in snippets:
            key = f"{s.type}:{s.name}"
            if key not in seen and len(unique_snippets) < max_snippets:
                seen.add(key)
                unique_snippets.append(s)

        return sorted(unique_snippets, key=lambda x: -x.relevance)

    def _get_func_signature(self, func: FunctionDef) -> str:
        params = ', '.join(f"{p.type_hint or 'object'} {p.name}" for p in func.parameters)
        mods = ' '.join(func.modifiers) + ' ' if func.modifiers else ''
        return f"{mods}{func.return_type or 'void'} {func.name}({params})"

    def _find_function(self, name: str) -> Optional[Dict]:
        """查找函数（支持带类名的格式）"""
        parts = name.split('.') if '.' in name else [name]
        search_name = parts[-1]

        for module in self.project.modules:
            # 模块级函数
            for func in module.functions:
                if func.name == search_name:
                    return {
                        'file': module.relative_path,
                        'start_line': func.start_line,
                        'end_line': func.end_line,
                        'content': func.content,
                        'signature': self._get_func_signature(func)
                    }
            # 类方法
            for cls in module.classes:
                if len(parts) > 1 and cls.name == parts[0]:
                    for method in cls.methods:
                        if method.name == search_name:
                            return {
                                'file': module.relative_path,
                                'start_line': method.start_line,
                                'end_line': method.end_line,
                                'content': method.content,
                                'signature': self._get_func_signature(method)
                            }
                else:
                    for method in cls.methods:
                        if method.name == search_name:
                            return {
                                'file': module.relative_path,
                                'start_line': method.start_line,
                                'end_line': method.end_line,
                                'content': method.content,
                                'signature': self._get_func_signature(method)
                            }
        return None

    def _find_class(self, name: str) -> Optional[ClassDef]:
        """查找类"""
        for module in self.project.modules:
            for cls in module.classes:
                if cls.name == name:
                    return cls
        return None

    def _find_callers(self, target_func_name: str) -> Dict[str, Dict]:
        """查找所有调用了目标函数的方法/函数
        返回: {调用者名称: {file, start_line, end_line, content, signature}}
        """
        callers = {}
        search_name = target_func_name.split('.')[-1] if '.' in target_func_name else target_func_name

        for module in self.project.modules:
            # 检查模块级函数
            for func in module.functions:
                if func.calls and search_name in func.calls:
                    full_name = func.name
                    callers[full_name] = {
                        'file': module.relative_path,
                        'start_line': func.start_line,
                        'end_line': func.end_line,
                        'content': func.content,
                        'signature': self._get_func_signature(func)
                    }

            # 检查类方法
            for cls in module.classes:
                for method in cls.methods:
                    if method.calls and search_name in method.calls:
                        full_name = f"{cls.name}.{method.name}"
                        if full_name != target_func_name:  # 排除递归调用自己
                            callers[full_name] = {
                                'file': module.relative_path,
                                'start_line': method.start_line,
                                'end_line': method.end_line,
                                'content': method.content,
                                'signature': self._get_func_signature(method)
                            }

        return callers

    async def analyze_function(self, func: FunctionDef, class_name: str = None,
                               module_path: str = "", force_refresh: bool = False,
                               additional_context: str = "") -> AnalysisResult:
        """
        深度分析单个函数（智能上下文 + 缓存）

        Args:
            func: 函数对象
            class_name: 如果是类方法，传类名
            module_path: 所在模块路径
            force_refresh: 强制刷新，不走缓存
            additional_context: 额外的人工引导/纠正信息

        Returns:
            AnalysisResult 分析结果
        """
        full_name = f"{class_name}.{func.name}" if class_name else func.name
        code_hash = self._compute_code_hash(func.content or full_name)

        # 先查缓存
        if not force_refresh:
            cached = self._get_cached_analysis("function", full_name, module_path, code_hash)
            if cached:
                logger.info(f"[OK] Using cached analysis for: {full_name}")
                return cached

        logger.info(f"[Search] Deep analyzing function: {full_name}")

        # ========== 智能获取上下文 ==========
        context_snippets = self._get_smart_context(func, class_name)
        logger.info(f"   Collected {len(context_snippets)} context snippets")

        # ========== 构建 Prompt ==========
        context_text = self._format_context(context_snippets)

        system_prompt = """你是一位世界级的代码架构师和代码审计专家。请深度分析这段代码并给出可执行的优化建议。

分析要求：
1. 准确理解代码的真实意图和业务逻辑
2. 分析执行流程，识别关键决策点和数据流转
3. 识别所有外部依赖、副作用和隐藏耦合
4. 找出潜在的 bug、边界情况、性能瓶颈
5. 【重要】给出具体的改进建议，包含：
   - 每个建议必须说明问题所在和改进收益
   - 尽可能提供重构后的代码示例（使用正确的语法）
   - 指出涉及的相关文件或依赖项
   - 按优先级排序：高(立即修复) > 中(建议优化) > 低(后续考虑)

输出格式（严格 JSON，不要其他文字）：
{
  "summary": "一句话总结这个函数的核心作用",
  "purpose": "详细说明这个函数的用途和职责",
  "flow": "执行流程分析，分点说明关键步骤和决策逻辑",
  "dependencies": ["依赖1", "依赖2", "外部系统/库/其他类"],
  "side_effects": ["副作用1", "副作用2", "修改数据库/发请求/改全局状态等"],
  "performance_notes": "性能分析和注意点（时间复杂度、内存、IO等）",
  "edge_cases": ["边界情况1", "边界情况2", "可能出问题的地方"],
  "security_notes": "安全风险分析（SQL注入、XSS、权限、空指针等）",
  "improvements": [
    "【高】问题描述：xxx，建议：xxx，相关文件：xxx",
    "【中】问题描述：xxx，代码示例：xxx"
  ]
}"""

        user_prompt = f"""
【待分析函数】
{full_name}
文件: {module_path}
行号: {func.start_line}-{func.end_line}

【函数完整代码】
```
{func.content or "(code unavailable)"}
```

【相关上下文（供参考）】
{context_text}

【额外引导信息】
{additional_context or "无"}

请按要求的 JSON 格式输出深度分析结果。
"""

        # ========== 调用 LLM ==========
        result = await self.llm._call_llm(user_prompt, system_prompt)

        # ========== 解析结果 ==========
        import json
        try:
            if "```json" in result:
                start = result.find("```json") + 7
                end = result.find("```", start)
                result = result[start:end].strip()
            elif "{" in result:
                start = result.find("{")
                end = result.rfind("}") + 1
                result = result[start:end]

            parsed = json.loads(result)
        except Exception as e:
            logger.warning(f"Failed to parse LLM result: {e}, falling back to raw")
            parsed = {
                "summary": result[:200],
                "purpose": result,
                "flow": "",
                "dependencies": [],
                "side_effects": [],
                "performance_notes": "",
                "edge_cases": [],
                "security_notes": ""
            }

        # ========== 构建结果 ==========
        analysis = AnalysisResult(
            target_type="function",
            target_name=full_name,
            file_path=module_path,
            start_line=func.start_line,
            end_line=func.end_line,
            summary=parsed.get("summary", ""),
            purpose=parsed.get("purpose", ""),
            flow=parsed.get("flow", ""),
            dependencies=parsed.get("dependencies", []),
            side_effects=parsed.get("side_effects", []),
            performance_notes=parsed.get("performance_notes", ""),
            edge_cases=parsed.get("edge_cases", []),
            security_notes=parsed.get("security_notes", ""),
            improvements=parsed.get("improvements", []),
            context_used=[
                {"type": s.type, "name": s.name, "relevance": s.relevance}
                for s in context_snippets
            ],
            code_hash=code_hash,
            manually_corrected=bool(additional_context)
        )

        # ========== 保存到缓存 ==========
        self._save_analysis(analysis)
        logger.info(f"[OK] Analysis complete for: {full_name}")

        return analysis

    async def analyze_class(self, cls: ClassDef, module_path: str = "",
                            force_refresh: bool = False,
                            additional_context: str = "") -> AnalysisResult:
        """深度分析类"""
        code_hash = self._compute_code_hash(
            ''.join(m.content or m.name for m in cls.methods) + cls.name
        )

        # 查缓存
        if not force_refresh:
            cached = self._get_cached_analysis("class", cls.name, module_path, code_hash)
            if cached:
                logger.info(f"[OK] Using cached analysis for class: {cls.name}")
                return cached

        logger.info(f"[Search] Deep analyzing class: {cls.name}")

        # ========== 构建上下文 ==========
        # 1. 类的所有方法（带代码）
        methods_text = ""
        for method in cls.methods:
            sig = self._get_func_signature(method)
            methods_text += f"\n--- {method.name} ---\n"
            methods_text += f"Signature: {sig}\n"
            if method.content and len(method.content) < 3000:
                methods_text += f"Code:\n{method.content}\n"
            else:
                methods_text += f"Lines: {method.end_line - method.start_line}\n"

        # 2. 父类和基类信息
        base_classes_text = ""
        for base_name in cls.bases[:5]:
            base_cls = self._find_class(base_name)
            if base_cls:
                base_classes_text += f"\n=== 父类 {base_name} ===\n"
                base_classes_text += f"Methods: {', '.join([m.name for m in base_cls.methods[:10]])}\n"

        # 3. 子类和相关类
        related_classes_text = ""
        for module in self.project.modules:
            for other_cls in module.classes[:5]:
                if other_cls.name != cls.name and cls.name in other_cls.bases:
                    related_classes_text += f"\n=== 子类 {other_cls.name} ===\n"
                    related_classes_text += f"Methods: {', '.join([m.name for m in other_cls.methods[:8]])}\n"

        system_prompt = """你是一位世界级的代码架构师。请深度分析这个类的设计和实现，并给出具体改进建议。

分析要求：
1. 评估类的单一职责原则，指出职责过多的地方
2. 分析类的依赖关系，识别不合理的耦合
3. 评估继承关系和接口设计的合理性
4. 找出潜在的性能问题和可维护性问题
5. 【重要】给出具体的改进建议，包含：
   - 每个建议必须说明：问题描述、改进收益、重构难度
   - 尽可能提供重构后的代码示例
   - 指出涉及的相关文件或依赖项
   - 按优先级排序：高(立即修复) > 中(建议优化) > 低(后续考虑)

输出格式（严格 JSON）：
{
  "summary": "一句话总结类的核心作用",
  "purpose": "详细说明这个类的业务职责和在系统中的定位",
  "flow": "核心执行流程（如果是生命周期类，说明各个阶段）",
  "dependencies": ["依赖的类", "依赖的外部系统", "依赖的库"],
  "design_patterns": ["使用的设计模式1", "模式2"],
  "strengths": ["设计优点1", "优点2"],
  "weaknesses": ["设计缺陷1", "潜在问题2"],
  "side_effects": ["副作用列表"],
  "performance_notes": "性能相关分析",
  "security_notes": "安全风险分析",
  "improvements": [
    "【高】问题描述：xxx，建议：xxx，相关文件：xxx",
    "【中】问题描述：xxx，代码示例：xxx"
  ]
}"""

        user_prompt = f"""
【待分析类】
{cls.name}
文件: {module_path}
行号: {cls.start_line}-{cls.end_line}
父类: {', '.join(cls.bases) if cls.bases else '无'}
方法数: {len(cls.methods)}

【类中所有方法】
{methods_text}

【父类/基类信息】
{base_classes_text or "无额外基类信息"}

【子类/相关类信息】
{related_classes_text or "无相关子类信息"}

【额外引导信息】
{additional_context or "无"}

请按要求的 JSON 格式输出深度分析结果。
"""

        result = await self.llm._call_llm(user_prompt, system_prompt)

        # 解析结果
        import json
        try:
            if "```json" in result:
                start = result.find("```json") + 7
                end = result.find("```", start)
                result = result[start:end].strip()
            elif "{" in result:
                start = result.find("{")
                end = result.rfind("}") + 1
                result = result[start:end]

            parsed = json.loads(result)
        except Exception as e:
            logger.warning(f"Failed to parse class analysis: {e}")
            parsed = {"summary": result[:200], "purpose": result}

        analysis = AnalysisResult(
            target_type="class",
            target_name=cls.name,
            file_path=module_path,
            start_line=cls.start_line,
            end_line=cls.end_line,
            summary=parsed.get("summary", ""),
            purpose=parsed.get("purpose", ""),
            flow=parsed.get("flow", ""),
            dependencies=parsed.get("dependencies", []),
            side_effects=parsed.get("side_effects", []),
            performance_notes=parsed.get("performance_notes", ""),
            edge_cases=parsed.get("weaknesses", []),
            security_notes=parsed.get("security_notes", ""),
            improvements=parsed.get("improvements", []),
            code_hash=code_hash,
            manually_corrected=bool(additional_context)
        )

        self._save_analysis(analysis)
        logger.info(f"[OK] Class analysis complete: {cls.name}")

        return analysis

    def _format_context(self, snippets: List[CodeSnippet]) -> str:
        """格式化上下文"""
        if not snippets:
            return "无相关上下文"

        lines = []
        for idx, s in enumerate(snippets, 1):
            lines.append(f"\n=== 相关代码 #{idx}: {s.name} (相关性: {s.relevance:.1f}) ===")
            if s.file_path:
                lines.append(f"文件: {s.file_path}")
            lines.append(f"类型: {s.type}")
            lines.append("")
            lines.append(s.content[:2500] if len(s.content) > 2500 else s.content)
            lines.append("")

        return '\n'.join(lines)

    def get_cached_analysis(self, target_type: str, target_name: str,
                             file_path: str = "") -> Optional[AnalysisResult]:
        """获取缓存的分析结果（外部调用用）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        params = [target_type, target_name]
        query = """
            SELECT result_json, code_hash, manually_corrected
            FROM deep_analysis_cache
            WHERE target_type = ? AND target_name = ?
        """
        if file_path:
            # Normalize path separator: convert backslashes to forward slashes
            query += " AND REPLACE(file_path, '\\', '/') = ?"
            params.append(file_path.replace("\\", "/"))
        query += " ORDER BY updated_at DESC LIMIT 1"

        cursor.execute(query, params)
        row = cursor.fetchone()
        conn.close()

        if row:
            return AnalysisResult(**json.loads(row[0]))
        return None

    def get_all_cached_analyses(self) -> List[Dict]:
        """获取所有缓存的分析结果列表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT target_type, target_name, file_path, updated_at,
                   manually_corrected, json_extract(result_json, '$.summary')
            FROM deep_analysis_cache
            ORDER BY updated_at DESC
        """)

        results = []
        for row in cursor.fetchall():
            results.append({
                "target_type": row[0],
                "target_name": row[1],
                "file_path": row[2],
                "updated_at": row[3],
                "manually_corrected": bool(row[4]),
                "summary": row[5] or ""
            })

        conn.close()
        return results
