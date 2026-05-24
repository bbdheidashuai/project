#!/usr/bin/python
# coding=utf-8
"""
板块/行业方向建议、大模型 JSON 选股：支持多种后端。
环境变量（在系统环境或 stock-analysis/.env 中设置，见 env.example）：

  LLM_PROVIDER  可选：
    openai_compat（默认）— OpenAI 兼容 POST .../chat/completions
    gemini        — Google 官方 Gemini generateContent（密钥多为 AIza...）
    gemini_openai — Google 提供的 OpenAI 兼容路径（Bearer + 官方密钥）

  LLM_API_KEY   通用密钥（openai_compat / gemini_openai 常用）
  GEMINI_API_KEY  若设置且 LLM_PROVIDER=gemini 时优先于 LLM_API_KEY

  LLM_API_BASE  openai_compat 或 gemini_openai 时的接口根路径
  LLM_MODEL     模型名（如 gpt-4o-mini、deepseek-chat）
  LLM_VENDOR    可选 deepseek：未写 LLM_API_BASE 时用官方 https://api.deepseek.com/v1；
                 未写 LLM_MODEL 时默认 deepseek-chat（若 BASE 含 deepseek.com 也会默认该模型）
  GEMINI_MODEL  LLM_PROVIDER=gemini 时可替代 LLM_MODEL
"""
import json
import os
import re

import requests

_ENV_PARSED = False


def _parse_env_line(line):
    line = line.strip()
    if not line or line.startswith("#"):
        return None, None
    if line.startswith("export "):
        line = line[7:].strip()
    if "=" not in line:
        return None, None
    key, _, val = line.partition("=")
    key = key.strip()
    if not key:
        return None, None
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        val = val[1:-1]
    return key, val


def _load_env_files_once():
    """从项目目录或当前工作目录的 .env 注入变量（不覆盖已在 OS 中设置的同名变量）。"""
    global _ENV_PARSED
    if _ENV_PARSED:
        return
    _ENV_PARSED = True
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = []
    custom = (os.environ.get("LLM_ENV_FILE") or "").strip()
    if custom:
        paths.append(custom)
    paths.append(os.path.join(base_dir, ".env"))
    paths.append(os.path.join(os.getcwd(), ".env"))
    seen = set()
    for path in paths:
        ap = os.path.normpath(os.path.abspath(path))
        if ap in seen:
            continue
        seen.add(ap)
        if not os.path.isfile(ap):
            continue
        try:
            with open(ap, encoding="utf-8") as fp:
                for raw in fp:
                    k, v = _parse_env_line(raw)
                    if k and v is not None:
                        os.environ.setdefault(k, v)
        except OSError:
            continue


_SYSTEM_PROMPT = """你是证券与行业研究的辅助工具，只做知识整理与思路启发，不得给出具体买卖时点、不得推荐个股代码。
用户仅提供一段自行撰写的文字说明。你的回复与任何程序化选股、排序或打分结果无关，仅为独立的一般性参考建议。
请结合 A 股市场常见的板块/行业划分习惯，输出结构化中文内容，严格使用以下 Markdown 小节标题（勿删改标题文字）：

## 可关注方向
用有序列表列出 4～8 个「板块或细分行业方向」，每项一行，格式为：序号. **方向名称** — 一句话逻辑（不超过 60 字）。

## 风险与约束
用无序列表写 3～5 条：宏观/政策/估值/流动性/行业周期等可能风险；并强调历史与公开信息不预示未来。

## 使用说明
用 2～3 句话说明：本输出仅为方向性参考建议，不构成投资建议，须自行核实信息并独立决策；若用户未提供足够信息，可基于常识做温和假设并在「可关注方向」首条用括号注明假设。

全文客观、克制，避免夸张收益承诺。"""


_STOCK_JSON_SYSTEM = """你是A股研究辅助助手。用户用自然语言描述投资偏好、行业或风格关注点。
你必须**只输出一个合法 JSON 对象**（不要用 Markdown 代码围栏、不要任何前缀或后缀说明文字），结构严格为：
{"stocks":[{"code":"6位数字证券代码","name":"股票简称","board":"行业或板块（简短）","reason":"一句话说明为何符合用户描述，不超过80字"}, ...]}
硬性要求：
- stocks 数组**恰好 10 个**元素；code 为沪深北 A 股常见 **6 位数字**（不要带 sh./sz. 前缀）；
- name、board、reason 用中文；信息不确定时如实写在 reason 中，勿编造明显虚假代码；
- 不得包含买卖价位、不得承诺收益。"""


