"""
代码 RAG 检索引擎 v2
- 混合检索：语义相似度 + 关键词匹配 + 结构权重
- 分层召回：先粗筛，再精排
- 代码理解优先，最小化无关片段
"""
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import re
import sqlite3
import hashlib
import json
import math
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass
from collections import defaultdict

from ..models.project import Module, ClassDef, FunctionDef


@dataclass
class CodeSnippet:
    """代码片段"""
    type: str  # class, function, module
    name: str
    file_path: str
    start_line: int
    end_line: int
    content: str
    signature: str  # 精简签名，无实现代码
    summary: str = ""
    relevance: float = 0.0
    match_reason: str = ""  # 匹配原因说明


class CodeRAG:
    """代码检索引擎 v2"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_tables()

        # 语义扩展：用户常见提问词 -> 代码概念词
        self.semantic_map = {
            # ========== 数据库/持久化 ==========
            "数据库": {"db", "database", "sql", "connection", "session", "transaction", "repo", "mapper"},
            "db": {"db", "database", "sql", "connection", "session"},
            "连接": {"connection", "connect", "open", "session", "pool"},
            "事务": {"transaction", "commit", "rollback", "begin", "tx"},
            "持久化": {"save", "persist", "insert", "update", "delete", "flush"},
            "查询": {"query", "select", "find", "search", "get", "list"},

            # ========== 分页/列表 ==========
            "分页": {"page", "pagelist", "paging", "pagination", "pageable", "limit", "offset", "pager", "rowbound", "pagehelper", "pagerequest"},
            "列表": {"list", "page", "pagelist", "array", "collection", "result"},
            "page": {"page", "pagelist", "pagination", "pageable", "pager"},

            # ========== 缓存相关 ==========
            "缓存": {"cache", "redis", "memcached", "expire", "evict", "put", "get"},
            "redis": {"redis", "cache", "jedis", "letture"},

            # ========== 配置相关 ==========
            "配置": {"config", "setting", "properties", "yaml", "env", "option"},
            "配置文件": {"config", "setting", "properties", "yaml"},

            # ========== 初始化/启动 ==========
            "启动": {"start", "run", "init", "bootstrap", "boot", "launch", "main"},
            "初始化": {"init", "initialize", "setup", "prepare", "bootstrap"},
            "入口": {"main", "entry", "start", "run", "bootstrap"},

            # ========== 并发/异步 ==========
            "异步": {"async", "await", "future", "promise", "coroutine", "thread"},
            "线程": {"thread", "pool", "executor", "runasync"},
            "并发": {"concurrent", "parallel", "thread", "lock", "atomic"},

            # ========== 设计模式 ==========
            "工厂": {"factory", "builder", "create", "build", "produce"},
            "单例": {"singleton", "instance", "getinstance"},
            "代理": {"proxy", "delegate", "wrapper"},
            "策略": {"strategy", "policy", "algorithm"},
            "观察者": {"observer", "listener", "event", "subscribe", "notify"},

            # ========== 异常处理 ==========
            "异常": {"exception", "error", "throw", "catch", "try", "handle"},
            "错误": {"error", "exception", "fail", "fault"},

            # ========== 网络/API ==========
            "接口": {"api", "controller", "rest", "endpoint", "route"},
            "请求": {"request", "http", "get", "post", "call", "invoke"},
            "响应": {"response", "result", "reply", "return"},

            # ========== 数据处理 ==========
            "解析": {"parse", "decode", "encode", "serialize", "deserialize"},
            "转换": {"convert", "transform", "map", "adapt"},
            "校验": {"validate", "check", "verify", "assert"},

            # ========== 日志/监控 ==========
            "日志": {"log", "logger", "info", "debug", "warn", "error"},
            "监控": {"monitor", "metric", "health", "check", "stat"},
        }

        # 停止词（太通用，匹配了也没意义）
        self.stop_words = {
            "get", "set", "is", "to", "string", "int", "bool", "public", "private",
            "return", "new", "this", "super", "class", "interface", "extends",
            "implements", "void", "final", "static", "import", "package",
            "throw", "catch", "try", "if", "else", "for", "while", "switch",
            "case", "break", "continue", "default", "do", "null", "true", "false"
        }

        # 类型权重
        self.type_weights = {
            "class": 2.0,      # 类最有价值
            "function": 1.5,   # 方法次之
            "module": 1.0      # 模块最后
        }

    def _init_tables(self):
        """初始化索引表（含自动迁移）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 1. 创建表（如果不存在）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS code_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                start_line INTEGER,
                end_line INTEGER,
                signature TEXT NOT NULL,
                content_hash TEXT UNIQUE NOT NULL,
                tokens INTEGER DEFAULT 0,
                keywords TEXT,  -- JSON 关键词列表
                concept_tags TEXT  -- JSON 概念标签（自动提取）
            )
        """)

        # 2. 检查并迁移旧数据库：添加 concept_tags 列
        cursor.execute("PRAGMA table_info(code_index)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'concept_tags' not in columns:
            print("[INFO] 迁移数据库：添加 concept_tags 列...")
            cursor.execute("ALTER TABLE code_index ADD COLUMN concept_tags TEXT")
            print("[WARN] 重要提示：旧项目需要重新分析才能获得更好的 RAG 检索效果！")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_summary (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    def _extract_concept_tags(self, name: str, signature: str, type: str) -> List[str]:
        """提取代码的概念标签（用于语义匹配）"""
        tags = set()
        text = (name + " " + signature).lower()

        # 简单的概念识别
        if any(w in text for w in ["db", "database", "sql", "jdbc", "mybatis"]):
            tags.add("database")
        if any(w in text for w in ["cache", "redis", "caffeine"]):
            tags.add("cache")
        if any(w in text for w in ["http", "request", "response", "api", "rest"]):
            tags.add("api")
        if any(w in text for w in ["config", "setting", "properties"]):
            tags.add("config")
        if any(w in text for w in ["async", "future", "thread", "pool"]):
            tags.add("async")
        if any(w in text for w in ["log", "logger", "logging"]):
            tags.add("log")
        if any(w in text for w in ["transaction", "commit", "rollback"]):
            tags.add("transaction")
        if any(w in text for w in ["factory", "builder", "create", "build"]):
            tags.add("factory")
        if type == "class" and "exception" in name.lower() or "error" in name.lower():
            tags.add("exception")

        return list(tags)

    def index_project(self, modules: List[Module]):
        """索引整个项目"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        snippets = []

        for module in modules:
            # 模块级
            mod_sig = self._extract_module_signature(module)
            snippets.append(CodeSnippet(
                type="module",
                name=module.relative_path,
                file_path=module.relative_path,
                start_line=0,
                end_line=module.line_count,
                content=mod_sig,
                signature=mod_sig
            ))

            # 类
            for cls in module.classes:
                cls_sig = self._extract_class_signature(cls)
                snippets.append(CodeSnippet(
                    type="class",
                    name=cls.name,
                    file_path=module.relative_path,
                    start_line=cls.start_line,
                    end_line=cls.end_line,
                    content=cls_sig,
                    signature=cls_sig
                ))

                # 方法
                for func in cls.methods:
                    func_sig = self._extract_function_signature(func)
                    snippets.append(CodeSnippet(
                        type="function",
                        name=f"{cls.name}.{func.name}",
                        file_path=module.relative_path,
                        start_line=func.start_line,
                        end_line=func.end_line,
                        content=func_sig,
                        signature=func_sig
                    ))

            # 模块级函数
            for func in module.functions:
                func_sig = self._extract_function_signature(func)
                snippets.append(CodeSnippet(
                    type="function",
                    name=func.name,
                    file_path=module.relative_path,
                    start_line=func.start_line,
                    end_line=func.end_line,
                    content=func_sig,
                    signature=func_sig
                ))

        # 保存到数据库
        for snip in snippets:
            content_hash = hashlib.md5(f"{snip.file_path}:{snip.name}".encode()).hexdigest()
            keywords = self._extract_keywords(snip.signature)
            concept_tags = self._extract_concept_tags(snip.name, snip.signature, snip.type)
            tokens = self._estimate_tokens(snip.signature)

            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO code_index
                    (type, name, file_path, start_line, end_line, signature,
                     content_hash, tokens, keywords, concept_tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    snip.type, snip.name, snip.file_path, snip.start_line, snip.end_line,
                    snip.signature, content_hash, tokens, json.dumps(keywords), json.dumps(concept_tags)
                ))
            except Exception:
                pass

        self._generate_project_summary(modules, cursor)

        conn.commit()
        conn.close()

        return len(snippets)

    def _extract_module_signature(self, module: Module) -> str:
        lines = [f"// Module: {module.relative_path}"]
        lines.append(f"// Classes: {len(module.classes)}, Functions: {len(module.functions)}")

        for cls in module.classes:
            lines.append(f"//   class {cls.name} ({len(cls.methods)} methods)")

        for func in module.functions:
            params = ', '.join(p.name for p in func.parameters[:3])
            if len(func.parameters) > 3:
                params += ", ..."
            lines.append(f"//   {func.return_type} {func.name}({params})")

        return '\n'.join(lines)

    def _extract_class_signature(self, cls: ClassDef) -> str:
        lines = [f"class {cls.name} {{"]

        for method in cls.methods[:15]:
            params = ', '.join(f"{p.name}" for p in method.parameters[:5])
            if len(method.parameters) > 5:
                params += ", ..."
            ret_type = method.return_type or "void"
            mods = ' '.join(method.modifiers) if method.modifiers else ""
            lines.append(f"  {mods} {ret_type} {method.name}({params});")

        if len(cls.methods) > 15:
            lines.append(f"  // ... and {len(cls.methods) - 15} more methods")

        lines.append("}")
        return '\n'.join(lines)

    def _extract_function_signature(self, func: FunctionDef) -> str:
        params = []
        for p in func.parameters:
            type_hint = p.type_hint or "object"
            params.append(f"{type_hint} {p.name}")

        params_str = ', '.join(params)
        ret_type = func.return_type or "void"
        mods = ' '.join(func.modifiers) if func.modifiers else ""

        return f"{mods} {ret_type} {func.name}({params_str})".strip()

    def _extract_keywords(self, text: str) -> List[str]:
        """从代码中提取关键词（过滤停止词）"""
        words = re.findall(r'[A-Za-z_][A-Za-z0-9_]*', text.lower())
        words = [w for w in words if len(w) > 2 and w not in self.stop_words]
        return list(set(words))

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def _generate_project_summary(self, modules: List[Module], cursor):
        total_classes = sum(len(m.classes) for m in modules)
        total_funcs = sum(len(m.functions) + sum(len(c.methods) for c in m.classes) for m in modules)

        dir_structure = {}
        for m in modules:
            parts = Path(m.relative_path).parts
            if len(parts) > 1:
                root = parts[0]
                dir_structure[root] = dir_structure.get(root, 0) + 1

        all_classes = []
        for m in modules:
            for c in m.classes:
                all_classes.append((c.name, len(c.methods), m.relative_path))
        top_classes = sorted(all_classes, key=lambda x: -x[1])[:20]

        all_funcs = []
        for m in modules:
            for c in m.classes:
                for f in c.methods:
                    all_funcs.append((f"{c.name}.{f.name}", f.end_line - f.start_line, m.relative_path))
        top_funcs = sorted(all_funcs, key=lambda x: -x[1])[:30]

        summary = {
            "stats": {"files": len(modules), "classes": total_classes, "functions": total_funcs},
            "structure": dir_structure,
            "top_classes": [{"name": c[0], "methods": c[1], "file": c[2]} for c in top_classes],
            "top_functions": [{"name": f[0], "lines": f[1], "file": f[2]} for f in top_funcs],
        }

        cursor.execute("""
            INSERT OR REPLACE INTO project_summary (key, value)
            VALUES ('project_overview', ?)
        """, (json.dumps(summary, ensure_ascii=False),))

    def get_project_context(self) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM project_summary WHERE key = 'project_overview'")
        row = cursor.fetchone()
        conn.close()

        if not row:
            return ""

        summary = json.loads(row[0])
        stats = summary["stats"]

        lines = [
            f"[Project Overview]",
            f"Files: {stats['files']}, Classes: {stats['classes']}, Functions: {stats['functions']}",
            "",
            "Core modules:"
        ]

        for mod, count in list(summary["structure"].items())[:10]:
            lines.append(f"  {mod}/ ({count} files)")

        lines.append("")
        lines.append("Key classes:")
        for c in summary["top_classes"][:15]:
            lines.append(f"  {c['name']} ({c['methods']} methods) - {c['file']}")

        lines.append("")
        lines.append("Key functions:")
        for f in summary["top_functions"][:10]:
            lines.append(f"  {f['name']} ({f['lines']} lines) - {f['file']}")

        return '\n'.join(lines)

    def _expand_query_semantics(self, query: str) -> Tuple[Set[str], Set[str], Set[str]]:
        """
        语义扩展查询 v3：多层扩展
        返回: (精确匹配词集, 扩展概念词集, 模糊相关词集)
        """
        query_lower = query.lower()

        # 1. 提取原始查询词
        query_words = set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', query_lower))
        query_words = {w for w in query_words if w not in self.stop_words and len(w) > 2}

        # 2. 中文语义扩展（精确概念）
        expanded = set()
        for cn_word, en_concepts in self.semantic_map.items():
            if cn_word in query_lower:
                expanded.update(en_concepts)

        # 3. 英文同义词扩展（从 semantic_map 的 values 反向找）
        for word in list(query_words):
            for cn_word, en_concepts in self.semantic_map.items():
                if word in en_concepts:
                    expanded.update(en_concepts)

        # 4. 驼峰拆分（比如 query 是 UserService，能匹配到 user 和 service）
        for word in list(query_words):
            parts = re.findall(r'[A-Z][a-z]+|[a-z]+|[A-Z]+(?=[A-Z]|$)', word)
            if len(parts) > 1:
                query_words.update(p.lower() for p in parts)

        # 5. 模糊相关词（用于弱匹配，权重低）
        fuzzy_words = set()
        for w in query_words:
            if len(w) >= 4:
                fuzzy_words.add(w[:4])  # 前缀4个字符
        for w in expanded:
            if len(w) >= 4:
                fuzzy_words.add(w[:4])

        return query_words, expanded, fuzzy_words

    def _calculate_score(self, snippet: CodeSnippet, concept_tags: List[str],
                         query_words: Set[str], expanded_words: Set[str],
                         fuzzy_words: Set[str] = None) -> Tuple[float, List[str]]:
        """
        精细打分算法 v3 - 分层加权，核心类显著领先
        返回: (分数, 匹配原因列表)
        """
        if fuzzy_words is None:
            fuzzy_words = set()

        score = 0.0
        reasons = []
        name_lower = snippet.name.lower()

        # ========== 第1层：精确匹配（权重极大，拉开差距）==========
        exact_matches = 0
        for qw in query_words:
            if qw == name_lower:  # 名称完全相等
                score += 50.0  # 大幅提高，核心类直接拉满
                reasons.append(f"⭐ 精确匹配: {qw}")
                exact_matches += 1

        # 类名前缀精确匹配（比如 PageList -> page）
        for qw in query_words:
            if name_lower.startswith(qw) and len(qw) >= 3:
                score += 30.0
                reasons.append(f"[MATCH] 前缀匹配: {qw}")
                exact_matches += 1
                break

        # ========== 第2层：语义扩展精确匹配 ==========
        semantic_matches = 0
        for ew in expanded_words:
            if ew == name_lower:
                score += 40.0
                reasons.append(f"[SEM] 语义精确匹配: {ew}")
                semantic_matches += 1
            elif name_lower.startswith(ew) and len(ew) >= 3:
                score += 25.0
                reasons.append(f"[SEM] 语义前缀匹配: {ew}")
                semantic_matches += 1

        # ========== 第3层：名称包含（中等权重）==========
        name_contains = 0
        for qw in query_words:
            if qw in name_lower and qw != name_lower:  # 避免和精确匹配重复
                score += 15.0
                reasons.append(f"[NAME] 名称包含: {qw}")
                name_contains += 1

        for ew in expanded_words:
            if ew in name_lower and ew != name_lower:
                score += 10.0
                reasons.append(f"[SEM] 语义包含: {ew}")
                name_contains += 1

        # 如果方法名是 Class.method 格式，单独检查类名
        if "." in snippet.name:
            class_name = snippet.name.split(".")[0].lower()
            for qw in query_words:
                if qw == class_name:
                    score += 20.0
                    reasons.append(f"[MATCH] 类名精确匹配: {qw}")
                    break
                if class_name.startswith(qw) and len(qw) >= 3:
                    score += 15.0
                    reasons.append(f"[CLASS] 类名前缀匹配: {qw}")
                    break

        # ========== 第4层：概念标签匹配 ==========
        concept_matches = 0
        for tag in concept_tags:
            if tag in expanded_words:
                score += 12.0
                reasons.append(f"[TAG] 语义概念匹配: {tag}")
                concept_matches += 1
            elif tag in query_words:
                score += 8.0
                reasons.append(f"[TAG] 概念标签匹配: {tag}")
                concept_matches += 1

        # ========== 第5层：签名关键词匹配（低权重）==========
        keywords = self._extract_keywords(snippet.signature)
        keyword_matches = 0
        for qw in query_words:
            if qw in keywords:
                score += 5.0
                keyword_matches += 1

        for ew in expanded_words:
            if ew in keywords:
                score += 3.0
                keyword_matches += 1

        if keyword_matches > 0:
            reasons.append(f"[KEY] 关键词匹配: {keyword_matches}个")

        # ========== 第6层：类型权重（类优先）==========
        type_weight = self.type_weights.get(snippet.type, 1.0)
        score *= type_weight

        # ========== 第7层：协同放大（多种匹配命中，说明非常相关）==========
        match_types = sum([
            1 if exact_matches > 0 else 0,
            1 if semantic_matches > 0 else 0,
            1 if name_contains > 0 else 0,
            1 if concept_matches > 0 else 0,
        ])
        if match_types >= 3:
            score *= 2.0  # 三种以上匹配，直接 ×2
            reasons.append("[BOOST] 多维度协同匹配")
        elif match_types >= 2:
            score *= 1.3  # 两种 ×1.3

        # ========== 第8层：核心类加成（长类/多方法类加分）==========
        line_count = snippet.end_line - snippet.start_line
        if snippet.type == "class" and line_count > 50:
            score += 8.0  # 长方法的类大概率是核心
            reasons.append("核心类（代码长度）")
        elif snippet.type == "function" and 15 <= line_count <= 200:
            score += 3.0  # 中等长度方法通常有逻辑

        return score, reasons

    def search(self, query: str, max_results: int = 8, max_tokens: int = 3000) -> List[CodeSnippet]:
        """
        智能代码检索 v2
        - 分层召回：先粗筛，再精排
        - 混合打分：精确匹配 + 语义匹配 + 关键词匹配
        """
        print(f"\n[RAG] Searching: '{query[:50]}...'")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Step 1: 语义扩展查询（三层）
        query_words, expanded_words, fuzzy_words = self._expand_query_semantics(query)
        print(f"   [Query] 原词: {query_words}")
        if expanded_words:
            print(f"   [Query] 语义扩展: {expanded_words}")

        # Step 2: 加载所有候选片段
        cursor.execute("SELECT * FROM code_index")
        candidates = []

        for row in cursor.fetchall():
            snippet = CodeSnippet(
                type=row[1],
                name=row[2],
                file_path=row[3],
                start_line=int(row[4]),
                end_line=int(row[5]),
                signature=row[6],
                content=row[6]
            )

            # 向后兼容：旧数据库没有 concept_tags 列
            concept_tags = []
            if len(row) > 10 and row[10]:
                try:
                    concept_tags = json.loads(row[10])
                except:
                    pass

            # Step 3: 计算相关度（v3 分层算法）
            score, reasons = self._calculate_score(
                snippet, concept_tags, query_words, expanded_words, fuzzy_words
            )

            if score > 0:
                snippet.relevance = score
                snippet.match_reason = ", ".join(reasons[:4])  # 前4个原因
                candidates.append(snippet)

        conn.close()

        # Step 4: 去重 + 排序
        seen = set()
        unique_candidates = []
        for c in candidates:
            key = f"{c.file_path}:{c.name}"
            if key not in seen:
                seen.add(key)
                unique_candidates.append(c)

        unique_candidates.sort(key=lambda x: -x.relevance)

        # Step 5: 打印检索结果（Debug + 分差提示）
        print(f"\n   [Result] 找到 {len(unique_candidates)} 个相关片段")
        if len(unique_candidates) >= 2:
            first_score = unique_candidates[0].relevance
            second_score = unique_candidates[1].relevance
            if first_score > second_score * 1.5:
                print(f"   [OK] 第一名显著领先: {first_score:.1f} vs {second_score:.1f}")
            elif first_score > second_score * 1.2:
                print(f"   [INFO] 第一名有优势: {first_score:.1f} vs {second_score:.1f}")
            else:
                print(f"   [WARN] 分差较小，可能需要更精确的查询词")

        for i, r in enumerate(unique_candidates[:10]):
            print(f"   #{i+1} [{r.type:8}] {r.name:40} {r.relevance:5.1f}分  ({r.match_reason})")

        # Step 6: 按 Token 限制选择，优先高相关度
        selected = []
        total_tokens = 0

        for r in unique_candidates:
            tokens = self._estimate_tokens(r.signature)
            if total_tokens + tokens <= max_tokens and len(selected) < max_results:
                selected.append(r)
                total_tokens += tokens
            else:
                break

        print(f"   最终选择 {len(selected)} 个片段，总 Token ≈ {total_tokens}")

        return selected

    def get_call_chain_context(self, function_name: str, depth: int = 2) -> str:
        """获取调用链上下文"""
        return self.search(function_name, max_results=6, max_tokens=2000)
