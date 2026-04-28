#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代码分析工具 Web 后端
"""
import sys
import os
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks

# 修复 Windows CMD 编码问题
os.environ['PYTHONIOENCODING'] = 'utf-8'
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import json
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.llm_client import LLMClient
from src.core.code_rag import CodeRAG
from src.core.deep_analyzer import DeepAnalyzer
from src.utils.config import Config
from src.models.project import Project

app = FastAPI(title="代码分析工具")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_DIR = Path(__file__).parent.parent / "output"


class ProjectInfo(BaseModel):
    name: str
    path: str
    file_count: int
    line_count: int
    analyzed_at: str


class ClassInfo(BaseModel):
    name: str
    file_path: str
    start_line: int
    end_line: int
    method_count: int


class MethodInfo(BaseModel):
    name: str
    class_name: Optional[str]
    file_path: str
    start_line: int
    end_line: int


class PaginatedResponse(BaseModel):
    """分页响应通用模型"""
    items: list
    total: int
    page: int
    page_size: int
    total_pages: int


class CallGraphEdge(BaseModel):
    source: str
    target: str
    count: int


class BusinessAnalysisRequest(BaseModel):
    project_name: str
    module_path: Optional[str] = None
    focus_area: Optional[str] = None


class AnalyzeNewProjectRequest(BaseModel):
    project_path: str
    project_name: Optional[str] = None


class ChatRequest(BaseModel):
    project_name: str
    message: str
    history: List[Dict[str, str]] = []  # 对话历史
    forced_context: List[Dict[str, str]] = []  # 强制上下文：[{"type": "class/function", "name": "...", "file_path": "..."}]


class DeepAnalyzeRequest(BaseModel):
    project_name: str
    target_type: str  # function, class, module
    target_name: str
    file_path: Optional[str] = ""
    force_refresh: bool = False  # 强制刷新，不走缓存
    additional_context: Optional[str] = ""  # 人工引导/纠正信息


def get_db_connection(project_name: str):
    """获取项目知识库连接"""
    db_path = DB_DIR / project_name / "knowledge.db"
    if not db_path.exists():
        raise HTTPException(status_code=404, detail=f"项目 {project_name} 未找到")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 优化查询性能：启用必要的索引（已存在时会自动忽略）
    cursor = conn.cursor()
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_classes_name ON classes(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_functions_name ON functions(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_functions_class_id ON functions(class_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_modules_path ON modules(relative_path)")

    return conn


@app.get("/")
async def root():
    """前端入口"""
    index_path = Path(__file__).parent / "static" / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return {"message": "代码分析工具 API 运行中"}


@app.get("/api/config")
async def get_config():
    """获取当前配置信息"""
    config = Config()
    api_key = config.llm.api_key or ""

    if api_key:
        masked_key = api_key[:4] + "*" * max(0, len(api_key) - 8) + api_key[-4:] if len(api_key) > 8 else "***" + api_key[-1:]
    else:
        masked_key = "未配置"

    llm_enabled = config.analysis.use_llm and bool(api_key)

    return {
        "llm_enabled": llm_enabled,
        "base_url": config.llm.base_url,
        "model": config.llm.model,
        "api_key": masked_key,
        "temperature": config.llm.temperature
    }


@app.get("/api/projects")
async def list_projects() -> List[ProjectInfo]:
    """获取所有已分析的项目"""
    projects = []
    if DB_DIR.exists():
        for proj_dir in DB_DIR.iterdir():
            if proj_dir.is_dir():
                db_path = proj_dir / "knowledge.db"
                if db_path.exists():
                    try:
                        conn = sqlite3.connect(str(db_path))
                        cursor = conn.cursor()
                        cursor.execute("SELECT name, root_path, total_files, total_lines, updated_at FROM projects LIMIT 1")
                        proj = cursor.fetchone()
                        if proj:
                            # 从modules表获取真实计数
                            cursor.execute("SELECT COUNT(*) FROM modules")
                            module_count = cursor.fetchone()[0]
                            cursor.execute("SELECT SUM(line_count) FROM modules")
                            lines_result = cursor.fetchone()[0]
                            line_count = lines_result or 0

                            projects.append(ProjectInfo(
                                name=proj_dir.name,
                                path=proj[1] or "",
                                file_count=module_count,
                                line_count=line_count,
                                analyzed_at=str(proj[4]) or ""
                            ))
                        conn.close()
                    except Exception as e:
                        print(f"Error reading {proj_dir}: {e}")
                        pass
    return sorted(projects, key=lambda x: x.name)


@app.get("/api/{project_name}/overview")
async def get_project_overview(project_name: str):
    """获取项目概览"""
    conn = get_db_connection(project_name)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM modules")
    module_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM classes")
    class_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM functions")
    func_count = cursor.fetchone()[0]

    # 获取核心模块
    cursor.execute("""
        SELECT m.relative_path,
               (SELECT COUNT(*) FROM classes c WHERE c.module_id = m.id) as class_count,
               (SELECT COUNT(*) FROM functions f WHERE f.module_id = m.id) as func_count
        FROM modules m
        ORDER BY (class_count + func_count) DESC
        LIMIT 20
    """)
    top_modules = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return {
        "module_count": module_count,
        "class_count": class_count,
        "function_count": func_count,
        "top_modules": top_modules
    }


@app.get("/api/{project_name}/classes")
async def list_classes(project_name: str, search: str = "", page: int = 1, page_size: int = 50) -> PaginatedResponse:
    """搜索类（分页）"""
    conn = get_db_connection(project_name)
    cursor = conn.cursor()

    # 1. 查询总数
    cursor.execute("""
        SELECT COUNT(*) FROM classes c WHERE c.name LIKE ?
    """, (f"%{search}%",))
    total = cursor.fetchone()[0]

    # 2. 分页查询数据
    offset = (page - 1) * page_size
    cursor.execute("""
        SELECT c.name, m.relative_path as file_path, c.start_line, c.end_line,
               (SELECT COUNT(*) FROM functions f WHERE f.class_id = c.id) as method_count
        FROM classes c
        JOIN modules m ON c.module_id = m.id
        WHERE c.name LIKE ?
        ORDER BY method_count DESC
        LIMIT ? OFFSET ?
    """, (f"%{search}%", page_size, offset))

    classes = [ClassInfo(**dict(row)) for row in cursor.fetchall()]
    conn.close()

    total_pages = (total + page_size - 1) // page_size
    return PaginatedResponse(
        items=classes,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@app.get("/api/{project_name}/methods")
async def list_methods(project_name: str, search: str = "", class_name: str = "",
                       page: int = 1, page_size: int = 100) -> PaginatedResponse:
    """搜索方法（分页）"""
    conn = get_db_connection(project_name)
    cursor = conn.cursor()

    conditions = ["f.name LIKE ?"]
    params = [f"%{search}%"]

    if class_name:
        conditions.append("c.name LIKE ?")
        params.append(f"%{class_name}%")

    where_clause = " AND ".join(conditions)

    # 1. 查询总数
    cursor.execute(f"""
        SELECT COUNT(*) FROM functions f
        JOIN modules m ON f.module_id = m.id
        LEFT JOIN classes c ON f.class_id = c.id
        WHERE {where_clause}
    """, params)
    total = cursor.fetchone()[0]

    # 2. 分页查询数据
    offset = (page - 1) * page_size
    query = f"""
        SELECT f.name, c.name as class_name, m.relative_path as file_path,
               f.start_line, f.end_line
        FROM functions f
        JOIN modules m ON f.module_id = m.id
        LEFT JOIN classes c ON f.class_id = c.id
        WHERE {where_clause}
        ORDER BY LENGTH(f.name) DESC
        LIMIT ? OFFSET ?
    """
    params.extend([page_size, offset])

    cursor.execute(query, params)

    methods = []
    for row in cursor.fetchall():
        methods.append(MethodInfo(
            name=row[0],
            class_name=row[1],
            file_path=row[2],
            start_line=row[3],
            end_line=row[4]
        ))

    conn.close()

    total_pages = (total + page_size - 1) // page_size
    return PaginatedResponse(
        items=methods,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@app.get("/api/{project_name}/callgraph")
async def get_call_graph(project_name: str, depth: int = 3, method_filter: str = ""):
    """获取调用图"""
    conn = get_db_connection(project_name)
    cursor = conn.cursor()

    # 读取调用图数据
    cursor.execute("SELECT value FROM project_metadata WHERE key = 'call_graph'")
    row = cursor.fetchone()

    if row and row[0]:
        graph_data = json.loads(row[0])
        edges = []

        for edge in graph_data.get('edges', []):
            source = edge.get('source', '')
            target = edge.get('target', '')

            if method_filter:
                if method_filter not in source and method_filter not in target:
                    continue

            edges.append(CallGraphEdge(
                source=source,
                target=target,
                count=1
            ))

        nodes = set()
        for e in edges[:200]:
            nodes.add(e.source)
            nodes.add(e.target)

        conn.close()
        return {
            "nodes": list(nodes)[:100],
            "edges": edges[:200]
        }

    conn.close()
    return {"nodes": [], "edges": []}


@app.get("/api/{project_name}/analyze/business")
async def get_cached_business_analysis(project_name: str):
    """获取缓存的业务分析结果"""
    conn = get_db_connection(project_name)
    cursor = conn.cursor()

    # 检查是否已有缓存结果
    cursor.execute("SELECT value FROM project_metadata WHERE key = 'business_analysis'")
    row = cursor.fetchone()
    conn.close()

    if row and row[0]:
        import json
        return json.loads(row[0])

    raise HTTPException(status_code=404, detail="暂无缓存的分析结果，请点击重新分析")


@app.post("/api/{project_name}/analyze/business")
async def analyze_business_logic(project_name: str, request: BusinessAnalysisRequest):
    """深度业务分析（可通过 force=true 强制重新分析）"""
    conn = get_db_connection(project_name)
    cursor = conn.cursor()

    # 除非强制重新分析，否则先尝试读取缓存
    if not getattr(request, 'force', False):
        cursor.execute("SELECT value FROM project_metadata WHERE key = 'business_analysis'")
        row = cursor.fetchone()
        if row and row[0]:
            import json
            conn.close()
            return json.loads(row[0])

    # 收集核心代码信息
    cursor.execute("""
        SELECT c.name, m.relative_path
        FROM classes c
        JOIN modules m ON c.module_id = m.id
        ORDER BY (SELECT COUNT(*) FROM functions f WHERE f.class_id = c.id) DESC
        LIMIT 20
    """)
    core_classes = cursor.fetchall()

    cursor.execute("""
        SELECT f.name, c.name as class_name, m.relative_path
        FROM functions f
        JOIN modules m ON f.module_id = m.id
        LEFT JOIN classes c ON f.class_id = c.id
        ORDER BY (f.end_line - f.start_line) DESC
        LIMIT 30
    """)
    core_methods = cursor.fetchall()

    # 构建 LLM 分析 prompt
    code_context = "核心类:\n"
    for cls in core_classes:
        code_context += f"- {cls[0]} ({cls[1]})\n"

    code_context += "\n核心方法 (按代码行数排序):\n"
    for method in core_methods:
        owner = f"{method[1]}." if method[1] else ""
        code_context += f"- {owner}{method[0]} ({method[2]})\n"

    config = Config()
    llm = LLMClient(config)

    if not llm.llm_enabled:
        conn.close()
        raise HTTPException(status_code=400, detail="LLM 未启用，请在 .env 文件中配置 API 密钥和模型信息")

    # 加载 RAG 引擎，获取更丰富的上下文
    rag = CodeRAG(str(DB_DIR / project_name / "knowledge.db"))
    project_context = rag.get_project_context()

    prompt = f"""