def _missing_key_message():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_dir, ".env")
    return (
        "未配置大模型：请设置 LLM_API_KEY（或 Gemini 官方用 GEMINI_API_KEY）。"
        "方式一：系统/终端环境变量。"
        "方式二：在 stock-analysis 目录新建 .env（可参考 env.example）。"
        f"将读取：{env_path}"
    )


def _call_openai_chat_completions(
    url, api_key, model, messages, timeout, max_tokens=2200, temperature=0.55
):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    except requests.RequestException as exc:
        return None, f"调用大模型网络异常：{exc}"
    if resp.status_code != 200:
        try:
            err_obj = resp.json()
            detail = err_obj.get("error", {})
            if isinstance(detail, dict):
                detail = detail.get("message", resp.text[:800])
            else:
                detail = str(detail)[:800]
        except Exception:
            detail = resp.text[:800]
        return None, f"大模型接口错误（HTTP {resp.status_code}）：{detail}"
    try:
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        return None, f"解析大模型返回失败：{exc}"
    return (text or "").strip(), None


def _call_gemini_native(api_key, model, system_prompt, user_text, timeout):
    """Google AI Studio / Gemini REST：generateContent，密钥为 URL 参数 key。"""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    params = {"key": api_key}
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_text}],
            }
        ],
        "generationConfig": {
            "temperature": 0.55,
            "maxOutputTokens": 4096,
        },
    }
    try:
        resp = requests.post(url, params=params, json=body, timeout=timeout)
    except requests.RequestException as exc:
        return None, f"调用 Gemini 网络异常：{exc}"

    try:
        data = resp.json()
    except Exception:
        return None, f"Gemini 返回非 JSON：{resp.text[:500]}"

    if resp.status_code != 200:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        msg = err.get("message", resp.text[:800]) if isinstance(err, dict) else str(err)
        hint = ""
        if str(api_key).startswith("sk-"):
            hint = (
                " 提示：sk- 类密钥无法用于 Google 官方 Gemini URL；"
                "请使用 LLM_PROVIDER=openai_compat，并设置服务商提供的 LLM_API_BASE。"
            )
        return None, f"Gemini 接口错误（HTTP {resp.status_code}）：{msg}{hint}"

    cands = data.get("candidates") or []
    if not cands:
        fb = data.get("promptFeedback") or {}
        return None, f"Gemini 未返回候选内容（可能被安全策略拦截）：{fb}"

    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join((p.get("text") or "") for p in parts if isinstance(p, dict))
    if not text.strip():
        return None, "Gemini 返回内容为空。"
    return text.strip(), None


