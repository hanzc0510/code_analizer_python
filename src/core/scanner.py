import fnmatch
import os
from pathlib import Path
from typing import List, Optional, Tuple
from ..models.project import Language
from ..utils.config import Config
from ..utils.logger import get_logger


logger = get_logger()


class CodeScanner:
    """代码扫描器 - 遍历并识别项目中的代码文件"""

    # 文件扩展名到语言的映射
    EXTENSION_MAP = {
        '.py': Language.PYTHON,
        '.java': Language.JAVA,
        '.cs': Language.CSHARP,
        '.js': Language.JAVASCRIPT,
        '.jsx': Language.JAVASCRIPT,
        '.ts': Language.TYPESCRIPT,
        '.tsx': Language.TYPESCRIPT,
    }

    def __init__(self, config: Config):
        self.config = config
        self.exclude_patterns = config.scanner.exclude_dirs
        self.exclude_file_patterns = config.scanner.exclude_files
        self.max_file_size = config.scanner.max_file_size

    def scan_directory(self, root_path: str) -> List[Tuple[Path, Language]]:
        """
        扫描目录，返回所有代码文件

        Args:
            root_path: 项目根目录路径

        Returns:
            文件路径和对应语言的列表
        """
        root = Path(root_path).resolve()
        if not root.exists():
            raise FileNotFoundError(f"Directory not found: {root_path}")

        logger.info(f"Scanning directory: {root}")
        code_files = []
        skipped_dirs = 0
        skipped_files = 0

        for dirpath, dirnames, filenames in os.walk(root):
            current_dir = Path(dirpath)

            # 过滤掉排除的目录 - 支持完整路径匹配
            filtered_dirs = []
            for d in dirnames:
                full_subdir = current_dir / d
                if self._should_exclude_dir(full_subdir, root):
                    skipped_dirs += 1
                else:
                    filtered_dirs.append(d)
            dirnames[:] = filtered_dirs

            for filename in filenames:
                file_path = current_dir / filename

                # 检查是否应该排除该文件
                if self._should_exclude_file(filename, file_path, root):
                    skipped_files += 1
                    continue

                # 检查文件大小
                try:
                    file_size = file_path.stat().st_size
                    if file_size > self.max_file_size:
                        logger.debug(f"Skipping large file: {file_path} ({file_size} bytes)")
                        skipped_files += 1
                        continue
                except OSError:
                    continue

                # 识别语言
                language = self._detect_language(filename)
                if language == Language.UNKNOWN:
                    skipped_files += 1
                    continue

                code_files.append((file_path, language))

        logger.info(f"Found {len(code_files)} code files (skipped {skipped_dirs} dirs, {skipped_files} files)")
        return code_files, {"skipped_dirs": skipped_dirs, "skipped_files": skipped_files}

    def _should_exclude_dir(self, full_dir_path: Path, root_path: Path) -> bool:
        """
        判断是否应该排除目录（支持相对路径匹配）

        Args:
            full_dir_path: 目录完整路径
            root_path: 项目根路径
        """
        dirname = full_dir_path.name
        try:
            rel_path = full_dir_path.relative_to(root_path).as_posix()
        except ValueError:
            rel_path = full_dir_path.as_posix()

        for pattern in self.exclude_patterns:
            # 1. 直接匹配目录名（最常见情况）
            if fnmatch.fnmatch(dirname, pattern):
                return True
            # 2. 匹配相对路径的任意部分（如 `*/packages/*` 排除所有子包目录）
            if fnmatch.fnmatch(rel_path, f"*/{pattern}/*"):
                return True
            # 3. 路径以排除目录开头（如 `packages/*`）
            if fnmatch.fnmatch(rel_path, f"{pattern}/*"):
                return True
            # 4. 相对路径完全匹配
            if fnmatch.fnmatch(rel_path, pattern):
                return True
        return False

    def _should_exclude_file(self, filename: str, full_file_path: Path, root_path: Path) -> bool:
        """
        判断是否应该排除文件

        Args:
            filename: 文件名
            full_file_path: 文件完整路径
            root_path: 项目根路径
        """
        # 1. 检查文件名规则
        for pattern in self.exclude_file_patterns:
            if fnmatch.fnmatch(filename, pattern):
                return True

        # 2. 检查文件是否在被排除的子目录中
        try:
            rel_path = full_file_path.relative_to(root_path).as_posix()
            for pattern in self.exclude_patterns:
                # 检查路径中是否包含排除的目录
                if fnmatch.fnmatch(rel_path, f"*/{pattern}/*"):
                    return True
        except ValueError:
            pass

        return False

    def _detect_language(self, filename: str) -> Language:
        """根据文件名检测语言"""
        ext = Path(filename).suffix.lower()
        return self.EXTENSION_MAP.get(ext, Language.UNKNOWN)

    @staticmethod
    def read_file_bytes(file_path: Path) -> Optional[bytes]:
        """
        读取文件内容为字节，用于 tree-sitter 解析

        Args:
            file_path: 文件路径

        Returns:
            文件字节内容，读取失败返回 None
        """
        try:
            with open(file_path, 'rb') as f:
                return f.read()
        except OSError:
            return None

    @staticmethod
    def read_file(file_path: Path, encoding: str = 'utf-8') -> Optional[str]:
        """
        读取文件内容为字符串，尝试多种编码

        Args:
            file_path: 文件路径
            encoding: 首选编码

        Returns:
            文件内容，读取失败返回 None
        """
        encodings = [encoding, 'gbk', 'gb2312', 'latin-1']

        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
            except OSError:
                return None

        return None

    def get_language_stats(self, code_files: List[Tuple[Path, Language]]) -> dict:
        """获取语言统计信息"""
        stats = {}
        for _, lang in code_files:
            stats[lang] = stats.get(lang, 0) + 1
        return stats