你是一位世界级的代码分析专家，分析深度和质量对标 DeepWiki。

【项目上下文】
{project_context}

【核心代码清单】
{code_context}

请从以下 10 个维度进行深度、结构化的分析：

---
## 1. 项目概览
- 项目类型/定位
- 核心价值/解决的问题
- 技术栈和依赖

## 2. 整体架构
- 采用的架构模式（分层/微内核/事件驱动/管道与过滤器等）
- 核心架构图（用 Mermaid 文本格式描述）
- 架构优缺点分析

## 3. 核心模块分析
详细分析每个核心模块的：
- 职责边界
- 核心依赖
- 关键实现机制

## 4. 调用链与数据流
- 典型调用链路（如：请求入口 → 业务处理 → 数据持久化）
- 关键数据结构流转
- 重要的设计模式识别

## 5. 核心类深度解析
详细解读 Top 5 最重要的类：
- 设计意图
- 核心方法说明
- 与其他类的协作关系
- 潜在的设计问题

## 6. 关键技术实现
- 项目中独特的/巧妙的实现方式
- 性能优化手段
- 并发/异步处理机制
- 异常处理策略

## 7. 扩展性与灵活性
- 扩展点设计
- 配置化能力
- 可插拔机制分析

## 8. 代码质量评估
- 可读性/可维护性评分（1-10分）
- 代码坏味道清单（附具体位置）
- 重复代码情况
- 注释质量

