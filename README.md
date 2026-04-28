# 代码分析工具 (DeepWiki Clone)

一个强大的代码分析工具，支持多种编程语言，可以自动分析代码结构、生成调用图、理解业务逻辑，复刻 DeepWiki 的核心功能。

## 功能特性

### 多语言支持
- ✅ Python
- ✅ Java
- ✅ C#
- ✅ JavaScript / TypeScript

### 核心功能
1. **代码扫描与解析**
   - 自动识别项目中的代码文件
   - 基于 tree-sitter 的语法解析
   - 提取函数、类、变量、导入等信息

2. **调用图分析**
   - 构建函数级别的调用关系图
   - 分析模块依赖关系
   - 查找循环依赖
   - 识别入口点和核心模块

3. **LLM 深度分析** (OpenAI 兼容接口)
   - 函数摘要生成
   - 类职责分析
   - 模块功能总结
   - 项目整体架构分析
   - 业务逻辑理解和推断

4. **报告生成**
   - 完整的 Markdown 分析报告
   - 项目摘要报告
   - 单模块详细报告

## 安装

```bash
# 克隆项目
git clone <repo-url>
cd code_analysis_agent

# 安装依赖
pip install -r requirements.txt
```

## 配置

### 环境变量

创建 `.env` 文件：

```env
# LLM 配置（支持所有 OpenAI 兼容接口）
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# 公司内部 Qwen 示例
# LLM_BASE_URL=https://your-internal-endpoint.com/v1
# LLM_MODEL=qwen-plus
```

### 配置文件 (可选)

创建 `config.yaml`：

```yaml
llm:
  temperature: 0.1
  max_tokens: 4000
  timeout: 60

scanner:
  exclude_dirs:
    - node_modules
    - __pycache__
    - .git
  max_file_size: 5242880

analysis:
  use_llm: true
```

## 使用方法

### 命令行使用

```bash
# 完整分析（包括 LLM）
python main.py analyze /path/to/your/project

# 只做静态分析，跳过 LLM
python main.py analyze /path/to/your/project --skip-llm

# 指定输出目录
python main.py analyze /path/to/your/project -o ./my_report

# 查看版本
python main.py version
```

### 代码中使用

```python
import asyncio
from src.utils.config import Config
from src.core.scanner import CodeScanner
from src.core.ast_parser import ASTParser
from src.core.call_graph import CallGraph
from src.core.llm_client import LLMClient
from src.core.report_generator import ReportGenerator
from src.models.project import Project

async def main():
    config = Config()
    config.set_project_root("/path/to/project")

    # 1. 扫描
    scanner = CodeScanner(config)
    code_files = scanner.scan_directory(config.project_root)

    # 2. 解析
    project = Project(root_path=config.project_root)
    parser = ASTParser(config)
    project = parser.parse_project(project, code_files)

    # 3. 调用图
    call_graph = CallGraph(project)
    call_graph.build()

    # 4. LLM 分析
    llm = LLMClient(config)
    await llm.analyze_project(project)

    # 5. 生成报告
    reporter = ReportGenerator("./output")
    reporter.generate_full_report(project)

asyncio.run(main())
```

## 输出文件

分析完成后，输出目录包含：

### 报告文件
- `report_light.md` - 精简版报告（~12KB，推荐日常查看）
- `00_overview.md` - 项目概览
- `01_entrypoints.md` - 入口点分析
- `02_core_modules.md` - 核心模块分析
- `03_modules.md` - 所有模块详情
- `README.md` - 报告索引
- `analysis_report.md` - 原始完整版报告（较大，~4.7MB）
- `summary.md` - 项目摘要报告

### 知识库文件
- `knowledge.db` - SQLite 知识库数据库（用于增量分析和查询）

## 报告结构

完整的分析报告包含：

1. **项目概览**
   - 基本统计信息
   - 语言分布
   - 代码行数统计

