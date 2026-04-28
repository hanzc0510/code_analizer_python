#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库查询工具 - 交互式查询代码分析结果
支持多项目知识库管理：
- 自动列出所有已分析的项目
- 支持通过项目名快速切换
- 支持指定完整数据库路径
"""
import sys
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional


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
        mtime = db_path.stat().st_mtime
        import time
        time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
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


class KnowledgeBaseQuery:
    """知识库查询工具"""

    def __init__(self, db_path: str = None):
        """
        初始化知识库查询

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
        print("[OK] 已连接知识库:", self.db_file.parent.name)
        self._show_stats()

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

        print("\n" + "=" * 50)
        print("[STATS] 知识库统计")
        print("=" * 50)
        print(f"  项目数: {proj_count}")
        print(f"  模块数: {module_count}")
        print(f"  类数量: {class_count}")
        print(f"  函数/方法: {func_count}")
        print("=" * 50)

    def search_class(self, keyword: str, limit: int = 20):
        """搜索类"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT c.name, m.relative_path, c.start_line, c.end_line
            FROM classes c
            JOIN modules m ON c.module_id = m.id
            WHERE c.name LIKE ?
            ORDER BY LENGTH(c.name)
            LIMIT ?
        """, (f'%{keyword}%', limit))

        results = cursor.fetchall()
        if not results:
            print(f"[ERROR] 未找到包含 '{keyword}' 的类")
            return

        print(f"\n[SEARCH] 找到 {len(results)} 个类 (最多显示 {limit} 个):")
        print("-" * 80)
        print(f"{'类名':<40} {'文件':<30} {'行号':<8}")
        print("-" * 80)
        for name, path, start, end in results:
            short_path = Path(path).name if len(path) > 30 else path
            name_str = str(name) if name else ""
            print(f"{name_str[:40]:<40} {str(short_path):<30} {start}-{end}")

        print()

    def search_function(self, keyword: str, limit: int = 20):
        """搜索函数/方法"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT f.name, m.relative_path, c.name as class_name, f.start_line
            FROM functions f
            JOIN modules m ON f.module_id = m.id
            LEFT JOIN classes c ON f.class_id = c.id
            WHERE f.name LIKE ?
            ORDER BY LENGTH(f.name)
            LIMIT ?
        """, (f'%{keyword}%', limit))

        results = cursor.fetchall()
        if not results:
            print(f"[ERROR] 未找到包含 '{keyword}' 的函数/方法")
            return

        print(f"\n[SEARCH] 找到 {len(results)} 个函数/方法 (最多显示 {limit} 个):")
        print("-" * 90)
        print(f"{'函数名':<30} {'所属类':<25} {'文件':<25} {'行号':<5}")
        print("-" * 90)
        for name, path, class_name, line in results:
            short_path = Path(path).name if len(path) > 25 else path
            cls_name = class_name or "(模块级)"
            name_str = str(name) if name else ""
            print(f"{name_str[:30]:<30} {str(cls_name)[:25]:<25} {str(short_path):<25} {line}")

        print()

    def show_module_classes(self, module_keyword: str, limit: int = 50):
        """显示某个模块下的所有类"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT c.name, c.start_line, c.end_line, m.relative_path
            FROM classes c
            JOIN modules m ON c.module_id = m.id
            WHERE m.relative_path LIKE ?
            ORDER BY c.start_line
            LIMIT ?
        """, (f'%{module_keyword}%', limit))

        results = cursor.fetchall()
        if not results:
            print(f"[ERROR] 未找到匹配 '{module_keyword}' 的模块")
            return

        print(f"\n[MODULE] 模块中的类 (最多显示 {limit} 个):")
        print("-" * 80)
        current_module = None
        for name, start, end, path in results:
            if path != current_module:
                print(f"\n[DIR] {path}")
                current_module = path
            print(f"   - {name} (第 {start}-{end} 行)")

        print()

    def show_module_functions(self, module_keyword: str, limit: int = 100):
        """显示某个模块下的所有函数/方法"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT f.name, c.name as class_name, f.start_line, f.return_type, m.relative_path
            FROM functions f
            JOIN modules m ON f.module_id = m.id
            LEFT JOIN classes c ON f.class_id = c.id
            WHERE m.relative_path LIKE ?
            ORDER BY m.relative_path, f.start_line
            LIMIT ?
        """, (f'%{module_keyword}%', limit))

        results = cursor.fetchall()
        if not results:
            print(f"[ERROR] 未找到匹配 '{module_keyword}' 的模块")
            return

        print(f"\n[MODULE] 模块中的函数/方法 (最多显示 {limit} 个):")
        print("-" * 80)
        current_module = None
        for name, class_name, line, return_type, path in results:
            if path != current_module:
                print(f"\n[DIR] {path}")
                current_module = path
            prefix = f"  {class_name}." if class_name else "  "
            ret = f" -> {return_type}" if return_type else ""
            name_str = str(name) if name else ""
            print(f"{prefix}{name_str}(){ret} (第 {line} 行)")

        print()

    def list_modules(self, pattern: str = "", limit: int = 50):
        """列出所有模块"""
        cursor = self.conn.cursor()
        query = "SELECT relative_path, line_count, language FROM modules"
        params = []

        if pattern:
            query += " WHERE relative_path LIKE ?"
            params.append(f'%{pattern}%')

        query += " ORDER BY relative_path LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        results = cursor.fetchall()

        print(f"\n[LIST] 模块列表 (最多显示 {limit} 个):")
        print("-" * 80)
        print(f"{'文件路径':<60} {'代码行':<8} {'语言':<8}")
        print("-" * 80)
        for path, lines, lang in results:
            short_path = path[:60] if len(path) > 60 else path
            print(f"{str(short_path):<60} {lines:<8} {str(lang):<8}")

        print()

    def get_file_path(self, class_or_func_name: str):
        """根据类名或函数名获取文件路径"""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT 'class' as type, c.name, m.relative_path, c.start_line
            FROM classes c
            JOIN modules m ON c.module_id = m.id
            WHERE c.name = ?
        """, (class_or_func_name,))

        results = cursor.fetchall()

        cursor.execute("""
            SELECT 'function' as type, f.name, m.relative_path, f.start_line
            FROM functions f
            JOIN modules m ON f.module_id = m.id
            WHERE f.name = ?
        """, (class_or_func_name,))

        results.extend(cursor.fetchall())

        if not results:
            print(f"[ERROR] 未找到 '{class_or_func_name}'")
            return

        print(f"\n[FIND] '{class_or_func_name}' 的位置:")
        for type_, name, path, line in results:
            print(f"  [{type_}] {name}")
            print(f"       文件: {path}")
            print(f"       行号: 第 {line} 行")
            print()

    def show_help(self):
        """显示帮助"""
        print("\n" + "=" * 60)
        print("[HELP] 查询命令帮助")
        print("=" * 60)
        print("  项目管理:")
        print("    启动时加 -p <项目名>   - 直接指定项目")
        print("")
        print("  查询命令:")
        print("    class <关键词>       - 搜索类")
        print("    func <关键词>        - 搜索函数/方法")
        print("    mod <关键词>         - 列出匹配的模块")
        print("    modcls <关键词>      - 显示模块下的所有类")
        print("    modfunc <关键词>     - 显示模块下的所有方法")
        print("    find <名称>          - 查找类/函数的文件位置")
        print("    ls [关键词]          - 列出模块")
        print("    stats                - 显示统计信息")
        print("    help                 - 显示帮助")
        print("    q / quit / exit      - 退出程序")
        print("=" * 60)
        print()


def interactive_mode(project_name: str = None):
    """交互式查询模式"""
    print("\n" + "=" * 50)
    print("[TOOL] 代码知识库查询工具")
    print("=" * 50)
    print("\n输入 'help' 查看可用命令，'q' 退出\n")

    kb = KnowledgeBaseQuery(project_name)
    kb.show_help()

    while True:
        try:
            cmd = input("query> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[BYE] 再见!")
            break

        if not cmd:
            continue

        parts = cmd.split(maxsplit=1)
        action = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if action in ['q', 'quit', 'exit']:
            print("[BYE] 再见!")
            break

        elif action == 'help':
            kb.show_help()

        elif action == 'stats':
            kb._show_stats()

        elif action in ['class', 'c']:
            if not arg:
                print("[ERROR] 请输入搜索关键词: class <关键词>")
                continue
            kb.search_class(arg)

        elif action in ['func', 'f']:
            if not arg:
                print("[ERROR] 请输入搜索关键词: func <关键词>")
                continue
            kb.search_function(arg)

        elif action in ['modcls', 'mc']:
            if not arg:
                print("[ERROR] 请输入模块关键词: modcls <关键词>")
                continue
            kb.show_module_classes(arg)

        elif action in ['modfunc', 'mf']:
            if not arg:
                print("[ERROR] 请输入模块关键词: modfunc <关键词>")
                continue
            kb.show_module_functions(arg)

        elif action in ['mod', 'ls', 'm']:
            kb.list_modules(arg)

        elif action in ['find', 'fd']:
            if not arg:
                print("[ERROR] 请输入类名或函数名: find <名称>")
                continue
            kb.get_file_path(arg)

        else:
            print(f"[ERROR] 未知命令: {action}")
            print("输入 'help' 查看可用命令")


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

    if args:
        # 命令行模式
        action = args[0].lower()
        arg = args[1] if len(args) > 1 else ""

        kb = KnowledgeBaseQuery(project_name)

        if action in ['class', 'c'] and arg:
            kb.search_class(arg)
        elif action in ['func', 'f'] and arg:
            kb.search_function(arg)
        elif action in ['mod', 'ls']:
            kb.list_modules(arg)
        elif action in ['modcls', 'mc'] and arg:
            kb.show_module_classes(arg)
        elif action in ['modfunc', 'mf'] and arg:
            kb.show_module_functions(arg)
        elif action in ['find', 'fd'] and arg:
            kb.get_file_path(arg)
        elif action == 'list':
            projects = find_all_projects()
            print("\n" + "=" * 60)
            print("[已分析的项目列表]")
            print("=" * 60)
            for p in projects:
                import time
                mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
                print(f"  - {p.parent.name} (分析时间: {mtime})")
            print()
        else:
            print("用法:")
            print("  python kb_query.py                    # 交互式")
            print("  python kb_query.py list               # 列出所有已分析的项目")
            print("  python kb_query.py -p <项目名> class <关键词>  # 指定项目搜索类")
            print("  python kb_query.py class <关键词>     # 搜索类")
            print("  python kb_query.py func <关键词>      # 搜索函数")
            print("  python kb_query.py ls [关键词]        # 列出模块")
            print("  python kb_query.py find <名称>        # 查找文件位置")
    else:
        # 交互式模式
        interactive_mode(project_name)


if __name__ == "__main__":
    main()