## 9. 技术债务与重构建议
- 按优先级排序的重构清单
- 每个重构项的预期收益和成本
- 分阶段实施路线图

## 10. 维护与贡献指南
- 新人上手路径（阅读顺序）
- 常见调试流程
- 添加新功能的步骤
- 避坑指南

---
要求：
1. 结构清晰，使用 Markdown 标题和列表
2. 所有分析必须基于实际代码，有具体的文件名、类名、方法名支撑
3. 给出可执行的、具体的建议，不要空泛理论
4. 分析深度要达到能让一个完全不了解此项目的开发者快速上手
"""

    print("\n" + "="*80)
    print("[INFO] 业务分析 - 发送到 LLM")
    print(f"[INFO] 项目: {project_name}")
    print(f"[INFO] 模型: {llm.model}")
    print(f"[INFO] Prompt 长度: {len(prompt)} 字符")
    print("="*80)
    print("Prompt 预览 (前 500 字符):")
    print(prompt[:500])
    print("..." if len(prompt) > 500 else "")
    print("="*80)
    print("[INFO] 等待 LLM 响应...\n")

    try:
        analysis_result = await llm.client.chat.completions.create(
            model=llm.model,
            messages=[
                {"role": "system", "content": "你是专业的遗留代码分析专家，擅长从复杂代码中提炼业务价值和识别技术债务。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=4000,
            timeout=300.0  # 5 分钟超时
        )

        result_content = analysis_result.choices[0].message.content or ""
        print("\n" + "="*80)
        print("[OK] 收到 LLM 响应")
        print(f"[INFO] 响应长度: {len(result_content)} 字符")
        if hasattr(analysis_result, 'usage') and analysis_result.usage:
            print(f"[INFO] Token 使用: prompt={analysis_result.usage.prompt_tokens}, completion={analysis_result.usage.completion_tokens}, total={analysis_result.usage.total_tokens}")
        print("="*80)
        print("响应预览 (前 500 字符):")
        print(result_content[:500])
        print("..." if len(result_content) > 500 else "")
        print("="*80 + "\n")

        result = {
            "project_name": project_name,
            "analysis": result_content,
            "code_samples_count": len(core_classes) + len(core_methods),
            "cached_at": datetime.now().isoformat()
        }

        # 保存到数据库缓存
        import json
        cursor.execute("""
            INSERT OR REPLACE INTO project_metadata (project_id, key, value)
            VALUES ((SELECT id FROM projects LIMIT 1), 'business_analysis', ?)
        """, (json.dumps(result, ensure_ascii=False),))
        conn.commit()
        conn.close()

        return result
    except Exception as e:
        conn.close()
        error_msg = str(e)
        print(f"❌ LLM 调用异常: {error_msg}")

        # 精细化错误诊断
        if "404" in error_msg or "not found" in error_msg.lower():
            error_msg = "API 端点或模型不存在，请检查 LLM_BASE_URL 和 LLM_MODEL 配置"
        elif "401" in error_msg or "auth" in error_msg.lower():
            error_msg = "认证失败，请检查 LLM_API_KEY 配置"
        elif "403" in error_msg or "forbidden" in error_msg.lower():
            error_msg = "访问被拒绝，请检查 API Key 权限和服务是否开通"
        elif "500" in error_msg or "Internal Server Error" in error_msg:
            error_msg = "模型服务内部错误，可能是模型过载或请求格式不对，请稍后重试"
        elif "timeout" in error_msg.lower():
            error_msg = "请求超时，请检查网络连接或稍后重试"
        elif "JSON" in error_msg or "json" in error_msg:
            error_msg = f"API 返回格式异常（非JSON）: {error_msg[:100]}"
        elif "rate_limit" in error_msg.lower() or "rate limit" in error_msg.lower():
            error_msg = "触发 API 限流，请降低请求频率"

        raise HTTPException(status_code=500, detail=f"LLM 分析失败: {error_msg}")


@app.post("/api/{project_name}/chat")
async def chat_with_project(project_name: str, request: ChatRequest):
    """针对项目的智能对话 - RAG 检索最小化 token 消耗
    支持手动强制注入代码片段（forced_context 参数）
    """
    if not (DB_DIR / project_name / "knowledge.db").exists():
        raise HTTPException(status_code=404, detail=f"项目 {project_name} 不存在")

    config = Config()
    llm = LLMClient(config)

    if not llm.llm_enabled:
        raise HTTPException(status_code=400, detail="LLM 未启用")

    # 1. RAG 检索相关代码
    rag = CodeRAG(str(DB_DIR / project_name / "knowledge.db"))
    relevant_code = rag.search(request.message, max_results=10, max_tokens=3500)

    # 2. 获取项目概览（固定上下文，每次都带）
    project_context = rag.get_project_context()

    # 3. 构建检索到的代码上下文
    code_context_parts = []
    forced_context_items = []  # 用于返回给前端展示

    # ========== 强制注入用户手动选择的代码 ==========
    if request.forced_context:
        print(f"   [Manual] 强制注入 {len(request.forced_context)} 个代码片段")
        conn = get_db_connection(project_name)
        cursor = conn.cursor()

        for forced_item in request.forced_context:
            item_type = forced_item.get("type", "")
            item_name = forced_item.get("name", "")
            item_file = forced_item.get("file_path", "")

            if item_type == "class":
                # 获取类完整信息（包括所有方法）
                cursor.execute("""
                    SELECT c.id, c.name, c.start_line, c.end_line, m.relative_path
                    FROM classes c JOIN modules m ON c.module_id = m.id
                    WHERE c.name = ? AND m.relative_path LIKE ?
                    LIMIT 1
                """, (item_name, f"%{item_file}%" if item_file else "%"))
                cls_row = cursor.fetchone()

                if cls_row:
                    # 获取类的方法列表
                    cursor.execute("""
                        SELECT f.name, f.start_line, f.end_line, f.content
                        FROM functions f WHERE f.class_id = ?
                        ORDER BY f.start_line
                    """, (cls_row[0],))
                    methods = cursor.fetchall()

                    # 构建类签名 + 方法内容
                    class_code_parts = [f"class {cls_row[1]} {{"]
                    for m in methods:
                        class_code_parts.append(f"  // Method: {m[0]} (lines {m[1]}-{m[2]})")
                        if m[3]:  # 如果有完整 content
                            class_code_parts.append(f"  {m[3]}")
                        else:
                            class_code_parts.append(f"  void {m[0]}();")
                    class_code_parts.append("}")

                    full_code = '\n'.join(class_code_parts)
                    code_context_parts.append(f"""