2. **架构分析**
   - 项目整体架构
   - 模块依赖关系
   - 核心模块识别
   - 调用关系图

3. **业务逻辑分析**
   - 项目解决的业务问题
   - 核心业务流程
   - 业务实体和关系

4. **模块详情**
   - 每个模块的功能摘要
   - 类和方法的详细分析
   - 函数调用关系

## 技术栈

- **语法解析**: tree-sitter (多语言解析)
- **LLM 集成**: OpenAI SDK (兼容 Qwen, Claude 等)
- **图算法**: networkx (调用图分析)
- **模板引擎**: Jinja2
- **CLI**: Click
- **终端输出**: Rich

## 注意事项

1. **LLM Token 限制**：对于大型项目，LLM 分析可能需要较长时间和较多 Token
2. **tree-sitter 编译**：首次运行时 tree-sitter 会编译语言解析器
3. **分析速度**：分析时间与项目规模和是否启用 LLM 相关

## 示例

```bash
# 分析自己
python main.py analyze . --skip-llm

# 使用内部 Qwen 分析一个 Java 项目
LLM_BASE_URL=https://internal-qwen.com/v1 LLM_API_KEY=xxx LLM_MODEL=qwen-turbo python main.py analyze ~/java-project
```

## 工具使用详解

### 1. 主分析工具 - `main.py`

分析项目代码并生成报告。

```bash
# 基本用法
python main.py analyze <项目路径>

# 完整选项
python main.py analyze <项目路径> \
    --skip-llm \              # 跳过 LLM 分析，仅静态解析
    -o <输出目录> \           # 指定输出目录，默认 ./output
    --config <配置文件>       # 指定 YAML 配置文件

# 示例
python main.py analyze ./my-java-project --skip-llm -o ./reports
python main.py analyze ~/project/src --config ./config.yaml

# 查看版本
python main.py version
```

**参数说明：**

| 参数 | 缩写 | 说明 |
|------|------|------|
| `analyze <path>` | - | 指定要分析的项目根目录路径（必填） |
| `--skip-llm` | - | 跳过 LLM 深度分析，仅进行静态代码解析<br>**优点**: 速度快，不消耗 Token<br>**适用场景**: 快速了解代码结构 |
| `-o <dir>` | `--output` | 指定输出目录，**默认自动使用项目名作为子目录** `./output/<项目名>` |
| `--config <file>` | - | 使用自定义 YAML 配置文件 |
| `version` | - | 显示版本信息 |

**多项目隔离：**
不同项目的分析结果会自动存储到独立目录，不会互相覆盖：
```
output/
├── ruoyi-vue-pro/        # 项目A
│   ├── knowledge.db      # 知识库
│   ├── report_light.md   # 精简报告
│   └── ...               # 其他报告
├── my-python-project/    # 项目B
│   └── ...
└── ...
```

---

### 2. 知识库查询工具 - `kb_query.py`

从已生成的知识库中快速查询代码信息。支持**交互式**和**命令行**两种模式。

```bash
# 交互式模式（推荐）
python kb_query.py

# 命令行模式 - 直接查询
python kb_query.py <命令> [参数]
```

**可用命令：**

| 命令 | 缩写 | 功能 | 示例 |
|------|------|------|------|
| `list` | - | 列出所有已分析的项目 | `python kb_query.py list` |
| `-p <项目名>` | `--project` | **指定项目查询** | `python kb_query.py -p ruoyi class Controller` |
| `class <关键词>` | `c` | 搜索类名 | `python kb_query.py class Controller` |
| `func <关键词>` | `f` | 搜索函数/方法名 | `python kb_query.py func login` |
| `ls [关键词]` | `m` / `mod` | 列出匹配的模块 | `python kb_query.py ls service` |
| `modcls <关键词>` | `mc` | 显示模块下的所有类 | `python kb_query.py modcls auth` |
| `modfunc <关键词>` | `mf` | 显示模块下的所有方法 | `python kb_query.py modfunc user` |
| `find <名称>` | `fd` | 查找类/函数的文件位置 | `python kb_query.py find UserService` |
| `stats` | - | 显示知识库统计信息 | `python kb_query.py stats` |
| `help` | - | 显示帮助 | `python kb_query.py help` |

