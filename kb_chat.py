#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库智能问答工具 - 支持 LLM 回答代码问题
支持多项目知识库管理：
- 自动列出所有已分析的项目
- 支持通过项目名快速切换
- 支持指定完整数据库路径
"""
import sys
import os
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from dotenv import load_dotenv

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# 加载环境变量
load_dotenv()


def find_all_projects(base_dir: str = "./output") -> List[Path]:
    """查找所有已分析的项目知识库"""
    base = Path(base_dir)
    if not base.exists():
        return []

    projects = []
    for item in base.iterdir():
        if item.is_dir():
            db_file = item / "knowledge.db"
            if db_file.exists():
                projects.append(db_file)
    return sorted(projects, key=lambda p: p.stat().st_mtime, reverse=True)


def select_project(projects: List[Path], hint: str = "") -> Optional[Path]:
    """让用户选择项目"""
    if not projects:
        return None

    print("\n" + "=" * 60)
    print("[项目列表] 找到以下已分析的项目:")
    print("=" * 60)

    for i, db_path in enumerate(projects, 1):
        project_name = db_path.parent.name
        import time
        time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(db_path.stat().st_mtime))
        print(f"  [{i}] {project_name} (分析时间: {time_str})")

    print("=" * 60)

    # 如果有 hint，尝试匹配
    if hint:
        for db_path in projects:
            if hint.lower() in db_path.parent.name.lower():
                return db_path

    # 如果只有一个项目，直接返回
    if len(projects) == 1:
        print("  自动选择唯一项目")
        return projects[0]

    # 让用户选择
    while True:
        try:
            choice = input("\n请选择项目编号 (直接回车选第1个): ").strip()
            if not choice:
                return projects[0]
            idx = int(choice) - 1
            if 0 <= idx < len(projects):
                return projects[idx]
            print(f"  请输入 1-{len(projects)} 之间的数字")
        except ValueError:
            print("  请输入有效的数字")


class TokenCounter:
    """Token 计数器"""

    def __init__(self):
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.llm_calls = 0

    def add(self, prompt_tokens: int, completion_tokens: int):
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.llm_calls += 1

    def show_summary(self):
        print("\n" + "=" * 60)
        print("[TOKEN 统计]")
        print("=" * 60)
        print(f"  LLM 调用次数: {self.llm_calls}")
        print(f"  输入 Tokens: {self.total_prompt_tokens}")
        print(f"  输出 Tokens: {self.total_completion_tokens}")
        print(f"  总 Tokens: {self.total_prompt_tokens + self.total_completion_tokens}")
        print("=" * 60)


class CodeKnowledgeChat:
    """代码知识库智能问答"""

    def __init__(self, db_path: str = None):
        """
        初始化智能问答

        Args:
            db_path: 数据库路径，可以是：
                    - 项目名 (如 "ruoyi-vue-pro")
                    - 完整路径 (如 "./output/ruoyi-vue-pro/knowledge.db")
                    - None (自动查找并让用户选择)
        """
        # 处理 db_path
        if db_path:
            # 先尝试直接作为路径
            direct_path = Path(db_path)
            if direct_path.exists():
                self.db_file = direct_path
            else:
                # 尝试作为项目名查找
                projects = find_all_projects()
                found = None
                for p in projects:
                    if db_path.lower() in p.parent.name.lower():
                        found = p
                        break
                if found:
                    self.db_file = found
                else:
                    print("[ERROR] 找不到项目或数据库:", db_path)
                    print("可用项目:")
                    for p in projects:
                        print(f"  - {p.parent.name}")
                    sys.exit(1)
        else:
            # 自动查找
            projects = find_all_projects()
            if not projects:
                print("[ERROR] 未找到任何已分析的项目知识库")
                print("请先运行: python main.py analyze <项目路径> --skip-llm")
                sys.exit(1)

            self.db_file = select_project(projects)
            if not self.db_file:
                print("[ERROR] 未选择项目")
                sys.exit(1)

        self.conn = sqlite3.connect(str(self.db_file))
        self.token_counter = TokenCounter()

        # 初始化 LLM 客户端
        self.llm_client = None
        self.llm_model = "gpt-3.5-turbo"
        self.llm_enabled = False
        self._init_llm()

        # 显示统计
        self._show_stats()

    def _init_llm(self):
        """初始化 LLM 客户端"""
        if OpenAI is None:
            print("[WARN] openai 库未安装，将使用纯静态查询模式")
            return

        api_key = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
        base_url = os.getenv("LLM_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
        model = os.getenv("LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"))

        if not api_key:
            print("[WARN] 未配置 LLM_API_KEY，将使用纯静态查询模式")
            print("       如需启用大模型，请在 .env 文件中配置:")
            print("       LLM_API_KEY=your_key")
            print("       LLM_BASE_URL=https://api.openai.com/v1")
            print("       LLM_MODEL=gpt-3.5-turbo")
            return

        try:
            self.llm_client = OpenAI(api_key=api_key, base_url=base_url)
            self.llm_model = model
            self.llm_enabled = True
            print(f"[OK] LLM 已启用，模型: {model}")
        except Exception as e:
            print(f"[WARN] LLM 初始化失败: {e}，将使用纯静态查询模式")

    def _show_stats(self):
        """显示统计信息"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM projects")
        proj_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM modules")
        module_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM classes")
        class_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM functions")
        func_count = cursor.fetchone()[0]

        print("\n" + "=" * 60)
        print("[知识库统计]")
        print("=" * 60)
        print(f"  项目数: {proj_count}")
        print(f"  模块数: {module_count}")
        print(f"  类数量: {class_count}")
        print(f"  函数/方法: {func_count}")
        print(f"  LLM 模式: {'已启用' if self.llm_enabled else '纯静态查询'}")
        print("=" * 60)

    def search_relevant_code(self, question: str, limit: int = 10) -> str:
        """搜索相关代码作为上下文"""
        cursor = self.conn.cursor()

        # 提取关键词（简单分词）
        keywords = [w for w in question.split() if len(w) > 1]

        # 搜索类
        classes = []
        for kw in keywords:
            cursor.execute("""
                SELECT c.name, m.relative_path, c.start_line
                FROM classes c
                JOIN modules m ON c.module_id = m.id
                WHERE c.name LIKE ?
                LIMIT 5
            """, (f'%{kw}%',))
            classes.extend(cursor.fetchall())

        # 搜索函数
        functions = []
        for kw in keywords:
            cursor.execute("""
                SELECT f.name, c.name as class_name, m.relative_path, f.start_line
                FROM functions f
                JOIN modules m ON f.module_id = m.id
                LEFT JOIN classes c ON f.class_id = c.id
                WHERE f.name LIKE ?
                LIMIT 5
            """, (f'%{kw}%',))
            functions.extend(cursor.fetchall())

        # 去重
        unique_classes = list({c[0]: c for c in classes}.values())[:limit]
        unique_funcs = list({f[0]: f for f in functions}.values())[:limit]

        # 构建上下文
        context_parts = []

        if unique_classes:
            context_parts.append("找到的类:")
            for name, path, line in unique_classes:
                context_parts.append(f"- {name} ({path}:{line})")

        if unique_funcs:
            context_parts.append("\n找到的函数/方法:")
            for name, cls, path, line in unique_funcs:
                owner = cls or "模块"
                context_parts.append(f"- {name} [{owner}] ({path}:{line})")

        return "\n".join(context_parts)

    def ask_llm(self, question: str, context: str) -> str:
        """调用 LLM 回答问题"""
        if not self.llm_enabled or not self.llm_client:
            return None

        system_prompt = """你是一位资深的代码分析专家。
用户会问关于代码库的问题，请根据提供的代码上下文回答。
回答要求：
1. 简洁明了，重点突出
2. 基于提供的上下文信息，不要编造
3. 如果信息不足，请告诉用户需要搜索什么关键词
4. 使用中文回答"""

        user_prompt = f"""代码库上下文：
{context if context else '(未找到直接匹配的代码，需要你根据问题通用回答)'}

用户问题：{question}

请回答："""

        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )

            # 记录 token 使用
            if response.usage:
                self.token_counter.add(
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens
                )

            return response.choices[0].message.content

        except Exception as e:
            return f"[LLM 调用失败] {str(e)}"

    def answer_question(self, question: str):
        """回答用户问题"""
        print(f"\n[Q] {question}")
        print("-" * 60)

        # 步骤 1: 搜索相关代码
        print("[静态查询] 正在搜索相关代码...")
        context = self.search_relevant_code(question)

        if context:
            print("[静态查询] 找到相关代码:")
            print(context)
        else:
            print("[静态查询] 未找到直接匹配的代码")

        # 步骤 2: 调用 LLM（如果启用）
        if self.llm_enabled:
            print("\n[LLM] 正在分析并生成回答...")
            answer = self.ask_llm(question, context)
            print("\n[A] LLM 回答:")
            print("-" * 60)
            print(answer)
            print("\n[INFO] 本次回答使用了大模型")
        else:
            print("\n[INFO] 未启用 LLM，仅显示静态搜索结果")
            print("[INFO] 如需智能回答，请配置 LLM_API_KEY")

        # 显示 token 统计
        if self.llm_enabled and self.token_counter.llm_calls > 0:
            self.token_counter.show_summary()

    def show_help(self):
        """显示帮助"""
        print("\n" + "=" * 60)
        print("[HELP] 可用命令")
        print("=" * 60)
        print("  直接输入问题       - 提问代码相关问题（自动搜索+LLM回答）")
        print("  /search <关键词>    - 仅静态搜索，不调用 LLM")
        print("  /class <关键词>     - 搜索类")
        print("  /func <关键词>      - 搜索函数/方法")
        print("  /stats              - 显示知识库统计")
        print("  /tokens             - 显示 token 使用统计")
        print("  /help               - 显示帮助")
        print("  /q /quit /exit      - 退出程序")
        print("=" * 60)
        print()

    def search_only(self, keyword: str):
        """仅搜索，不调用 LLM"""
        print(f"\n[搜索] 关键词: {keyword}")
        print("-" * 60)
        context = self.search_relevant_code(keyword, limit=20)
        if context:
            print(context)
        else:
            print("未找到匹配的代码")
        print("\n[INFO] 仅静态搜索，未调用大模型")