// 🔒 手动选择 CLASS: {cls_row[1]}
// File: {cls_row[4]} (lines {cls_row[2]}-{cls_row[3]})
{full_code}
""".strip())
                    forced_context_items.append({"type": "class", "name": item_name, "file_path": cls_row[4]})

            elif item_type == "function":
                # 获取函数/方法完整信息
                if "." in item_name:
                    cls_name, func_name = item_name.split(".", 1)
                    cursor.execute("""
                        SELECT f.name, f.start_line, f.end_line, f.content, m.relative_path, c.name
                        FROM functions f
                        JOIN modules m ON f.module_id = m.id
                        LEFT JOIN classes c ON f.class_id = c.id
                        WHERE f.name = ? AND c.name = ? AND m.relative_path LIKE ?
                        LIMIT 1
                    """, (func_name, cls_name, f"%{item_file}%" if item_file else "%"))
                else:
                    cursor.execute("""
                        SELECT f.name, f.start_line, f.end_line, f.content, m.relative_path, NULL
                        FROM functions f
                        JOIN modules m ON f.module_id = m.id
                        WHERE f.name = ? AND f.class_id IS NULL AND m.relative_path LIKE ?
                        LIMIT 1
                    """, (item_name, f"%{item_file}%" if item_file else "%"))

                func_row = cursor.fetchone()
                if func_row:
                    display_name = f"{func_row[5]}.{func_row[0]}" if func_row[5] else func_row[0]
                    full_code = func_row[3] or f"void {func_row[0]}();"
                    code_context_parts.append(f"""