def _run_chat(messages, timeout=90, max_tokens=2200, temperature=0.55):
    """统一路由：OpenAI 兼容 / DeepSeek / Gemini。"""
    _load_env_files_once()
    provider = (os.environ.get("LLM_PROVIDER") or "openai_compat").lower().strip()

    if provider in ("gemini", "google", "google_gemini"):
        api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY") or "").strip()
        model = (os.environ.get("GEMINI_MODEL") or os.environ.get("LLM_MODEL") or "gemini-2.0-flash").strip()
        if not api_key:
            return None, _missing_key_message() + "（Gemini 官方请使用 AI Studio 的 API 密钥，并建议设置 LLM_PROVIDER=gemini）"
        system_c = ""
        user_parts = []
        for m in messages:
            if m.get("role") == "system":
                system_c = m.get("content") or ""
            elif m.get("role") == "user":
                user_parts.append(m.get("content") or "")
        user_c = "\n\n".join(user_parts) if user_parts else ""
        return _call_gemini_native(
            api_key, model, system_c or "You are a helpful assistant.", user_c, timeout
        )

    if provider in ("gemini_openai", "gemini-openai"):
        api_key = (os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
        base = (
            os.environ.get("LLM_API_BASE")
            or "https://generativelanguage.googleapis.com/v1beta/openai"
        ).strip().rstrip("/")
        model = (os.environ.get("LLM_MODEL") or "gemini-2.0-flash").strip()
        if not api_key:
            return None, _missing_key_message()
        url = f"{base}/chat/completions"
        return _call_openai_chat_completions(
            url, api_key, model, messages, timeout, max_tokens, temperature
        )

    api_key = (os.environ.get("LLM_API_KEY") or "").strip()
    base_raw = (os.environ.get("LLM_API_BASE") or "").strip().rstrip("/")
    model_raw = (os.environ.get("LLM_MODEL") or "").strip()
    vendor = (os.environ.get("LLM_VENDOR") or "").lower().strip()
    use_deepseek = vendor == "deepseek" or (
        base_raw and "deepseek.com" in base_raw.lower()
    )
    if use_deepseek:
        base = base_raw or "https://api.deepseek.com/v1"
        model = model_raw or "deepseek-chat"
    else:
        base = base_raw or "https://api.openai.com/v1"
        model = model_raw or "gpt-4o-mini"
    if not api_key:
        return None, _missing_key_message()
    url = f"{base}/chat/completions"
    return _call_openai_chat_completions(
        url, api_key, model, messages, timeout, max_tokens, temperature
    )


def get_sector_direction_advice(extra_note, timeout=90):
    text_in = (extra_note or "").strip()
    if len(text_in) < 4:
        return None, "请在本模块「补充说明」文本框中至少输入几个字的描述后再试（与下方量化选股无关）。"

    user_content = "【用户在本模块提供的说明】\n" + text_in
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    return _run_chat(messages, timeout=timeout, max_tokens=2200, temperature=0.55)


def _norm_a_code(code):
    s = str(code).strip()
    if "." in s:
        s = s.split(".")[-1]
    s = re.sub(r"\D", "", s)
    if len(s) == 6 and s.isdigit():
        return s
    return ""


def _parse_ten_stocks_from_llm_text(raw):
    text = (raw or "").strip()
    if not text:
        return None, "大模型返回为空"
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I).strip()
        text = re.sub(r"\s*```\s*$", "", text).strip()
    brace_a = text.find("{")
    brace_b = text.rfind("}")
    if brace_a != -1 and brace_b != -1 and brace_b > brace_a:
        text = text[brace_a : brace_b + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"无法解析大模型返回的 JSON：{exc}"
    stocks = data.get("stocks")
    if not isinstance(stocks, list):
        return None, "JSON 中缺少 stocks 数组或类型不正确"
    out = []
    seen = set()
    for item in stocks:
        if not isinstance(item, dict):
            continue
        c = _norm_a_code(item.get("code", ""))
        if not c or c in seen:
            continue
        seen.add(c)
        name = str(item.get("name") or "").strip() or c
        board = str(item.get("board") or "").strip() or "—"
        reason = str(item.get("reason") or "").strip() or "—"
        out.append({"code": c, "name": name, "board": board, "reason": reason})
        if len(out) >= 10:
            break
    if len(out) < 10:
        return None, (
            f"解析后有效标的仅 {len(out)} 只（需 10 只六位 A 股代码）。"
            "请重试，或在输入中写清行业、风格、市值偏好等。"
        )
    return out, None


def get_ten_stocks_recommendation(extra_note, timeout=120):
    """
    根据用户自然语言，让大模型输出 JSON，解析为 10 条 {code,name,board,reason}，
    再转为与前端表格兼容的字典列表（无实时行情字段）。
    """
    text_in = (extra_note or "").strip()
    if len(text_in) < 6:
        return None, "请至少输入一小段具体说明（如行业、风格、持仓周期等），便于大模型选出 10 只标的。"

    user_content = "【用户输入】\n" + text_in + "\n\n请严格按系统要求的 JSON 输出，stocks 必须恰好 10 条。"
    messages = [
        {"role": "system", "content": _STOCK_JSON_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    raw, err = _run_chat(messages, timeout=timeout, max_tokens=4500, temperature=0.35)
    if err:
        return None, err
    parsed, perr = _parse_ten_stocks_from_llm_text(raw)
    if perr:
        return None, perr

    rows = []
    for i, s in enumerate(parsed, 1):
        raw_score = 1.0 - (i - 1) / 9.0
        stars = max(1, min(5, int(round(1 + raw_score * 4))))
        stars_display = "★" * stars + "☆" * (5 - stars)
        rows.append(
            {
                "rank": i,
                "code": s["code"],
                "name": s["name"],
                "board": s["board"],
                "stars": stars,
                "stars_display": stars_display,
                "today_chg": None,
                "d5_chg": None,
                "d10_chg": None,
                "main_today": None,
                "main_d5": None,
                "sector_matched": False,
                "reason": "【大模型】" + s["reason"],
            }
        )
    return rows, None