def interactive_mode(project_name: str = None):
    """交互式问答模式"""
    print("\n" + "=" * 60)
    print("[TOOL] 代码知识库智能问答")
    print("=" * 60)
    print("\n输入问题开始提问，或输入 /help 查看可用命令\n")

    chat = CodeKnowledgeChat(project_name)
    chat.show_help()

    while True:
        try:
            cmd = input("\nask> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[BYE] 再见!")
            break

        if not cmd:
            continue

        # 处理命令
        if cmd.startswith('/'):
            parts = cmd[1:].split(maxsplit=1)
            action = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if action in ['q', 'quit', 'exit']:
                print("[BYE] 再见!")
                break

            elif action == 'help':
                chat.show_help()

            elif action == 'stats':
                chat._show_stats()

            elif action == 'tokens':
                chat.token_counter.show_summary()

            elif action in ['search', 's']:
                if not arg:
                    print("[ERROR] 请输入搜索关键词")
                    continue
                chat.search_only(arg)

            elif action in ['class', 'c']:
                if not arg:
                    print("[ERROR] 请输入搜索关键词")
                    continue
                print("\n" + "-" * 60)
                print(f"[静态搜索] 类名包含: {arg}")
                print("-" * 60)
                cursor = chat.conn.cursor()
                cursor.execute("""
                    SELECT c.name, m.relative_path, c.start_line
                    FROM classes c
                    JOIN modules m ON c.module_id = m.id
                    WHERE c.name LIKE ?
                    LIMIT 20
                """, (f'%{arg}%',))
                for name, path, line in cursor.fetchall():
                    print(f"  - {name} ({path}:{line})")
                print("\n[INFO] 纯静态搜索，未调用大模型")

            elif action in ['func', 'f']:
                if not arg:
                    print("[ERROR] 请输入搜索关键词")
                    continue
                print("\n" + "-" * 60)
                print(f"[静态搜索] 函数名包含: {arg}")
                print("-" * 60)
                cursor = chat.conn.cursor()
                cursor.execute("""
                    SELECT f.name, c.name as cls_name, m.relative_path, f.start_line
                    FROM functions f
                    JOIN modules m ON f.module_id = m.id
                    LEFT JOIN classes c ON f.class_id = c.id
                    WHERE f.name LIKE ?
                    LIMIT 20
                """, (f'%{arg}%',))
                for name, cls_name, path, line in cursor.fetchall():
                    owner = cls_name or "模块"
                    print(f"  - {name} [{owner}] ({path}:{line})")
                print("\n[INFO] 纯静态搜索，未调用大模型")

            else:
                print(f"[ERROR] 未知命令: {cmd}")
                print("输入 /help 查看可用命令")

        else:
            # 普通问题 - 调用 LLM 回答
            chat.answer_question(cmd)


def main():
    # 解析参数
    project_name = None
    args = sys.argv[1:]

    # 提取 -p/--project 参数
    i = 0
    while i < len(args):
        if args[i] in ['-p', '--project'] and i + 1 < len(args):
            project_name = args[i + 1]
            del args[i:i + 2]
            break
        i += 1

    if args and args[0] == 'list':
        # 列出所有项目
        projects = find_all_projects()
        print("\n" + "=" * 60)
        print("[已分析的项目列表]")
        print("=" * 60)
        import time
        for p in projects:
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
            print(f"  - {p.parent.name} (分析时间: {mtime})")
        print()
    elif args:
        # 命令行直接提问
        question = " ".join(args)
        chat = CodeKnowledgeChat(project_name)
        chat.answer_question(question)
    else:
        # 交互式模式
        interactive_mode(project_name)


if __name__ == "__main__":
    main()