// 🔒 手动选择 FUNCTION: {display_name}
// File: {func_row[4]} (lines {func_row[1]}-{func_row[2]})
{full_code}
""".strip())
                    forced_context_items.append({"type": "function", "name": display_name, "file_path": func_row[4]})

        conn.close()

    # 添加自动检索到的代码（在手动选择之后，优先级略低）
    for snip in relevant_code:
        # 如果这个片段已经在强制上下文中（同名+同类型），跳过重复
        already_forced = any(
            f["name"] == snip.name and f["type"] == snip.type
            for f in forced_context_items
        )
        if already_forced:
            continue

        code_context_parts.append(f"""
// {snip.type.upper()}: {snip.name}
// File: {snip.file_path} (lines {snip.start_line}-{snip.end_line})
{snip.signature}
""".strip())

    code_context = '\n\n'.join(code_context_parts)

    # 4. 处理对话历史（只保留最近 3 轮，节省 token）
    history_context = []
    for msg in request.history[-6:]:  # 最多 3 轮对话 (user+assistant)
        history_context.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    # 5. 构建最终 prompt
    system_prompt = f"""你是一位资深的代码理解专家，正在帮助用户理解代码项目。

【项目基本信息】
{project_context}

【检索到的相关代码片段】
{code_context if code_context else '（未找到特别相关的代码）'}

回答要求：
1. 所有回答必须基于提供的代码上下文，不要编造
2. 提到类、方法时，附带文件名和行号
3. 如果上下文信息不足，请明确告知
4. 回答简洁实用，重点突出
5. 代码引用使用 Markdown 格式"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history_context)
    messages.append({"role": "user", "content": request.message})

    # Debug 日志
    print("\n" + "="*80)
    print("[INFO] 代码对话 - 发送到 LLM")
    print(f"[INFO] 项目: {project_name}")
    print(f"[INFO] 模型: {llm.model}")
    print(f"[INFO] 用户问题: {request.message}")
    print(f"[INFO] 检索到 {len(code_context_parts)} 个代码片段")
    print("="*80)

    try:
        response = await llm.client.chat.completions.create(
            model=llm.model,
            messages=messages,
            temperature=0.4,
            max_tokens=2000,
            timeout=120.0  # 对话 2 分钟超时
        )

        answer = response.choices[0].message.content or ""
        print("\n" + "="*80)
        print("[OK] 收到 LLM 响应")
        print(f"[INFO] 响应长度: {len(answer)} 字符")
        if hasattr(response, 'usage') and response.usage:
            print(f"[INFO] Token 使用: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, total={response.usage.total_tokens}")
        print("="*80)
        print("回答预览 (前 300 字符):")
        print(answer[:300])
        print("..." if len(answer) > 300 else "")
        print("="*80 + "\n")

        # 计算 token 消耗
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0

        return {
            "answer": answer,
            "context_used": {
                "snippets_count": len(code_context_parts),
                "forced_count": len(forced_context_items),
                "forced_items": forced_context_items,
                "auto_snippets": [
                    {
                        "type": s.type,
                        "name": s.name,
                        "file_path": s.file_path,
                        "start_line": s.start_line,
                        "end_line": s.end_line,
                        "relevance": s.relevance
                    }
                    for s in relevant_code
                ],
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens
            }
        }

    except Exception as e:
        error_msg = str(e)
        print(f"❌ 对话异常: {error_msg}")

        # 精细化错误诊断
        if "404" in error_msg or "not found" in error_msg.lower():
            error_msg = "API 端点或模型不存在，请检查 LLM_BASE_URL 和 LLM_MODEL 配置"
        elif "401" in error_msg or "auth" in error_msg.lower():
            error_msg = "认证失败，请检查 LLM_API_KEY 配置"
        elif "403" in error_msg or "forbidden" in error_msg.lower():
            error_msg = "访问被拒绝，请检查 API Key 权限"
        elif "500" in error_msg or "Internal Server Error" in error_msg:
            error_msg = "模型服务内部错误，可能是模型过载，请稍后重试"
        elif "timeout" in error_msg.lower():
            error_msg = "请求超时，请检查网络连接或稍后重试"
        elif "JSON" in error_msg or "json" in error_msg:
            error_msg = f"API 返回格式异常（非JSON）: {error_msg[:100]}"

        raise HTTPException(status_code=500, detail=f"对话失败: {error_msg}")