**多项目切换：**
```bash
# 列出所有已分析的项目
python kb_query.py list

# 指定项目查询（无需完整路径，模糊匹配即可）
python kb_query.py -p ruoyi class UserController
python kb_query.py -p myproject func login

# 交互式模式会自动列出所有项目供选择
python kb_query.py
```

**交互式模式下的操作：**

```
query> class Service          # 搜索所有 Service 类
query> func login             # 搜索所有 login 相关方法
query> ls controller          # 列出 controller 相关模块
query> find UserController    # 查找 UserController 位置
query> stats                  # 查看知识库统计
query> q                      # 退出
```

---

### 3. 智能问答工具 - `kb_chat.py`

用自然语言提问代码问题。支持纯静态搜索和 LLM 智能回答两种模式。

```bash
# 交互式模式（推荐）
python kb_chat.py

# 命令行直接提问
python kb_chat.py "这个项目的登录流程是怎样的？"
```

**配置 LLM（可选）：**

在 `.env` 文件中配置：
```env
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

配置后会自动启用智能回答，否则仅使用纯静态搜索。

**可用命令：**

| 命令 | 是否调用 LLM | 功能 | 示例 |
|------|-------------|------|------|
| `-p <项目名>` | - | **启动时指定项目** | `python kb_chat.py -p ruoyi` |
| `list` | - | 列出所有已分析的项目 | `python kb_chat.py list` |
| 直接输入问题 | ✅ 是 | 智能问答，先搜索再分析 | `ask> 这个项目的架构是怎样的？` |
| `/search <关键词>` | ❌ 否 | 仅静态搜索，0 Token | `ask> /search 权限` |
| `/class <关键词>` | ❌ 否 | 搜索类 | `ask> /class Controller` |
| `/func <关键词>` | ❌ 否 | 搜索函数/方法 | `ask> /func login` |
| `/stats` | ❌ 否 | 显示知识库统计 | `ask> /stats` |
| `/tokens` | - | 显示 Token 使用统计 | `ask> /tokens` |
| `/help` | - | 显示帮助 | `ask> /help` |
| `/q` `/quit` `/exit` | - | 退出程序 | `ask> /q` |

**Token 统计说明：**

每次 LLM 回答后会显示详细的 Token 用量：
```
[TOKEN 统计]
============================================================
  LLM 调用次数: 1
  输入 Tokens: 856
  输出 Tokens: 243
  总 Tokens: 1099
============================================================
```

---

## 典型工作流程

### 场景 1：快速了解一个新项目

```bash
# 1. 静态分析（不调用 LLM，速度快）
python main.py analyze /path/to/project --skip-llm

# 2. 查看精简报告
code output/report_light.md

# 3. 搜索核心模块
python kb_query.py class Service
python kb_query.py func login
```

### 场景 2：深度代码理解

```bash
# 1. 完整分析（需要 LLM API Key）
python main.py analyze /path/to/project

# 2. 查看架构分析报告
code output/02_core_modules.md

# 3. 智能问答
python kb_chat.py
ask> 这个项目的核心业务流程是怎样的？
```

### 场景 3：增量分析

```bash
# 第一次分析（全量）
python main.py analyze /path/to/project --skip-llm

# 修改代码后再次分析（自动增量，未修改的文件跳过）
python main.py analyze /path/to/project --skip-llm
```

---

## 开发计划

- [ ] 支持更多编程语言 (Go, Rust, PHP, C++)
- [ ] Web 界面展示
- [ ] 代码搜索和导航
- [ ] 代码复杂度分析
- [ ] 代码重复检测
- [ ] Git 提交历史分析
- [ ] 可视化交互调用图
