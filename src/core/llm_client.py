import asyncio
import json
from typing import List, Dict, Optional, Any
from openai import AsyncOpenAI
import tiktoken
from ..models.project import Project, Module, FunctionDef, ClassDef
from ..utils.config import Config
from ..utils.logger import get_logger


logger = get_logger()


class LLMClient:
    """LLM 客户端 - 封装 OpenAI 兼容接口"""

    # 系统提示词
    SYSTEM_PROMPTS = {
        "function_summary": """
你是一位资深代码分析师。请简要分析这个函数，用中文输出：
1. 函数的核心功能
2. 主要逻辑步骤
3. 关键注意点

请简洁明了，不超过 200 字。
""",
        "class_summary": """
你是一位资深代码分析师。请简要分析这个类，用中文输出：
1. 类的职责和定位
2. 核心方法说明
3. 设计特点

请简洁明了，不超过 300 字。
""",
        "module_summary": """
你是一位资深代码分析师。请简要分析这个代码模块，用中文输出：
1. 模块的主要功能和定位
2. 核心组件（类/函数）概述
3. 依赖关系和交互方式

请简洁明了，不超过 400 字。
""",
        "architecture": """
你是一位资深软件架构师。请分析这个代码项目，用中文输出架构分析：
1. 项目整体架构概述
2. 核心模块及其职责
3. 关键设计模式和技术选型
4. 数据流和调用关系
5. 架构优点和潜在改进点

请结构化输出，内容充实但不冗余。
""",
        "business_logic": """
你是一位资深业务分析师。请分析这个代码项目的业务逻辑，用中文输出：
1. 项目解决的业务问题
2. 核心业务流程
3. 关键业务实体和它们的关系
4. 业务规则和约束
5. 业务价值和应用场景

请结构化输出，基于代码实际内容分析，不要凭空猜测。
"""
    }

    def __init__(self, config: Config):
        self.config = config
        self.client: Optional[AsyncOpenAI] = None
        self.model = config.llm.model
        self.tokenizer = None
        self.llm_enabled = False

        if config.analysis.use_llm:
            try:
                self._init_client()
                self.llm_enabled = bool(self.client)
            except Exception as e:
                logger.warning(f"LLM client init failed: {e}")
                self.llm_enabled = False

            try:
                # 尝试按模型名获取编码器，失败则用通用编码器
                self.tokenizer = tiktoken.encoding_for_model(config.llm.model)
            except:
                # 对于不识别的模型（如 doubao, qwen 等），使用 cl100k_base 编码器
                # 这是 gpt-3.5/gpt-4 使用的编码器，兼容大多数场景
                self.tokenizer = tiktoken.get_encoding("cl100k_base")

    def _init_client(self):
        """初始化 OpenAI 客户端"""
        if not self.config.llm.api_key:
            logger.warning("No LLM API key configured. LLM features will be disabled.")
            return

        self.client = AsyncOpenAI(
            api_key=self.config.llm.api_key,
            base_url=self.config.llm.base_url,
            timeout=self.config.llm.timeout,
        )
        logger.info(f"LLM client initialized with model: {self.config.llm.model}")

    def _count_tokens(self, text: str) -> int:
        """计算 token 数量"""
        if not self.tokenizer:
            return len(text) // 4  # 粗略估计
        return len(self.tokenizer.encode(text))

    def _truncate_code(self, code: str, max_tokens: int = 3000) -> str:
        """截断代码以适应 token 限制"""
        if self._count_tokens(code) <= max_tokens:
            return code

        # 简单的截断策略：保留头部和尾部
        lines = code.split('\n')
        if len(lines) > 50:
            return '\n'.join(lines[:30]) + '\n\n... [TRUNCATED] ...\n\n' + '\n'.join(lines[-20:])
        return '\n'.join(lines[:30])

    async def _call_llm(self, prompt: str, system_prompt: str = "") -> str:
        """调用 LLM（带完整错误诊断）"""
        if not self.client:
            logger.warning("LLM client not initialized, skipping")
            return ""

        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Debug: 打印发送给 LLM 的消息
            logger.debug(f"📤 Sending to LLM ({len(prompt)} chars)...")
            logger.debug(f"   Model: {self.config.llm.model}")
            logger.debug(f"   Base URL: {self.config.llm.base_url}")
            if system_prompt:
                logger.debug(f"   System prompt: {system_prompt[:100]}...")

            response = await self.client.chat.completions.create(
                model=self.config.llm.model,
                messages=messages,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
                timeout=self.config.llm.timeout,
            )

            result = response.choices[0].message.content or ""

            logger.debug(f"📥 Received from LLM ({len(result)} chars)")
            logger.debug(f"   Response (first 200 chars): {result[:200]}...")
            if hasattr(response, 'usage') and response.usage:
                logger.debug(f"   Token usage: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, total={response.usage.total_tokens}")

            return result

        except Exception as e:
            error_str = str(e)
            logger.error(f"❌ LLM call failed!")
            logger.error(f"   Model: {self.config.llm.model}")
            logger.error(f"   Base URL: {self.config.llm.base_url}")
            logger.error(f"   Error: {error_str}")

            # 尝试提取更有用的错误信息
            if "status_code" in error_str or "Status" in error_str:
                logger.error("   → 这是 HTTP 状态码错误，请检查 API 配置是否正确")
            if "Internal Server Error" in error_str or "500" in error_str:
                logger.error("   → 服务端内部错误，可能是模型过载或不支持该请求格式")
            if "timeout" in error_str.lower():
                logger.error("   → 请求超时，网络可能不稳定或模型响应太慢")
            if "json" in error_str.lower() and "decode" in error_str.lower():
                logger.error("   → API 返回了非 JSON 格式（通常是网关错误、登录页面等）")

            return ""

    async def summarize_function(self, func: FunctionDef) -> str:
        """生成函数摘要"""
        if not self.client:
            return ""

        code = self._truncate_code(func.content, 2000)
        prompt = f"""函数名: {func.name}
参数: {', '.join(p.name for p in func.parameters)}
返回类型: {func.return_type}

代码:
{code}

请分析这个函数。"""

        return await self._call_llm(prompt, self.SYSTEM_PROMPTS["function_summary"])

    async def summarize_class(self, cls: ClassDef) -> str:
        """生成类摘要"""
        if not self.client:
            return ""

        method_names = ', '.join(m.name for m in cls.methods)
        code = self._truncate_code(cls.content, 3000)
        prompt = f"""类名: {cls.name}
父类: {', '.join(cls.bases) if cls.bases else 'None'}
方法: {method_names}

代码:
{code}

请分析这个类。"""

        return await self._call_llm(prompt, self.SYSTEM_PROMPTS["class_summary"])

    async def summarize_module(self, module: Module) -> str:
        """生成模块摘要"""
        if not self.client:
            return ""

        func_names = ', '.join(f.name for f in module.functions)
        class_names = ', '.join(c.name for c in module.classes)
        imports = ', '.join(i.module for i in module.imports[:10])

        # 取前几个关键函数的代码
        code_snippets = []
        for func in module.functions[:3]:
            code_snippets.append(f"--- {func.name} ---\n{self._truncate_code(func.content, 500)}")
        for cls in module.classes[:2]:
            code_snippets.append(f"--- {cls.name} ---\n{self._truncate_code(cls.content, 800)}")

        prompt = f"""模块: {module.relative_path}
函数: {func_names or 'None'}
类: {class_names or 'None'}
导入: {imports or 'None'}

关键代码片段:
{chr(10).join(code_snippets)}

请分析这个模块。"""

        return await self._call_llm(prompt, self.SYSTEM_PROMPTS["module_summary"])

    async def analyze_architecture(self, project: Project) -> str:
        """分析项目架构"""
        if not self.client:
            return ""

        # 收集项目信息
        lang_stats = {k.value: v for k, v in project.language_stats.items()}
        module_info = []
        for module in project.modules[:20]:  # 最多 20 个模块
            func_count = len(module.functions)
            for cls in module.classes:
                func_count += len(cls.methods)
            module_info.append(
                f"- {module.relative_path}: {len(module.classes)} classes, {func_count} functions"
            )

        prompt = f"""项目概览:
- 总文件数: {project.total_files}
- 代码行数: {project.total_lines}
- 语言分布: {json.dumps(lang_stats, ensure_ascii=False)}

模块列表:
{chr(10).join(module_info)}

请分析这个项目的整体架构。"""

        return await self._call_llm(prompt, self.SYSTEM_PROMPTS["architecture"])

    async def analyze_business_logic(self, project: Project) -> str:
        """分析业务逻辑"""
        if not self.client:
            return ""

        # 收集核心模块信息
        module_details = []
        for module in project.modules[:15]:
            if module.summary:
                module_details.append(f"## {module.relative_path}\n{module.summary}")

        prompt = f"""项目模块分析:

{chr(10).join(module_details)}

请基于以上模块分析，推断整个项目的业务逻辑。"""

        return await self._call_llm(prompt, self.SYSTEM_PROMPTS["business_logic"])

    async def analyze_project(self, project: Project, progress_callback=None):
        """
        完整分析项目（批量优化 + 隐私保护版）
        - 批量分析方法和类，大幅减少 API 调用次数
        - 隐私保护：默认只发送签名，不发送实现代码
        """
        if not self.client:
            logger.info("LLM not configured, skipping analysis")
            return

        cfg = self.config.analysis
        logger.info("🚀 Starting LLM analysis (batch mode)...")
        logger.info(f"   🔒 Privacy mode: llm_analysis_depth={cfg.llm_analysis_depth}")
        logger.info(f"   🔒 Send function code: {cfg.llm_send_function_code}")
        logger.info(f"   🔒 Skip simple methods: {cfg.llm_skip_simple_methods}")

        # ========== 1. 筛选 + 批量分析函数 ==========
        all_funcs = self._filter_functions_for_analysis(project.get_all_functions())
        if all_funcs:
            logger.info(f"📊 Batch analyzing {len(all_funcs)} functions...")
            await self._batch_analyze_functions(all_funcs, progress_callback)

        # ========== 2. 筛选 + 批量分析类 ==========
        all_classes = self._filter_classes_for_analysis(project.get_all_classes())
        if all_classes:
            logger.info(f"📊 Batch analyzing {len(all_classes)} classes...")
            await self._batch_analyze_classes(all_classes, progress_callback)

        # ========== 3. 批量分析模块 ==========
        logger.info(f"📊 Analyzing {len(project.modules)} modules...")
        await self._batch_analyze_modules(project.modules, progress_callback)

        # ========== 4. 架构分析 ==========
        logger.info("🏗️  Analyzing architecture...")
        project.architecture_summary = await self.analyze_architecture(project)

        # ========== 5. 业务逻辑分析 ==========
        logger.info("💼 Analyzing business logic...")
        project.business_overview = await self.analyze_business_logic(project)

        logger.info("✅ LLM analysis complete!")

    def _filter_functions_for_analysis(self, funcs: list) -> list:
        """筛选需要分析的函数，过滤简单方法节省 Token 并保护隐私"""
        if not self.config.analysis.llm_skip_simple_methods:
            return funcs

        SIMPLE_NAMES = {
            'get', 'set', 'is', 'to_string', 'tostring', 'equals', 'hashcode',
            'hash', 'clone', 'compare', 'compareto', 'equals', 'equal',
            'gethashcode', 'tostring', 'dispose', 'close', 'init',
            'ctor', 'constructor', '__init__'
        }

        filtered = []
        skipped = 0
        for func in funcs:
            name = func.name.lower().strip('_')
            # 跳过 getter/setter/toString 等简单方法
            if name in SIMPLE_NAMES:
                skipped += 1
                func.summary = f"{func.name}（简单访问器方法）"
                continue

            # 跳过参数很少 + 代码很短的方法
            if len(func.parameters) <= 1 and (func.end_line - func.start_line) < 5:
                skipped += 1
                func.summary = f"{func.name}（简单方法）"
                continue

            filtered.append(func)

        if skipped > 0:
            logger.info(f"   ⏩ 跳过 {skipped} 个简单方法")
        return filtered

    def _filter_classes_for_analysis(self, classes: list) -> list:
        """筛选需要分析的类"""
        # 按方法数排序，优先分析大的核心类
        sorted_classes = sorted(classes, key=lambda c: -len(c.methods))

        # 只分析 Top 60% 的类（方法多的通常是核心类）
        keep_count = max(5, int(len(sorted_classes) * 0.6))
        result = sorted_classes[:keep_count]

        skipped = len(sorted_classes) - len(result)
        if skipped > 0:
            logger.info(f"   ⏩ 跳过 {skipped} 个简单/工具类")
            for cls in sorted_classes[keep_count:]:
                cls.summary = f"{cls.name}（{len(cls.methods)}个方法）"

        return result

    async def _batch_analyze_functions(self, funcs: list, progress_callback=None):
        """批量分析函数：一次塞多个，大幅减少 API 调用 + 隐私保护"""
        BATCH_SIZE = 15  # 每批 15 个函数
        TOKEN_LIMIT = 4000  # 降低上限，因为只发签名

        batches = []
        current_batch = []
        current_tokens = 0

        # 先分桶
        for func in funcs:
            func_tokens = self._count_tokens(func.name or "") + 50  # 只估算签名，不估算代码
            if current_tokens + func_tokens > TOKEN_LIMIT or len(current_batch) >= BATCH_SIZE:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
            current_batch.append(func)
            current_tokens += func_tokens
        if current_batch:
            batches.append(current_batch)

        logger.info(f"   Split into {len(batches)} batches (avg {len(funcs)/len(batches):.1f} funcs/batch)")
        logger.info(f"   🔒 Privacy mode: NOT sending implementation code to LLM")

        processed = 0
        send_code = self.config.analysis.llm_send_function_code

        for batch_idx, batch in enumerate(batches):
            # 构建批量 prompt（隐私保护版：只发签名，不发代码）
            parts = []
            for idx, func in enumerate(batch):
                parts.append(f"--- FUNCTION #{idx+1}: {func.name} ---")
                parts.append(f"Lines: {func.start_line}-{func.end_line}")
                if func.modifiers:
                    parts.append(f"Modifiers: {' '.join(func.modifiers)}")
                if func.parameters:
                    params = ', '.join(f"{p.type_hint or 'object'} {p.name}" for p in func.parameters[:10])
                    parts.append(f"Params: ({params})")
                if func.return_type:
                    parts.append(f"Return: {func.return_type}")

                # ===== 隐私保护：默认不发代码 =====
                # 只有明确配置才发送代码内容
                if send_code and func.content:
                    parts.append("Code snippet:")
                    code_lines = func.content.split('\n', 30)[:30]
                    parts.append('\n'.join(code_lines))
                parts.append("")

            batch_prompt = f"""
请批量分析以下 {len(batch)} 个函数，输出 JSON 格式：
要求：
1. 每个函数用一句话说明核心作用（不超过 50 字）
2. 只输出 JSON，不要其他说明
3. 格式：{{"函数全名": "摘要", ...}}

{'\n'.join(parts)}
"""
            # 调用 LLM
            try:
                result = await self._call_llm(batch_prompt, self.SYSTEM_PROMPTS["function_summary"])
                # 解析结果（容错处理）
                summaries = self._parse_json_result(result, len(batch))

                # 分配摘要
                for idx, func in enumerate(batch):
                    key = func.name
                    # 尝试各种可能的 key
                    if key in summaries:
                        func.summary = summaries[key]
                    elif key.lower() in summaries:
                        func.summary = summaries[key.lower()]
                    else:
                        # 按顺序匹配
                        keys = list(summaries.keys())
                        if idx < len(keys):
                            func.summary = summaries[keys[idx]]
                        else:
                            # 提取失败，fallback 到单行
                            func.summary = f"{func.name} 函数"

            except Exception as e:
                logger.warning(f"   Batch {batch_idx+1} failed: {e}")
                # 失败时给个默认值
                for func in batch:
                    func.summary = f"{func.name}"

            processed += len(batch)
            if progress_callback:
                progress_callback("function", processed, len(funcs))

            logger.debug(f"   Batch {batch_idx+1}/{len(batches)} complete")

    async def _batch_analyze_classes(self, classes: list, progress_callback=None):
        """批量分析类"""
        BATCH_SIZE = 8  # 每批 8 个类
        TOKEN_LIMIT = 8000

        batches = []
        current_batch = []
        current_tokens = 0

        for cls in classes:
            cls_tokens = self._count_tokens(f"{cls.name} {len(cls.methods)} methods")
            if current_tokens + cls_tokens > TOKEN_LIMIT or len(current_batch) >= BATCH_SIZE:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
            current_batch.append(cls)
            current_tokens += cls_tokens
        if current_batch:
            batches.append(current_batch)

        logger.info(f"   Split into {len(batches)} batches (avg {len(classes)/len(batches):.1f} classes/batch)")
        logger.info(f"   🔒 Privacy mode: NOT sending implementation code to LLM")

        processed = 0
        send_code = self.config.analysis.llm_send_class_code

        for batch_idx, batch in enumerate(batches):
            parts = []
            for idx, cls in enumerate(batch):
                parts.append(f"--- CLASS #{idx+1}: {cls.name} ---")
                parts.append(f"Lines: {cls.start_line}-{cls.end_line}")
                if cls.modifiers:
                    parts.append(f"Modifiers: {' '.join(cls.modifiers)}")
                parts.append(f"Methods count: {len(cls.methods)}")
                if cls.methods:
                    # 只发方法签名，不发代码
                    method_sigs = []
                    for m in cls.methods[:15]:
                        params = ', '.join(p.name for p in m.parameters[:5])
                        sig = f"{m.name}({params})"
                        method_sigs.append(sig)
                    parts.append(f"Method signatures: {'; '.join(method_sigs)}")
                if cls.bases:
                    parts.append(f"Inherits: {', '.join(cls.bases)}")

                # 只有明确配置才发送代码内容
                if send_code and cls.methods:
                    parts.append("Sample code (first 3 methods):")
                    for m in cls.methods[:3]:
                        if m.content:
                            code_lines = m.content.split('\n', 15)[:15]
                            parts.append(f"  {m.name}:")
                            parts.append(f"    {'    '.join(code_lines)}")
                parts.append("")

            batch_prompt = f"""
请批量分析以下 {len(batch)} 个类，输出 JSON 格式：
要求：
1. 每个类用一句话说明核心职责（不超过 60 字）
2. 只输出 JSON，不要其他说明
3. 格式：{{"类名": "摘要", ...}}

{'\n'.join(parts)}
"""
            try:
                result = await self._call_llm(batch_prompt, self.SYSTEM_PROMPTS["class_summary"])
                summaries = self._parse_json_result(result, len(batch))

                for idx, cls in enumerate(batch):
                    key = cls.name
                    if key in summaries:
                        cls.summary = summaries[key]
                    elif key.lower() in summaries:
                        cls.summary = summaries[key.lower()]
                    else:
                        keys = list(summaries.keys())
                        if idx < len(keys):
                            cls.summary = summaries[keys[idx]]
                        else:
                            cls.summary = f"{cls.name} 类，{len(cls.methods)} 个方法"
            except Exception as e:
                logger.warning(f"   Batch {batch_idx+1} failed: {e}")
                for cls in batch:
                    cls.summary = f"{cls.name} 类，{len(cls.methods)} 个方法"

            processed += len(batch)
            if progress_callback:
                progress_callback("class", processed, len(classes))

    async def _batch_analyze_modules(self, modules: list, progress_callback=None):
        """批量分析模块"""
        # 模块比较大，保守一点，每批 5 个
        BATCH_SIZE = 5

        batches = []
        for i in range(0, len(modules), BATCH_SIZE):
            batches.append(modules[i:i+BATCH_SIZE])

        logger.info(f"   Split into {len(batches)} batches")

        processed = 0
        for batch_idx, batch in enumerate(batches):
            parts = []
            for idx, module in enumerate(batch):
                parts.append(f"--- MODULE #{idx+1}: {module.relative_path} ---")
                parts.append(f"Classes: {len(module.classes)}")
                parts.append(f"Functions: {len(module.functions)}")
                if module.classes:
                    parts.append(f"Class list: {', '.join(c.name for c in module.classes[:15])}")
                if module.functions:
                    parts.append(f"Function list: {', '.join(f.name for f in module.functions[:10])}")
                parts.append("")

            batch_prompt = f"""
请批量分析以下 {len(batch)} 个代码模块，输出 JSON 格式：
要求：
1. 每个模块用 1-2 句话说明该模块的业务职责
2. 只输出 JSON，不要其他说明
3. 格式：{{"模块路径": "摘要", ...}}

{'\n'.join(parts)}
"""
            try:
                result = await self._call_llm(batch_prompt, self.SYSTEM_PROMPTS["module_summary"])
                summaries = self._parse_json_result(result, len(batch))

                for idx, module in enumerate(batch):
                    key = module.relative_path
                    if key in summaries:
                        module.summary = summaries[key]
                    elif key.lower() in summaries:
                        module.summary = summaries[key.lower()]
                    else:
                        # 按文件名匹配
                        found = False
                        for k, v in summaries.items():
                            if k in key or key.split('/')[-1] in k or key.split('\\')[-1] in k:
                                module.summary = v
                                found = True
                                break
                        if not found:
                            keys = list(summaries.keys())
                            if idx < len(keys):
                                module.summary = summaries[keys[idx]]
                            else:
                                module.summary = f"{module.relative_path}：{len(module.classes)}个类，{len(module.functions)}个函数"
            except Exception as e:
                logger.warning(f"   Batch {batch_idx+1} failed: {e}")
                for module in batch:
                    module.summary = f"{module.relative_path}：{len(module.classes)}个类，{len(module.functions)}个函数"

            processed += len(batch)
            if progress_callback:
                progress_callback("module", processed, len(modules))

    def _parse_json_result(self, result: str, expected_count: int) -> dict:
        """智能解析 LLM 返回的 JSON，处理各种格式问题"""
        if not result:
            return {}

        # 1. 先尝试直接解析
        try:
            import json
            return json.loads(result)
        except:
            pass

        # 2. 尝试提取 ```json ... ``` 块
        if "```json" in result:
            start = result.find("```json") + 7
            end = result.find("```", start)
            if end > start:
                try:
                    import json
                    return json.loads(result[start:end].strip())
                except:
                    pass

        # 3. 尝试提取任何 {} 块
        if "{" in result and "}" in result:
            start = result.find("{")
            end = result.rfind("}") + 1
            try:
                import json
                return json.loads(result[start:end].strip())
            except:
                pass

        logger.warning(f"   JSON parse failed, falling back to raw text (first 200 chars: {result[:200]}...)")
        return {}

    def _count_tokens(self, text: str) -> int:
        """估算 Token 数量"""
        if not text:
            return 0
        if self.tokenizer:
            try:
                return len(self.tokenizer.encode(text))
            except:
                pass
        # 粗略估计：中文 1 字 ≈ 1.5 token，英文 1 词 ≈ 1 token
        return int(len(text) * 0.8)  # 保守估计