@app.get("/api/{project_name}/code/{file_path:path}")
async def get_file_code(project_name: str, file_path: str, lines: int = 5000):
    """获取文件代码片段"""
    conn = get_db_connection(project_name)
    cursor = conn.cursor()

    try:
        # 读取项目路径
        cursor.execute("SELECT root_path FROM projects LIMIT 1")
        proj_row = cursor.fetchone()
        if proj_row and proj_row[0]:
            project_root = Path(proj_row[0])

            # 先尝试直接匹配
            full_path = project_root / file_path
            if full_path.exists():
                pass
            else:
                # 尝试规范化路径：去掉可能重复的前缀、修复分隔符问题
                import os
                # 规范化路径（处理斜杠和反斜杠）
                normalized_file_path = os.path.normpath(file_path)

                # 如果文件不存在，尝试从数据库查找匹配的路径
                full_path = project_root / normalized_file_path
                if not full_path.exists():
                    # 从 modules 表查找最相似的路径
                    cursor.execute("SELECT relative_path FROM modules")
                    all_paths = [row[0] for row in cursor.fetchall()]

                    # 尝试不同的路径组合
                    found = False
                    for db_path in all_paths:
                        db_norm = os.path.normpath(db_path)
                        file_norm = os.path.normpath(file_path)
                        # 检查文件名是否匹配
                        if os.path.basename(db_norm) == os.path.basename(file_norm):
                            full_path = project_root / db_path
                            if full_path.exists():
                                found = True
                                break
                    if not found:
                        raise Exception(f"File not found: {file_path}")
            content = full_path.read_text(encoding='utf-8', errors='replace')
            all_lines = content.split('\n')
            lines_content = all_lines[:lines]
            result = {
                "file_path": file_path,
                "total_lines": len(all_lines),
                "lines": [{"number": i+1, "code": line} for i, line in enumerate(lines_content)]
            }
            conn.close()
            return result
    except Exception as e:
        pass

    conn.close()
    raise HTTPException(status_code=404, detail=f"无法读取文件内容: {file_path}")


