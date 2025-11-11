#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SRT翻译API服务 - FastAPI实现
"""

import argparse
import json
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List, Tuple, Callable

import requests
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from zai import ZhipuAiClient

import logger
from config import config

logger = logger.get_logger(__name__)

# 语言代码映射
LANG_MAP = {
    "zh": "ZH",
    "中文": "ZH",
    "chinese": "ZH",
    "en": "EN",
    "英文": "EN",
    "english": "EN",
    "ja": "JA",
    "日文": "JA",
    "japanese": "JA",
    "ko": "KO",
    "韩文": "KO",
    "korean": "KO",
    "fr": "FR",
    "法文": "FR",
    "french": "FR",
    "de": "DE",
    "德文": "DE",
    "german": "DE",
    "es": "ES",
    "西班牙文": "ES",
    "spanish": "ES",
}


def parse_srt(content: str) -> List[Tuple[int, str, str]]:
    """
    解析SRT文件内容，保留多行文本格式

    Args:
        content: SRT文件内容

    Returns:
        List[Tuple[序号, 时间轴, 文本内容]]，文本内容保留原始换行符
    """
    if not content or not content.strip():
        logger.warning("SRT内容为空")
        return []

    # 规范化换行符：将 /n 或 \n 统一为 \n
    # 处理可能的转义问题
    original_content = content
    content = content.replace("/n", "\n").replace("\\n", "\n")
    if original_content != content:
        logger.info("检测到非标准换行符，已自动转换")

    # 使用非贪婪匹配，直到遇到下一个序号或文件结尾
    pattern = r"(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?=\n\d+\s*\n|\Z)"

    matches = re.findall(pattern, content, re.DOTALL)
    logger.debug(f"正则匹配结果: {len(matches)} 条")
    subtitles = []

    for match in matches:
        index = int(match[0])
        timestamp = match[1]
        text = match[2].strip()

        # 将多个连续换行符替换为单个换行符，但保留文本内部的换行
        text = re.sub(r'\n{3,}', '\n\n', text)  # 最多保留两个连续换行
        text = text.strip()  # 清理首尾空白

        subtitles.append((index, timestamp, text))
        # 记录文本行数用于调试
        line_count = text.count('\n') + 1
        logger.debug(f"解析字幕 {index}: {timestamp} - {line_count}行 - {text[:50].replace(chr(10), ' ')}...")

    return subtitles


def format_srt(subtitles: List[Tuple[int, str, str]]) -> str:
    """
    将字幕数据格式化为SRT格式，保留多行文本

    Args:
        subtitles: 字幕列表 [(序号, 时间轴, 文本), ...]，文本可能包含换行符

    Returns:
        SRT格式的字符串
    """
    srt_lines = []
    for index, timestamp, text in subtitles:
        srt_lines.append(str(index))
        srt_lines.append(timestamp)
        # 否则添加单行文本
        srt_lines.append(text)
        srt_lines.append("")  # 空行分隔

    return "\n".join(srt_lines)


def normalize_lang_code(lang_input: str) -> str:
    """
    标准化语言代码

    Args:
        lang_input: 用户输入的语言

    Returns:
        标准化的语言代码
    """
    lang_lower = lang_input.lower().strip()
    return LANG_MAP.get(lang_lower, lang_input.upper())


def create_session() -> requests.Session:
    """
    创建带重试机制的HTTP会话

    Args:
        use_proxy: 是否使用代理，默认 True

    Returns:
        配置好的requests.Session对象
    """
    session = requests.Session()

    # 配置重试策略
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy, pool_connections=10, pool_maxsize=20
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


# 全局HTTP会话（连接复用）
_translation_session: Optional[requests.Session] = None

# 全局ZhipuAi客户端（连接复用）
_zhipuai_client: Optional[ZhipuAiClient] = None


def get_translation_session() -> requests.Session:
    """
    依赖注入：获取翻译会话
    
    Returns:
        HTTP会话对象
    """
    if _translation_session is None:
        raise RuntimeError("翻译会话未初始化，请确保服务已正常启动")
    return _translation_session


def get_zhipuai_client() -> ZhipuAiClient:
    """
    依赖注入：获取ZhipuAi客户端
    
    Returns:
        ZhipuAi客户端对象
    """
    if _zhipuai_client is None:
        raise RuntimeError("ZhipuAi客户端未初始化，请确保服务已正常启动")
    return _zhipuai_client


def normalize_model(model_input: Optional[str]) -> str:
    """
    标准化模型名称
    
    Args:
        model_input: 用户输入的模型名称
        
    Returns:
        标准化的模型名称
    """
    model = model_input.lower().strip() if model_input else "zhipuai"
    if model not in ["deeplx", "zhipuai"]:
        logger.warning(f"不支持的模型: {model}，使用默认模型 zhipuai")
        model = "zhipuai"
    return model


def translate_with_zhipuai(
        srt_content: str,
        source_lang: str,
        target_lang: str,
        client: ZhipuAiClient
) -> str:
    """
    使用 ZhipuAi 模型翻译SRT
    
    Args:
        srt_content: SRT字幕内容
        source_lang: 源语言
        target_lang: 目标语言
        client: ZhipuAi客户端
        
    Returns:
        翻译后的SRT内容
    """
    logger.info("使用 ZhipuAi 模型进行翻译")

    # 构建翻译提示词
    prompt = f"""{source_lang} Translate to {target_lang} (output translation only):

    {srt_content}"""

    response = client.chat.completions.create(
        model="glm-4-plus",
        messages=[
            {"role": "user", "content": prompt}
        ],
        max_tokens=4096,
        temperature=0.7
    )
    translated_srt = response.choices[0].message.content.strip()
    logger.info("ZhipuAi 翻译完成")
    return translated_srt


def translate_with_deeplx(
        srt_content: str,
        source_lang: str,
        target_lang: str,
        session: requests.Session
) -> str:
    """
    使用 DeepLX 模型翻译SRT
    
    Args:
        srt_content: SRT字幕内容
        source_lang: 源语言
        target_lang: 目标语言
        session: HTTP会话对象
        
    Returns:
        翻译后的SRT内容
    """
    logger.info("使用 DeepLX 模型进行翻译")

    # 解析SRT内容
    try:
        logger.info("开始解析SRT内容...")
        subtitles = parse_srt(srt_content)
        logger.info(f"SRT解析完成，找到 {len(subtitles)} 条字幕")
    except Exception as e:
        logger.error(f"SRT格式解析失败: {str(e)}")
        raise HTTPException(status_code=400, detail=f"SRT格式解析失败: {str(e)}")

    if not subtitles:
        logger.warning("SRT文件中未找到任何字幕内容")
        raise HTTPException(status_code=400, detail="SRT文件中未找到任何字幕内容")

    # 提取所有文本，并记录每个文本的行数（用于多行文本的处理）
    texts = []
    text_line_counts = []  # 记录每个文本的行数
    for _, _, text in subtitles:
        texts.append(text)
        # 计算文本行数（换行符数量 + 1）
        line_count = text.count('\n') + 1
        text_line_counts.append(line_count)
        if line_count > 1:
            logger.debug(f"检测到多行文本，行数: {line_count}")

    logger.info(f"提取到 {len(texts)} 条文本，准备翻译")
    total_lines = sum(text_line_counts)
    logger.info(f"总行数: {total_lines}（包含多行文本）")

    # 标准化语言代码（deeplx需要标准格式）
    source_lang_normalized = normalize_lang_code(source_lang)
    target_lang_normalized = normalize_lang_code(target_lang)
    logger.info(f"DeepLX标准化后 - 源语言: {source_lang_normalized}, 目标语言: {target_lang_normalized}")

    # 调用翻译API
    try:
        logger.info(f"调用DeepLX翻译API: {config.models['deeplx_api_url']}")
        translated_texts = translate_texts(
            texts, source_lang_normalized, target_lang_normalized, config.models['deeplx_api_url'], session
        )
        logger.info(f"翻译完成，收到 {len(translated_texts)} 条翻译结果")
    except Exception as e:
        logger.error(f"DeepLX翻译API调用失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"DeepLX翻译API调用失败: {str(e)}")

    # 如果翻译结果被分割成多行，需要根据原始文本的行数重新组合
    translated_subtitles = []
    result_index = 0

    for i, (index, timestamp, original_text) in enumerate(subtitles):
        original_line_count = text_line_counts[i]

        if result_index < len(translated_texts):
            # 如果原文是多行的，需要组合多行翻译结果
            if original_line_count > 1:
                # 组合对应行数的翻译结果
                translated_lines = []
                for _ in range(original_line_count):
                    if result_index < len(translated_texts):
                        translated_lines.append(translated_texts[result_index])
                        result_index += 1
                    else:
                        translated_lines.append("")
                translated_text = "\n".join(translated_lines)
            else:
                # 单行文本，直接使用
                translated_text = translated_texts[result_index] if result_index < len(translated_texts) else ""
                result_index += 1
        else:
            translated_text = ""

        translated_subtitles.append((index, timestamp, translated_text))
        if original_line_count > 1:
            logger.debug(f"字幕 {index}: 原文{original_line_count}行，翻译后{translated_text.count(chr(10)) + 1}行")

    # 格式化为SRT格式
    translated_srt = format_srt(translated_subtitles)
    return translated_srt


def translate_texts(
        texts: List[str],
        source_lang: str,
        target_lang: str,
        api_url: str,
        session: requests.Session,
) -> List[str]:
    """
    调用翻译API翻译文本列表（一次性发送所有文本）

    Args:
        texts: 要翻译的文本列表
        source_lang: 源语言代码
        target_lang: 目标语言代码
        api_url: API地址
        session: HTTP会话对象

    Returns:
        翻译后的文本列表
    """
    if not texts:
        logger.warning("文本列表为空，跳过翻译")
        return []

    # 组装请求数据
    payload = {"text": texts, "source_lang": source_lang, "target_lang": target_lang}
    logger.info(
        f"准备发送翻译请求: {len(texts)} 条文本, {source_lang} -> {target_lang}"
    )

    try:
        # 发送POST请求
        logger.debug(f"请求URL: {api_url}")
        logger.debug(f"请求payload: {json.dumps(payload, ensure_ascii=False)[:200]}...")
        response = session.post(api_url, json=payload, timeout=60)
        logger.info(f"翻译API响应状态码: {response.status_code}")
        response.raise_for_status()

        # 解析响应
        result = response.json()
        logger.debug(f"翻译API响应: {json.dumps(result, ensure_ascii=False)[:200]}...")
        translations = result.get("translations", [])

        if len(translations) == 0:
            # 如果没有translations字段，尝试直接获取text字段
            translated_text = result.get("text", "")
            if not translated_text:
                logger.warning("翻译API返回空结果")
                return [""] * len(texts)
        else:
            translated_text = translations[0].get("text", "")

        if not translated_text:
            logger.warning("翻译结果为空")
            return [""] * len(texts)

        # 按\n分割翻译结果
        translated_texts = translated_text.split("\n")
        logger.info(f"翻译结果分割后: {len(translated_texts)} 条")

        # 确保返回的列表长度与输入一致
        if len(translated_texts) != len(texts):
            logger.warning(
                f"翻译结果数量({len(translated_texts)})与输入数量({len(texts)})不一致，进行调整"
            )
            # 如果数量不一致，尝试补齐或截断
            if len(translated_texts) < len(texts):
                translated_texts.extend([""] * (len(texts) - len(translated_texts)))
            else:
                translated_texts = translated_texts[: len(texts)]

        return [text.strip() for text in translated_texts]

    except requests.exceptions.RequestException as e:
        logger.error(f"API请求错误: {str(e)}")
        raise RuntimeError(f"API请求错误: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"响应解析错误: {str(e)}")
        raise RuntimeError(f"响应解析错误: {e}")
    except Exception as e:
        logger.error(f"翻译过程出错: {str(e)}", exc_info=True)
        raise RuntimeError(f"翻译过程出错: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global _translation_session, _zhipuai_client

    # 启动时初始化
    logger.info("=" * 60)
    logger.info("SRT翻译API服务启动")
    logger.info("=" * 60)

    # 初始化翻译会话
    logger.info("正在初始化翻译会话...")
    _translation_session = create_session()
    logger.info("翻译会话初始化完成")

    # 初始化ZhipuAi客户端
    logger.info("正在初始化ZhipuAi客户端...")
    _zhipuai_client = ZhipuAiClient(api_key=config.models['zhipuai_api_key'])
    logger.info("ZhipuAi客户端初始化完成")

    yield

    # 关闭时清理资源
    logger.info("SRT翻译API服务关闭，清理资源...")
    if _translation_session is not None:
        _translation_session.close()
        _translation_session = None
        logger.info("翻译会话已关闭")
    if _zhipuai_client is not None:
        _zhipuai_client = None
        logger.info("ZhipuAi客户端已清理")


app = FastAPI(
    title="SRT翻译API服务",
    description="提供SRT字幕文件翻译功能的Web API",
    version="1.0.0",
    lifespan=lifespan,
)


# 请求和响应日志记录中间件
@app.middleware("http")
async def log_requests_responses(request: Request, call_next: Callable) -> Response:
    """
    记录所有API请求和响应的中间件
    """
    start_time = time.time()
    
    # 获取客户端IP
    client_ip = request.client.host if request.client else "unknown"
    
    # 读取请求体（需要保存以便后续使用）
    request_body = None
    body_bytes = None
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            body_bytes = await request.body()
            if body_bytes:
                # 尝试解析JSON
                try:
                    request_body = json.loads(body_bytes.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # 如果不是JSON，记录为文本（截断长内容）
                    body_text = body_bytes.decode('utf-8', errors='replace')
                    max_body_length = 1000  # 最大记录长度
                    if len(body_text) > max_body_length:
                        request_body = f"{body_text[:max_body_length]}... (已截断，总长度: {len(body_text)} 字符)"
                    else:
                        request_body = body_text
        except Exception as e:
            request_body = f"<读取请求体失败: {str(e)}>"
    
    # 重新设置请求体，以便后续路由处理函数可以使用
    async def receive():
        return {"type": "http.request", "body": body_bytes} if body_bytes else {"type": "http.request"}
    
    if body_bytes:
        request._receive = receive
    
    # 记录请求信息
    logger.info("=" * 80)
    logger.info(f"[请求] {request.method} {request.url.path}")
    logger.info(f"客户端IP: {client_ip}")
    logger.info(f"查询参数: {dict(request.query_params)}")
    
    # 记录请求头（排除敏感信息）
    headers_to_log = {}
    sensitive_headers = ['authorization', 'cookie', 'x-api-key']
    for key, value in request.headers.items():
        if key.lower() not in sensitive_headers:
            headers_to_log[key] = value
        else:
            headers_to_log[key] = "***已隐藏***"
    logger.debug(f"请求头: {json.dumps(headers_to_log, ensure_ascii=False, indent=2)}")
    
    # 记录请求体（对于大内容进行截断）
    if request_body is not None:
        if isinstance(request_body, dict):
            # JSON请求体，完整记录
            request_body_str = json.dumps(request_body, ensure_ascii=False, indent=2)
            max_length = 2000  # JSON最大记录长度
            if len(request_body_str) > max_length:
                logger.info(f"请求体: {request_body_str[:max_length]}... (已截断，总长度: {len(request_body_str)} 字符)")
            else:
                logger.info(f"请求体: {request_body_str}")
        else:
            # 文本请求体
            logger.info(f"请求体: {request_body}")
    
    # 处理请求
    try:
        response = await call_next(request)
        
        # 计算处理时间
        process_time = time.time() - start_time
        
        # 记录响应信息
        status_code = response.status_code
        
        # 记录响应基本信息
        logger.info(f"[响应] 状态码: {status_code}, 处理时间: {process_time:.3f}秒")
        
        # 尝试读取响应体（对于大响应进行截断）
        # 注意：某些响应类型（如 PlainTextResponse）可能无法在中间件中读取响应体
        # 详细的响应内容会在路由函数中记录
        try:
            # 检查响应类型
            response_type = type(response).__name__
            logger.debug(f"响应类型: {response_type}")
            
            # 对于 JSON 响应，尝试读取响应体
            if hasattr(response, 'body') and response.body:
                try:
                    body_bytes = response.body
                    if isinstance(body_bytes, bytes):
                        try:
                            # 尝试解析JSON
                            response_body = json.loads(body_bytes.decode('utf-8'))
                            response_body_str = json.dumps(response_body, ensure_ascii=False, indent=2)
                            max_length = 2000
                            if len(response_body_str) > max_length:
                                logger.info(f"响应体: {response_body_str[:max_length]}... (已截断，总长度: {len(response_body_str)} 字符)")
                            else:
                                logger.info(f"响应体: {response_body_str}")
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            # 文本响应
                            body_text = body_bytes.decode('utf-8', errors='replace')
                            max_length = 2000
                            if len(body_text) > max_length:
                                logger.info(f"响应体: {body_text[:max_length]}... (已截断，总长度: {len(body_text)} 字符)")
                            else:
                                logger.info(f"响应体: {body_text}")
                except Exception as e:
                    logger.debug(f"无法读取响应体: {str(e)}")
            else:
                # 对于 PlainTextResponse 等，响应体可能已经在路由函数中记录
                logger.debug("响应体: <无法在中间件中读取，详情请查看路由函数日志>")
        except Exception as e:
            logger.debug(f"读取响应体时出错: {str(e)}")
        
        # 对于错误响应，记录为ERROR级别
        if status_code >= 400:
            logger.error(f"[错误响应] {request.method} {request.url.path} - 状态码: {status_code}, 处理时间: {process_time:.3f}秒")
        
        logger.info("=" * 80)
        
        return response
        
    except Exception as e:
        # 处理异常
        process_time = time.time() - start_time
        logger.error(f"[异常] {request.method} {request.url.path} - 异常: {str(e)}, 处理时间: {process_time:.3f}秒", exc_info=True)
        logger.info("=" * 80)
        raise


class TranslateRequest(BaseModel):
    """翻译请求模型"""

    srt: str = Field(..., description="SRT字幕文本内容")
    lang: str = Field(
        ..., description="目标翻译语言，例如: EN, 英文, english, ZH, 中文等"
    )
    source_lang: Optional[str] = Field(default="ZH", description="源语言代码，默认: ZH")
    model: Optional[str] = Field(
        default="zhipuai", description="翻译模型，可选值: deeplx, zhipuai (默认: zhipuai)"
    )


@app.get("/")
async def root():
    """根路径，返回API信息"""
    logger.info("收到根路径请求")
    return {
        "service": "SRT翻译API服务",
        "version": "1.0.0",
        "endpoints": {
            "POST /translate": "翻译SRT字幕文件",
            "GET /languages": "获取支持的语言列表",
        },
        "supported_models": {
            "deeplx": "DeepLX翻译模型",
            "zhipuai": "智谱AI翻译模型（默认）",
        },
    }


@app.get("/languages")
async def get_languages():
    """获取支持的语言列表"""
    logger.info("收到获取语言列表请求")
    # 按标准语言代码分组
    languages = {}
    for key, value in LANG_MAP.items():
        if value not in languages:
            languages[value] = []
        languages[value].append(key)

    # 格式化输出
    result = {}
    for lang_code, aliases in sorted(languages.items()):
        result[lang_code] = aliases

    logger.info(f"返回支持的语言列表，共 {len(result)} 种语言")
    return {
        "supported_languages": result,
        "usage": "可以使用语言代码或别名作为lang参数",
    }


@app.post("/translate", response_class=PlainTextResponse)
def translate_srt(
        request: TranslateRequest,
        session: requests.Session = Depends(get_translation_session),
        zhipuai_client: ZhipuAiClient = Depends(get_zhipuai_client)
):
    """
    翻译SRT字幕文件

    Args:
        request: 翻译请求，包含SRT文本和目标语言
        session: HTTP会话对象（DeepLX使用）
        zhipuai_client: ZhipuAi客户端（ZhipuAi使用）

    Returns:
        翻译后的SRT文本
    """
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info(f"收到翻译请求 - 时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"目标语言: {request.lang}, 源语言: {request.source_lang}")
    logger.info(f"SRT内容长度: {len(request.srt)} 字符")

    try:
        # 标准化模型和语言代码
        model = normalize_model(request.model)
        logger.info(f"使用翻译模型: {model}")

        target_lang = request.lang.lower().strip()
        source_lang = request.source_lang.lower().strip()
        logger.info(f"标准化后 - 源语言: {source_lang}, 目标语言: {target_lang}")

        # 根据模型选择不同的翻译方式
        # FastAPI 会自动将同步函数放到线程池执行，支持并发
        if model == "zhipuai":
            try:
                translated_srt = translate_with_zhipuai(
                    request.srt, source_lang, target_lang, zhipuai_client
                )
            except Exception as e:
                logger.error(f"ZhipuAi API调用失败: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"ZhipuAi翻译API调用失败: {str(e)}")
        else:
            translated_srt = translate_with_deeplx(
                request.srt, source_lang, target_lang, session
            )

        # 记录处理完成日志
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.info(f"翻译处理完成，耗时: {duration:.2f} 秒")
        logger.info("=" * 60)

        return translated_srt

    except HTTPException:
        logger.error("HTTP异常，已返回错误响应")
        raise
    except Exception as e:
        logger.error(f"处理过程中发生未预期的错误: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理过程中发生错误: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    # 解析命令行参数
    parser = argparse.ArgumentParser(description="SRT翻译API服务")
    parser.add_argument(
        "--port", type=int, default=8000, help="服务端口号 (默认: 8000)"
    )
    parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="服务主机地址 (默认: 0.0.0.0)"
    )
    parser.add_argument(
        "--reload", action="store_true", help="启用自动重载（开发模式）"
    )

    args = parser.parse_args()

    logger.info("启动SRT翻译API服务")
    logger.info(f"主机: {args.host}, 端口: {args.port}")
    if args.reload:
        logger.info("自动重载模式已启用")

    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
