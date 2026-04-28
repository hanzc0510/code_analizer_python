import os
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
import yaml
from dotenv import load_dotenv


@dataclass
class LLMConfig:
    """LLM 配置"""
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4"
    temperature: float = 0.1
    max_tokens: int = 4000
    timeout: int = 300  # 5 分钟超时，大项目分析需要足够时间


@dataclass
class ScannerConfig:
    """扫描器配置"""
    # 目录排除规则（支持通配符）
    exclude_dirs: list = field(default_factory=lambda: [
        # 版本控制
        ".git", ".svn", ".hg", ".bzr",
        # Python 相关
        "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
        "venv", "env", ".venv", "site-packages", "dist-packages",
        # 构建输出
        "dist", "build", "target", "bin", "obj", "out", "output",
        "Debug", "Release", "x64", "x86", "bin64",
        # 第三方依赖
        "vendor", "third_party", "third-party", "3rdparty",
        "packages", "Packages", "package", "lib", "libs", "libraries",
        "external", "extern", "deps", "dependencies",
        # Java/Android
        ".gradle", ".idea", ".settings", ".classpath", ".project",
        "build", "target", "out", "gen", "generated",
        # Go
        "vendor", "pkg", "go/pkg",
        # C# / NuGet
        "packages", "Packages", "nuget", ".nuget",
        # JavaScript / Node
        "node_modules", "bower_components", "jspm_packages",
        # 前端框架构建目录
        ".next", ".nuxt", ".output", ".svelte-kit", ".astro",
        # 前端测试和工具目录
        "__tests__", "test", "tests", "__mocks__", "__fixtures__",
        ".storybook", "storybook-static", ".cypress", "cypress",
        ".playwright", "playwright",
        # 前端静态资源目录（通常不是业务代码）
        "public", "static", "assets", "dist", "build",
        # 类型定义目录
        "types", "@types", "typings",
        # 示例和文档
        "examples", "example", "demo", "docs",
        # iOS / CocoaPods
        "Pods", "Pods",
        # PHP
        "vendor",
        # Ruby
        ".bundle", "vendor/bundle",
        # 其他
        "cache", ".cache", "tmp", "temp", "logs", ".vscode", ".vs"
    ])
    # 文件排除规则
    exclude_files: list = field(default_factory=lambda: [
        # 编译产物
        "*.pyc", "*.pyo", "*.pyd", "*.so", "*.dll", "*.dylib",
        "*.exe", "*.bin", "*.class", "*.jar", "*.war", "*.ear",
        "*.obj", "*.o", "*.a", "*.lib", "*.pdb", "*.exe.config",
        # 前端压缩文件
        "*.min.js", "*.min.css", "*.map", "*.bundle.js",
        "*.chunk.js", "*.chunk.css", "runtime*.js", "vendor*.js",
        # JS 类型定义和测试文件（非业务代码）
        "*.d.ts", "*.test.js", "*.test.ts", "*.test.tsx", "*.test.jsx",
        "*.spec.js", "*.spec.ts", "*.spec.tsx", "*.spec.jsx",
        "*.e2e.js", "*.e2e.ts", "*.cy.js", "*.cy.ts",
        # JS 构建配置和工具文件
        "webpack*.js", "vite*.js", "rollup*.js", "esbuild*.js",
        "babel.config.js", ".babelrc.js", "jest.config.js",
        "vitest.config.js", "vitest.config.ts", "*.config.js",
        "*.config.ts", "*.conf.js", "*.conf.ts",
        # 前端 polyfill 和兼容性文件
        "*polyfill*.js", "es5-shim*.js", "es6-shim*.js",
        # 图片/媒体
        "*.svg", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico",
        "*.pdf", "*.bmp", "*.tiff", "*.webp", "*.mp3", "*.mp4",
        # 文档
        "*.md", "*.rst", "*.txt", "*.docx", "*.xlsx", "*.pptx",
        # 配置文件（通常不是业务代码）
        "*.json", "*.yml", "*.yaml", "*.xml", "*.ini", "*.config",
        "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        # 日志和临时文件
        "*.log", "*.tmp", "*.bak", "*.swp", "*.swo", "*.backup"
    ])
    max_file_size: int = 5 * 1024 * 1024  # 5MB