@app.post("/api/analyze")
async def analyze_new_project(request: AnalyzeNewProjectRequest):
    """分析新项目"""
    project_path = Path(request.project_path)

    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"项目路径不存在: {request.project_path}")

    # 确定项目名称
    if request.project_name:
        project_name = request.project_name
    else:
        project_name = project_path.name

    # 创建输出目录
    output_dir = DB_DIR / project_name
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 导入分析模块
        from src.core.scanner import CodeScanner
        from src.core.ast_parser import ASTParser
        from src.core.call_graph import CallGraph
        from src.core.knowledge_base import KnowledgeBase
        from src.models.project import Project
        from src.utils.config import Config

        config = Config()

        # 1. 扫描代码文件
        scanner = CodeScanner(config)
        code_files, scan_stats = scanner.scan_directory(str(project_path))
        if not code_files:
            raise HTTPException(status_code=400, detail="未找到支持的代码文件")

        # 2. 解析 AST
        project = Project(root_path=project_path, name=project_name)
        parser = ASTParser(config)

        for file_path, lang in code_files:
            source_bytes = CodeScanner.read_file_bytes(file_path)
            if not source_bytes:
                continue
            analyzer = parser.get_analyzer(lang)
            if analyzer:
                module = analyzer.parse(source_bytes, file_path)
                if module:
                    module.relative_path = str(file_path.relative_to(project_path))
                    project.modules.append(module)

        if not project.modules:
            raise HTTPException(status_code=400, detail="没有成功解析任何文件")

        # 3. 构建调用图
        call_graph = CallGraph(project)
        call_graph.build()

        # 4. 保存到知识库
        kb = KnowledgeBase(str(output_dir / "knowledge.db"))
        project_id = kb.get_or_create_project(str(project_path), project_name)

        for module in project.modules:
            kb.save_module(project_id, module)

        # 保存调用图
        edges_data = [
            {"source": u, "target": v}
            for u, v in call_graph.graph.edges()
        ]
        kb.save_metadata(project_id, "call_graph", {
            "nodes": list(call_graph.graph.nodes()),
            "edges": edges_data
        })
        kb.close()

        # 构建 RAG 索引
        rag = CodeRAG(str(output_dir / "knowledge.db"))
        rag.index_project(project.modules)

        return {
            "success": True,
            "project_name": project_name,
            "modules_count": len(project.modules),
            "edges_count": len(edges_data),
            "nodes_count": len(call_graph.graph.nodes()),
            "scan_stats": {
                "code_files_found": len(code_files),
                "directories_skipped": scan_stats["skipped_dirs"],
                "files_skipped": scan_stats["skipped_files"]
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


# ========== 🧠 深度代码分析 API ==========

def _load_project(project_name: str) -> Project:
    """加载项目（从知识数据库重建 Project 对象）"""
    db_path = DB_DIR / project_name / "knowledge.db"
    if not db_path.exists():
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_name}")

    # 简单重建 Project 对象（只需要模块和类/方法结构）
    project = Project(root_path=Path("."), name=project_name)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 加载模块
    cursor.execute("SELECT id, relative_path, language FROM modules")
    for m_row in cursor.fetchall():
        from src.models.project import Module, Language
        lang_str = m_row['language'] if 'language' in m_row.keys() else 'UNKNOWN'
        try:
            lang = Language[lang_str] if lang_str else Language.UNKNOWN
        except:
            lang = Language.UNKNOWN

        # Normalize path to forward slashes for consistent comparison
        normalized_path = m_row['relative_path'].replace("\\", "/")
        module = Module(
            file_path=Path(normalized_path),
            relative_path=normalized_path,
            language=lang
        )

        # 加载该模块的类
        cursor.execute("SELECT id, name, start_line, end_line FROM classes WHERE module_id = ?", (m_row['id'],))
        for c_row in cursor.fetchall():
            from src.models.project import ClassDef
            cls = ClassDef(
                name=c_row['name'],
                start_line=c_row['start_line'],
                end_line=c_row['end_line'],
                methods=[]
            )

            # 加载类的方法
            cursor.execute("SELECT name, start_line, end_line, parameters, calls FROM functions WHERE class_id = ?", (c_row['id'],))
            for f_row in cursor.fetchall():
                from src.models.project import FunctionDef, Parameter
                import json
                params_json = json.loads(f_row['parameters'] or '[]') if f_row['parameters'] else []
                calls = json.loads(f_row['calls'] or '[]') if f_row['calls'] else []
                # 将字典转换为 Parameter 对象
                params = []
                for p in params_json:
                    if isinstance(p, dict):
                        params.append(Parameter(
                            name=p.get('name', ''),
                            type_hint=p.get('type_hint', ''),
                            default_value=p.get('default_value', '')
                        ))
                    else:
                        params.append(Parameter(name=str(p)))
                func = FunctionDef(
                    name=f_row['name'],
                    start_line=f_row['start_line'],
                    end_line=f_row['end_line'],
                    content="",
                    parameters=params,
                    calls=calls
                )
                cls.methods.append(func)

            module.classes.append(cls)

        # 加载模块级函数
        cursor.execute("SELECT name, start_line, end_line, parameters, calls FROM functions WHERE module_id = ? AND class_id IS NULL", (m_row['id'],))
        for f_row in cursor.fetchall():
            from src.models.project import FunctionDef, Parameter
            import json
            params_json = json.loads(f_row['parameters'] or '[]') if f_row['parameters'] else []
            calls = json.loads(f_row['calls'] or '[]') if f_row['calls'] else []
            # 将字典转换为 Parameter 对象
            params = []
            for p in params_json:
                if isinstance(p, dict):
                    params.append(Parameter(
                        name=p.get('name', ''),
                        type_hint=p.get('type_hint', ''),
                        default_value=p.get('default_value', '')
                    ))
                else:
                    params.append(Parameter(name=str(p)))
            func = FunctionDef(
                name=f_row['name'],
                start_line=f_row['start_line'],
                end_line=f_row['end_line'],
                content="",
                parameters=params,
                calls=calls
            )
            module.functions.append(func)

        project.modules.append(module)

    conn.close()
    return project


@app.post("/api/deep-analyze")
async def deep_analyze_target(request: DeepAnalyzeRequest):
    """
    深度代码分析（智能上下文感知）

    功能：
    - 自动获取相关上下文（调用的方法、同类其他方法、同模块代码）
    - 本地缓存，代码不变直接复用结果
    - 支持人工引导和纠正
    - 支持强制刷新重新分析
    """
    # 1. 加载项目
    project = _load_project(request.project_name)

    # 2. 初始化 LLM 客户端和分析器
    config = Config()
    llm = LLMClient(config)
    if not llm.llm_enabled:
        raise HTTPException(status_code=400, detail="LLM 未配置")

    analyzer = DeepAnalyzer(
        project=project,
        llm_client=llm,
        db_path=str(DB_DIR / request.project_name / "knowledge.db")
    )

    # 3. 查找分析目标
    target = None
    target_cls = None
    target_module = None

    # Normalize request file path to forward slashes for consistent comparison
    req_file_path = request.file_path.replace("\\", "/") if request.file_path else ""

    for module in project.modules:
        if req_file_path and req_file_path not in module.relative_path:
            continue

        # 找类
        if request.target_type == "class":
            for cls in module.classes:
                if cls.name == request.target_name:
                    target = cls
                    target_module = module
                    break
            if target:
                break

        # 找方法
        elif request.target_type == "function":
            # 可能是类方法
            if "." in request.target_name:
                cls_name, func_name = request.target_name.split(".", 1)
                for cls in module.classes:
                    if cls.name == cls_name:
                        for method in cls.methods:
                            if method.name == func_name:
                                target = method
                                target_cls = cls_name
                                target_module = module
                                break
                        break
            else:
                # 模块级函数
                for func in module.functions:
                    if func.name == request.target_name:
                        target = func
                        target_module = module
                        break
            if target:
                break

    if not target:
        raise HTTPException(status_code=404, detail=f"未找到分析目标: {request.target_type} {request.target_name}")

    # 4. 执行深度分析
    if request.target_type == "function":
        result = await analyzer.analyze_function(
            func=target,
            class_name=target_cls,
            module_path=target_module.relative_path if target_module else "",
            force_refresh=request.force_refresh,
            additional_context=request.additional_context or ""
        )
    elif request.target_type == "class":
        result = await analyzer.analyze_class(
            cls=target,
            module_path=target_module.relative_path if target_module else "",
            force_refresh=request.force_refresh,
            additional_context=request.additional_context or ""
        )
    else:
        raise HTTPException(status_code=400, detail=f"不支持的分析类型: {request.target_type}")

    return {
        "success": True,
        "data": result,
        "from_cache": not request.force_refresh and not request.additional_context
    }


@app.get("/api/{project_name}/deep-analysis/list")
async def list_deep_analyses(project_name: str):
    """获取所有已缓存的深度分析结果列表"""
    db_path = DB_DIR / project_name / "knowledge.db"
    if not db_path.exists():
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_name}")

    analyzer = DeepAnalyzer(None, None, str(db_path))
    return analyzer.get_all_cached_analyses()


