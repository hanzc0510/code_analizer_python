from pathlib import Path
from typing import Dict, Optional
from ..analyzers import (
    BaseAnalyzer,
    PythonAnalyzer,
    JavaAnalyzer,
    CSharpAnalyzer,
    JSAnalyzer,
)
from ..models.project import Project, Module, Language
from ..utils.config import Config
from ..utils.logger import get_logger


logger = get_logger()


class ASTParser:
    """AST 解析器 - 管理各语言分析器，解析整个项目"""

    def __init__(self, config: Config):
        self.config = config
        self.analyzers: Dict[Language, BaseAnalyzer] = {}
        self._init_analyzers()

    def _init_analyzers(self):
        """初始化各语言分析器"""
        try:
            self.analyzers[Language.PYTHON] = PythonAnalyzer()
            logger.info("Python analyzer initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Python analyzer: {e}")

        try:
            self.analyzers[Language.JAVA] = JavaAnalyzer()
            logger.info("Java analyzer initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Java analyzer: {e}")

        try:
            self.analyzers[Language.CSHARP] = CSharpAnalyzer()
            logger.info("C# analyzer initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize C# analyzer: {e}")

        try:
            self.analyzers[Language.JAVASCRIPT] = JSAnalyzer()
            logger.info("JavaScript analyzer initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize JavaScript analyzer: {e}")

        try:
            self.analyzers[Language.TYPESCRIPT] = JSAnalyzer()
            logger.info("TypeScript analyzer initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize TypeScript analyzer: {e}")

    def parse_file(self, file_path: Path, language: Language, source_bytes: bytes) -> Optional[Module]:
        """
        解析单个文件

        Args:
            file_path: 文件路径
            language: 语言类型
            source_bytes: 源代码（字节形式，tree-sitter 需要 bytes）

        Returns:
            Module 对象
        """
        analyzer = self.analyzers.get(language)
        if not analyzer:
            logger.warning(f"No analyzer available for language: {language}")
            return None

        return analyzer.parse(source_bytes, file_path)

    def parse_project(self, project: Project, code_files: list) -> Project:
        """
        解析整个项目

        Args:
            project: Project 对象
            code_files: 代码文件列表 [(file_path, language), ...]

        Returns:
            更新后的 Project 对象
        """
        logger.info(f"Parsing {len(code_files)} files...")

        from ..core.scanner import CodeScanner

        for idx, (file_path, language) in enumerate(code_files, 1):
            if idx % 10 == 0:
                logger.info(f"Progress: {idx}/{len(code_files)} files")

            # 读取文件（必须是字节，tree-sitter 需要 bytes）
            source_bytes = CodeScanner.read_file_bytes(file_path)
            if not source_bytes:
                logger.warning(f"Failed to read file: {file_path}")
                continue

            # 解析文件
            module = self.parse_file(file_path, language, source_bytes)
            if module:
                # 设置相对路径
                try:
                    module.relative_path = str(file_path.relative_to(project.root_path))
                except ValueError:
                    module.relative_path = str(file_path)

                project.modules.append(module)

        # 更新统计信息
        project.total_files = len(project.modules)
        project.total_lines = sum(m.line_count for m in project.modules)

        # 统计各语言文件数量
        for module in project.modules:
            lang = module.language
            project.language_stats[lang] = project.language_stats.get(lang, 0) + 1

        logger.info(f"Parsing complete: {project.total_files} files, {project.total_lines} lines")
        return project

    def get_analyzer(self, language: Language) -> Optional[BaseAnalyzer]:
        """获取指定语言的分析器"""
        return self.analyzers.get(language)