@dataclass
class AnalysisConfig:
    """分析配置"""
    extract_functions: bool = True
    extract_classes: bool = True
    extract_variables: bool = True
    build_call_graph: bool = True
    analyze_dependencies: bool = True
    use_llm: bool = True
    llm_summary: bool = True
    llm_architecture: bool = True
    llm_business: bool = True

    # ===== LLM 隐私保护配置 =====
    # LLM 分析深度: minimal(仅签名) / standard(签名+关键信息) / full(完整代码)
    llm_analysis_depth: str = "standard"
    # 是否发送函数实现代码（False=仅发送签名）
    llm_send_function_code: bool = False
    # 是否发送类的方法实现代码
    llm_send_class_code: bool = False
    # 只分析核心模块（排除 utils, helpers, infrastructure 等）
    llm_only_core_modules: bool = True
    # 跳过简单方法（getter/setter/toString/equals 等）
    llm_skip_simple_methods: bool = True


class Config:
    """全局配置管理"""

    def __init__(self, config_path: Optional[str] = None):
        load_dotenv()

        self.project_root: Optional[Path] = None
        self.output_dir: Path = Path("./output")

        self.llm: LLMConfig = LLMConfig()
        self.scanner: ScannerConfig = ScannerConfig()
        self.analysis: AnalysisConfig = AnalysisConfig()

        # 从环境变量加载 LLM 配置
        self._load_from_env()

        # 从配置文件加载
        if config_path and Path(config_path).exists():
            self._load_from_file(config_path)

    def _load_from_env(self):
        """从环境变量加载配置"""
        self.llm.api_key = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
        self.llm.base_url = os.getenv("LLM_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
        self.llm.model = os.getenv("LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-4"))

    def _load_from_file(self, config_path: str):
        """从 YAML 配置文件加载"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            if llm := data.get("llm", {}):
                self.llm.api_key = llm.get("api_key", self.llm.api_key)
                self.llm.base_url = llm.get("base_url", self.llm.base_url)
                self.llm.model = llm.get("model", self.llm.model)
                self.llm.temperature = llm.get("temperature", self.llm.temperature)
                self.llm.max_tokens = llm.get("max_tokens", self.llm.max_tokens)

            if scanner := data.get("scanner", {}):
                self.scanner.exclude_dirs = scanner.get("exclude_dirs", self.scanner.exclude_dirs)
                self.scanner.exclude_files = scanner.get("exclude_files", self.scanner.exclude_files)
                self.scanner.max_file_size = scanner.get("max_file_size", self.scanner.max_file_size)

            if analysis := data.get("analysis", {}):
                self.analysis.extract_functions = analysis.get("extract_functions", self.analysis.extract_functions)
                self.analysis.extract_classes = analysis.get("extract_classes", self.analysis.extract_classes)
                self.analysis.build_call_graph = analysis.get("build_call_graph", self.analysis.build_call_graph)
                self.analysis.use_llm = analysis.get("use_llm", self.analysis.use_llm)

        except Exception as e:
            print(f"Warning: Failed to load config file: {e}")

    def set_project_root(self, path: str):
        """设置项目根目录"""
        self.project_root = Path(path).resolve()

    def set_output_dir(self, path: str):
        """设置输出目录"""
        self.output_dir = Path(path).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "llm": {
                "api_key": "***" if self.llm.api_key else "",
                "base_url": self.llm.base_url,
                "model": self.llm.model,
                "temperature": self.llm.temperature,
                "max_tokens": self.llm.max_tokens,
            },
            "scanner": {
                "exclude_dirs": self.scanner.exclude_dirs,
                "exclude_files": self.scanner.exclude_files,
                "max_file_size": self.scanner.max_file_size,
            },
            "analysis": {
                "extract_functions": self.analysis.extract_functions,
                "extract_classes": self.analysis.extract_classes,
                "build_call_graph": self.analysis.build_call_graph,
                "use_llm": self.analysis.use_llm,
            }
        }