@app.get("/api/{project_name}/deep-analysis/get")
async def get_deep_analysis(project_name: str, target_type: str, target_name: str, file_path: str = ""):
    """获取单个缓存的分析结果"""
    db_path = DB_DIR / project_name / "knowledge.db"
    if not db_path.exists():
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_name}")

    analyzer = DeepAnalyzer(None, None, str(db_path))
    result = analyzer.get_cached_analysis(target_type, target_name, file_path)

    if result:
        return {"success": True, "data": result}
    return {"success": False, "message": "未找到缓存的分析结果"}


@app.get("/api/{project_name}/code/detail")
async def get_code_detail(project_name: str, target_type: str, target_name: str, file_path: str = ""):
    """获取类/方法的完整代码（用于预览或手动注入前查看）
    target_type: "class" 或 "function"
    """
    conn = get_db_connection(project_name)
    cursor = conn.cursor()

    if target_type == "class":
        cursor.execute("""
            SELECT c.id, c.name, c.start_line, c.end_line, m.relative_path
            FROM classes c JOIN modules m ON c.module_id = m.id
            WHERE c.name = ? AND m.relative_path LIKE ?
            LIMIT 1
        """, (target_name, f"%{file_path}%" if file_path else "%"))
        cls_row = cursor.fetchone()

        if not cls_row:
            conn.close()
            raise HTTPException(status_code=404, detail=f"类未找到: {target_name}")

        cursor.execute("""
            SELECT f.name, f.start_line, f.end_line, f.content, f.parameters
            FROM functions f WHERE f.class_id = ?
            ORDER BY f.start_line
        """, (cls_row[0],))
        methods = cursor.fetchall()

        conn.close()

        method_list = []
        for m in methods:
            params = ""
            try:
                if m[4]:
                    import json
                    params = json.dumps(json.loads(m[4]), ensure_ascii=False)
            except:
                pass
            method_list.append({
                "name": m[0],
                "start_line": m[1],
                "end_line": m[2],
                "content": m[3] or "",
                "parameters": params
            })

        return {
            "type": "class",
            "name": cls_row[1],
            "file_path": cls_row[4],
            "start_line": cls_row[2],
            "end_line": cls_row[3],
            "method_count": len(method_list),
            "methods": method_list
        }

    elif target_type == "function":
        if "." in target_name:
            cls_name, func_name = target_name.split(".", 1)
            cursor.execute("""
                SELECT f.name, f.start_line, f.end_line, f.content, m.relative_path, c.name, f.parameters
                FROM functions f
                JOIN modules m ON f.module_id = m.id
                LEFT JOIN classes c ON f.class_id = c.id
                WHERE f.name = ? AND c.name = ? AND m.relative_path LIKE ?
                LIMIT 1
            """, (func_name, cls_name, f"%{file_path}%" if file_path else "%"))
        else:
            cursor.execute("""
                SELECT f.name, f.start_line, f.end_line, f.content, m.relative_path, NULL, f.parameters
                FROM functions f
                JOIN modules m ON f.module_id = m.id
                WHERE f.name = ? AND f.class_id IS NULL AND m.relative_path LIKE ?
                LIMIT 1
            """, (target_name, f"%{file_path}%" if file_path else "%"))

        func_row = cursor.fetchone()
        conn.close()

        if not func_row:
            raise HTTPException(status_code=404, detail=f"方法未找到: {target_name}")

        params = ""
        try:
            if func_row[6]:
                import json
                params = json.dumps(json.loads(func_row[6]), ensure_ascii=False)
        except:
            pass

        display_name = f"{func_row[5]}.{func_row[0]}" if func_row[5] else func_row[0]
        return {
            "type": "function",
            "name": display_name,
            "class_name": func_row[5],
            "file_path": func_row[4],
            "start_line": func_row[1],
            "end_line": func_row[2],
            "content": func_row[3] or "",
            "parameters": params
        }

    conn.close()
    raise HTTPException(status_code=400, detail=f"不支持的类型: {target_type}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
