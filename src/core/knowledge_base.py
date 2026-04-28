"""知识库存储 - SQLite 数据库存储分析结果"""
import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime

from ..models.project import Module, FunctionDef, ClassDef, Language
from ..utils.logger import get_logger

logger = get_logger()


@dataclass
class FileCache:
    """文件缓存信息"""
    file_path: str
    file_size: int
    last_modified: float
    file_hash: str
    language: str
    analyzed_at: str


class KnowledgeBase:
    """代码知识库"""

    def __init__(self, db_path: str = "./output/knowledge.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self._init_tables()

    def _init_tables(self):
        """初始化数据库表"""
        cursor = self.conn.cursor()

        # 项目表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                root_path TEXT UNIQUE NOT NULL,
                name TEXT,
                total_files INTEGER DEFAULT 0,
                total_lines INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 文件缓存表 - 用于增量分析
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                file_path TEXT UNIQUE NOT NULL,
                file_size INTEGER,
                last_modified REAL,
                file_hash TEXT,
                language TEXT,
                analyzed_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
        """)

        # 模块表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS modules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                file_path TEXT UNIQUE NOT NULL,
                relative_path TEXT,
                language TEXT,
                line_count INTEGER,
                size INTEGER,
                summary TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
        """)

        # 导入表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_id INTEGER,
                module_name TEXT,
                alias TEXT,
                FOREIGN KEY (module_id) REFERENCES modules(id)
            )
        """)

        # 类表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_id INTEGER,
                name TEXT NOT NULL,
                start_line INTEGER,
                end_line INTEGER,
                bases TEXT,  -- JSON 数组
                modifiers TEXT,  -- JSON 数组
                summary TEXT,
                FOREIGN KEY (module_id) REFERENCES modules(id)
            )
        """)

        # 方法/函数表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS functions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_id INTEGER,
                class_id INTEGER,  -- NULL 表示模块级函数
                name TEXT NOT NULL,
                start_line INTEGER,
                end_line INTEGER,
                parameters TEXT,  -- JSON 数组
                return_type TEXT,
                modifiers TEXT,  -- JSON 数组
                calls TEXT,  -- JSON 数组 - 调用的函数名
                summary TEXT,
                FOREIGN KEY (module_id) REFERENCES modules(id),
                FOREIGN KEY (class_id) REFERENCES classes(id)
            )
        """)

        # 依赖关系表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_id INTEGER,
                depends_on TEXT,  -- 依赖的模块路径
                FOREIGN KEY (module_id) REFERENCES modules(id)
            )
        """)

        # 项目元数据表 - 存储调用图、配置等
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                key TEXT NOT NULL,
                value TEXT,  -- JSON 存储
                FOREIGN KEY (project_id) REFERENCES projects(id),
                UNIQUE(project_id, key)
            )
        """)

        self.conn.commit()

    def save_metadata(self, project_id: int, key: str, value: Any):
        """保存项目元数据"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO project_metadata (project_id, key, value)
            VALUES (?, ?, ?)
        """, (project_id, key, json.dumps(value, ensure_ascii=False)))
        self.conn.commit()

    def get_or_create_project(self, root_path: str, name: str = None) -> int:
        """获取或创建项目"""
        cursor = self.conn.cursor()

        cursor.execute("SELECT id FROM projects WHERE root_path = ?", (root_path,))
        row = cursor.fetchone()

        if row:
            return row[0]

        cursor.execute(
            "INSERT INTO projects (root_path, name) VALUES (?, ?)",
            (root_path, name or Path(root_path).name)
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_project_stats(self, project_id: int, total_files: int, total_lines: int):
        """更新项目统计"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE projects
            SET total_files = ?, total_lines = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (total_files, total_lines, project_id))
        self.conn.commit()

    def get_file_cache(self, file_path: str) -> Optional[FileCache]:
        """获取文件缓存信息"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT file_path, file_size, last_modified, file_hash, language, analyzed_at
            FROM file_cache WHERE file_path = ?
        """, (file_path,))
        row = cursor.fetchone()
        if row:
            return FileCache(
                file_path=row[0],
                file_size=row[1],
                last_modified=row[2],
                file_hash=row[3],
                language=row[4],
                analyzed_at=row[5]
            )
        return None

    def is_file_unchanged(self, file_path: str, file_size: int, last_modified: float) -> bool:
        """检查文件是否未变更（可以跳过分析）"""
        cache = self.get_file_cache(file_path)
        if not cache:
            return False
        return cache.file_size == file_size and cache.last_modified == last_modified

    def save_module(self, project_id: int, module: Module) -> int:
        """保存模块分析结果"""
        cursor = self.conn.cursor()

        # 删除旧数据
        cursor.execute("DELETE FROM modules WHERE file_path = ?", (str(module.file_path),))
        module_id = cursor.lastrowid

        # 插入新数据
        cursor.execute("""
            INSERT INTO modules (
                project_id, file_path, relative_path, language,
                line_count, size, summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            str(module.file_path),
            module.relative_path,
            module.language.value,
            module.line_count,
            module.size,
            module.summary
        ))
        module_id = cursor.lastrowid

        # 保存导入
        for imp in module.imports:
            cursor.execute("""
                INSERT INTO imports (module_id, module_name, alias)
                VALUES (?, ?, ?)
            """, (module_id, imp.module, getattr(imp, 'alias', '')))

        # 保存类
        for cls in module.classes:
            class_id = self._save_class(cursor, module_id, cls)

            # 保存方法
            for method in cls.methods:
                self._save_function(cursor, module_id, method, class_id)

        # 保存模块级函数
        for func in module.functions:
            self._save_function(cursor, module_id, func, None)

        # 保存依赖
        for dep in module.depends_on:
            cursor.execute("""
                INSERT INTO dependencies (module_id, depends_on)
                VALUES (?, ?)
            """, (module_id, dep))

        # 更新文件缓存
        cursor.execute("""
            INSERT OR REPLACE INTO file_cache (
                project_id, file_path, file_size, last_modified,
                file_hash, language, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            str(module.file_path),
            module.size,
            module.file_path.stat().st_mtime if module.file_path.exists() else 0,
            "",  # TODO: 计算文件 hash
            module.language.value,
            datetime.now().isoformat()
        ))

        self.conn.commit()
        return module_id

    def _save_class(self, cursor, module_id: int, cls: ClassDef) -> int:
        """保存类"""
        cursor.execute("""
            INSERT INTO classes (
                module_id, name, start_line, end_line,
                bases, modifiers, summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            module_id,
            cls.name,
            cls.start_line,
            cls.end_line,
            json.dumps(cls.bases, ensure_ascii=False),
            json.dumps(cls.modifiers, ensure_ascii=False),
            cls.summary
        ))
        return cursor.lastrowid

    def _save_function(self, cursor, module_id: int, func: FunctionDef, class_id: Optional[int]):
        """保存函数/方法"""
        params = [{"name": p.name, "type": getattr(p, 'type_hint', '')} for p in func.parameters]

        cursor.execute("""
            INSERT INTO functions (
                module_id, class_id, name, start_line, end_line,
                parameters, return_type, modifiers, calls, summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            module_id,
            class_id,
            func.name,
            func.start_line,
            func.end_line,
            json.dumps(params, ensure_ascii=False),
            func.return_type,
            json.dumps(func.modifiers, ensure_ascii=False),
            json.dumps(func.calls, ensure_ascii=False),
            func.summary
        ))

    # 查询方法
    def search_class(self, class_name: str, project_id: int = None) -> List[Dict]:
        """搜索类"""
        cursor = self.conn.cursor()
        query = "SELECT * FROM classes WHERE name LIKE ?"
        params = [f'%{class_name}%']

        if project_id:
            query += " AND module_id IN (SELECT id FROM modules WHERE project_id = ?)"
            params.append(project_id)

        cursor.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def search_function(self, func_name: str, project_id: int = None) -> List[Dict]:
        """搜索函数/方法"""
        cursor = self.conn.cursor()
        query = "SELECT * FROM functions WHERE name LIKE ?"
        params = [f'%{func_name}%']

        if project_id:
            query += " AND module_id IN (SELECT id FROM modules WHERE project_id = ?)"
            params.append(project_id)

        cursor.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_module_by_path(self, relative_path: str, project_id: int = None) -> Optional[Dict]:
        """根据路径获取模块"""
        cursor = self.conn.cursor()
        query = "SELECT * FROM modules WHERE relative_path = ?"
        params = [relative_path]

        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)

        cursor.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        row = cursor.fetchone()
        if row:
            return dict(zip(columns, row))
        return None

    def get_project_summary(self, project_id: int) -> Dict:
        """获取项目摘要"""
        cursor = self.conn.cursor()

        cursor.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        proj_columns = [desc[0] for desc in cursor.description]
        project = dict(zip(proj_columns, cursor.fetchone()))

        # 统计类数量
        cursor.execute("""
            SELECT COUNT(*) FROM classes c
            JOIN modules m ON c.module_id = m.id
            WHERE m.project_id = ?
        """, (project_id,))
        class_count = cursor.fetchone()[0]

        # 统计函数数量
        cursor.execute("""
            SELECT COUNT(*) FROM functions f
            JOIN modules m ON f.module_id = m.id
            WHERE m.project_id = ?
        """, (project_id,))
        func_count = cursor.fetchone()[0]

        return {
            "project": project,
            "class_count": class_count,
            "function_count": func_count
        }

    def close(self):
        """关闭数据库连接"""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
