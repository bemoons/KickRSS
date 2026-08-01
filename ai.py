import logging
import json
import httpx
import re
from typing import List, Dict, Any, Optional, Union
from config import settings

logger = logging.getLogger(__name__)

def estimate_clean_text_length(text: str) -> int:
    """
    Estimate the real text length by stripping Markdown images, links, and HTML tags.
    """
    if not text:
        return 0
    # 1. Strip markdown images: ![alt](url)
    t = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    # 2. Strip ordinary markdown links: [text](url) -> keep text
    t = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', t)
    # 3. Strip HTML tags
    t = re.sub(r'<[^>]*>', '', t)
    # 4. Strip extra spaces and return length
    return len(t.strip())

def call_chat_completion(
    config: Dict[str, Any], 
    messages: List[Dict[str, str]], 
    response_format_json: bool = True,
    disable_reasoning: bool = True
) -> str:
    """
    Perform a POST request to the OpenAI-compatible endpoint.
    Handles fallbacks for JSON mode if the endpoint fails.
    """
    base_url = config["base_url"].rstrip("/")
    url = f"{base_url}/chat/completions"
    
    headers = {"Content-Type": "application/json"}
    if config["api_key"]:
        headers["Authorization"] = f"Bearer {config['api_key']}"
        
    payload = {
        "model": config["model"],
        "messages": messages,
    }
    
    if is_reasoning_model(config["model"]):
        payload["max_tokens"] = 8192
    elif config.get("max_tokens"):
        payload["max_tokens"] = config["max_tokens"]
        
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}
        
    disabler_added = False
    if disable_reasoning:
        append_reasoning_disabler(payload, config["model"], config["base_url"], config.get("reasoning_disabler", "auto"))
        disabler_added = True
        
    try:
        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(url, headers=headers, json=payload)
            
            # If 400 Bad Request and we added disablers, retry without them
            if response.status_code == 400 and disabler_added:
                logger.warning("Endpoint returned 400; retrying without reasoning disablers")
                for field in ["chat_template_kwargs", "thinking", "thinking_config", "think", "enable_thinking"]:
                    payload.pop(field, None)
                disabler_added = False
                with httpx.Client(timeout=120.0) as client:
                    response = client.post(url, headers=headers, json=payload)
                    
            # Fallback if JSON mode is not supported by the endpoint (e.g. returns 400 Bad Request)
            if response.status_code == 400 and response_format_json:
                logger.warning("Endpoint returned 400; retrying without response_format='json_object'")
                payload.pop("response_format", None)
                with httpx.Client(timeout=120.0) as client:
                    response = client.post(url, headers=headers, json=payload)
            
            response.raise_for_status()
        except Exception as initial_err:
            if response_format_json or disabler_added:
                logger.warning(f"Initial request failed with {initial_err}; retrying with absolute fallback")
                payload.pop("response_format", None)
                for field in ["chat_template_kwargs", "thinking", "thinking_config", "think", "enable_thinking"]:
                    payload.pop(field, None)
                with httpx.Client(timeout=120.0) as client:
                    response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
            else:
                raise
                
        result_json = response.json()
        logger.info(f"AI response: {result_json}")
        usage = result_json.get("usage")
        if usage:
            try:
                from db import get_db
                import crud
                with get_db() as conn:
                    crud.record_token_usage(
                        conn,
                        usage.get("prompt_tokens", 0),
                        usage.get("completion_tokens", 0),
                        usage.get("total_tokens", 0)
                    )
            except Exception as usage_err:
                logger.error(f"Failed to record token usage: {usage_err}")
        message = result_json["choices"][0]["message"]
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        
        # If content is empty, check if reasoning contains SUMMARY:
        if not content.strip() and reasoning.strip():
            if "SUMMARY:" in reasoning:
                # Extract SUMMARY: from reasoning
                _, summary = parse_ai_summary_response(reasoning)
                if summary:
                    content = summary
            else:
                # Fallback: use reasoning as-is
                content = reasoning
        
        content = clean_think_block(content)
        return content
    except Exception as e:
        logger.error(f"Error calling AI completions API at {url}: {e}", exc_info=True)
        raise

def generate_seed_categories(titles: List[str]) -> List[str]:
    """
    Generate initial feed categories based on 100 historical titles.
    """
    if not titles:
        return []
        
    config = settings.get_ai_config("seed")
    
    # Format the titles for the AI
    titles_text = "\n".join(f"- {title}" for title in titles)
    
    system_prompt = (
        "You are an expert RSS assistant. You are given a list of article titles from a single RSS feed.\n"
        "Your task is to analyze these titles and generate a list of 3 to 10 distinct, cohesive categories (drawers) to organize this feed.\n"
        "Follow these rules:\n"
        "1. The categories must be in the same language as the titles (e.g. if titles are in Chinese, categories must be in Chinese).\n"
        "2. The categories should have a reasonable granularity (not too broad, not too narrow).\n"
        "3. Do not include a '未归类' (Uncategorized) category; it will be added automatically.\n"
        "4. Output must be a valid JSON object matching this schema:\n"
        "{\n"
        "  \"categories\": [\"Category 1\", \"Category 2\", ...]\n"
        "}"
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Here are the titles of the articles from the feed:\n\n{titles_text}"}
    ]
    
    try:
        content = call_chat_completion(config, messages)
        # Parse the JSON response
        data = json.loads(content)
        categories = data.get("categories", [])
        # Filter out "未归类" in case the AI generated it anyway
        clean_categories = [cat.strip() for cat in categories if cat.strip() and cat.strip() != "未归类"]
        return clean_categories
    except Exception as e:
        logger.error(f"Failed to generate seed categories: {e}", exc_info=True)
        # Return empty list on fallback so no custom categories are seeded without AI
        return []

def classify_entries_batch(
    allowed_categories: List[str], 
    entries: List[Dict[str, Any]],
    interest_profile_prompt: str = ""
) -> List[Dict[str, Any]]:
    """
    Classify a batch of entries into allowed categories and assign attention levels.
    allowed_categories: list of category names (string)
    entries: list of dict, each containing 'id', 'title', 'summary'
    Returns a list of dict: [{'id': id, 'category': category, 'attention': attention}]
    """
    if not entries:
        return []
        
    config = settings.get_ai_config("classify")
    
    # Format categories
    categories_text = ", ".join(f"'{cat}'" for cat in allowed_categories)
    
    # Format entries batch
    entries_list = []
    for entry in entries:
        entries_list.append({
            "id": entry["id"],
            "title": entry["title"],
            "summary": entry["summary"][:200] if entry.get("summary") else ""
        })
    entries_text = json.dumps(entries_list, ensure_ascii=False)
    
    system_prompt = (
        "You are an expert RSS assistant. You are given:\n"
        f"1. A list of allowed categories for a specific feed: {categories_text}\n"
        "2. A batch of articles, each with an ID, title, and optional summary.\n\n"
        "Your task is to classify each article into one of the allowed categories and assign an attention level.\n"
        "Allowed attention levels:\n"
        "- 'read': High value, worth reading carefully.\n"
        "- 'skim': Medium value, scan quickly.\n"
        "- 'glance': Low value, just a quick look.\n\n"
        "Rules:\n"
        "1. You MUST select the category from the allowed categories list exactly. If none of the allowed categories fit, you MUST select '未归类'. Do not invent new categories.\n"
        "2. Output must be a valid JSON object with the key 'results' containing a list of classification results matching this schema:\n"
        "{\n"
        "  \"results\": [\n"
        "    {\n"
        "      \"id\": <id_as_integer>,\n"
        "      \"category\": \"<selected_category_or_未归类>\",\n"
        "      \"attention\": \"<read|skim|glance>\"\n"
        "    },\n"
        "    ...\n"
        "  ]\n"
        "}\n"
        "Ensure every input article is classified in the output results list."
    )
    
    if interest_profile_prompt:
        system_prompt += f"\n\n## User Reading Preferences (Based on past behavior):\n{interest_profile_prompt}\nAdjust the attention levels to fit the user's reading preferences."
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Classify this batch of articles:\n\n{entries_text}"}
    ]
    
    def process_response(content: str) -> List[Dict[str, Any]]:
        clean_content = content.strip()
        if clean_content.startswith("```"):
            lines = clean_content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            clean_content = "\n".join(lines).strip()
        data = json.loads(clean_content)
        results = data.get("results", [])
        return results

    # Try 1: Normal call
    try:
        content = call_chat_completion(config, messages)
        results = process_response(content)
        return results
    except Exception as e:
        logger.warning(f"Classification batch call failed: {e}. Retrying once...")
        # Try 2: Retry once
        try:
            content = call_chat_completion(config, messages)
            results = process_response(content)
            return results
        except Exception as retry_err:
            logger.error(f"Classification batch retry failed: {retry_err}. Falling back to defaults.", exc_info=True)
            # Fallback for all entries
            return [
                {"id": entry["id"], "category": "未归类", "attention": "skim"}
                for entry in entries
            ]

def get_summary_messages(
    title: str, 
    url: str, 
    content: str, 
    length: Optional[Union[str, int]] = None,
    summary_lang: Optional[str] = None
) -> List[Dict[str, str]]:
    if not length:
        length = settings.summary_length
    if not summary_lang:
        summary_lang = settings.summary_language
    if summary_lang == "auto" or not summary_lang:
        summary_lang = settings.system_language
    if summary_lang == "auto" or not summary_lang:
        summary_lang = "zh"
        
    is_numeric_length = False
    try:
        target_chars = int(length)
        is_numeric_length = True
    except (ValueError, TypeError):
        pass

    if is_numeric_length:
        length_desc = f"proportional summary targeting approximately {target_chars} Chinese characters (around 1/10 of the clean text length)"
        
        # Structure guidelines based on target length
        # Structure guidelines based on target length
        if target_chars >= 400:
            structure_advice = (
                f"- For this length ({target_chars} characters), write a structured summary containing 4-6 informative bullet points. "
                "Be concise, clear, and highlight key takeaways without fluff."
            )
            cn_structure_advice = (
                f"针对当前目标字数（大约 {target_chars} 字），请撰写 4-6 个高度凝练的核心要点。表述需客观精炼，严禁赘述或盲目扩写。"
            )
        elif target_chars >= 250:
            structure_advice = (
                f"- For this length ({target_chars} characters), write a concise summary containing 3-5 bullet points."
            )
            cn_structure_advice = (
                f"针对当前目标字数（大约 {target_chars} 字），请撰写 3-5 个精炼核心要点。"
            )
        else:
            structure_advice = (
                f"- For this length ({target_chars} characters), write a brief summary containing 2-3 bullet points."
            )
            cn_structure_advice = (
                f"针对当前简短的目标字数（大约 {target_chars} 字），请撰写 2-3 个极简核心要点。"
            )

        rule_desc = (
            f"The summary should be high-quality, cover key takeaways, and strictly target approximately {target_chars} Chinese characters.\n"
            f"- CRITICAL: The generated summary MUST target around {target_chars} Chinese characters and MUST NOT exceed {int(target_chars * 1.2)} characters.\n"
            f"- {structure_advice}"
        )
    elif length == "short":
        length_desc = "short and concise summary (typically 3 bullet points or 1 paragraph, around 150-200 characters for the summary)"
        rule_desc = "The summary should be very brief and focus only on the most important takeaway."
    elif length == "long":
        length_desc = "long, detailed and comprehensive summary (typically 6-8 bullet points or 3-4 structured paragraphs, around 600-800 characters for the summary)"
        rule_desc = "The summary should cover background context, core points/arguments, key facts/data, and final conclusions in detail."
    else: # medium
        length_desc = "comprehensive and informative summary (typically 4-6 bullet points or 2 structured paragraphs, around 300-400 characters for the summary)"
        rule_desc = "The summary should cover background context, core points/arguments, key facts/data, and final conclusions."

    lang_map = {
        "zh": ("Simplified Chinese (简体中文)", "简体中文", "简体中文"),
        "zh-hant": ("Traditional Chinese (繁体中文)", "繁體中文", "繁体中文"),
        "en": ("English", "English", "英文"),
        "ja": ("Japanese (日本語)", "日本語", "日语"),
        "ko": ("Korean (한국어)", "한국어", "韩语"),
        "fr": ("French (Français)", "Français", "法语"),
        "es": ("Spanish (Español)", "Español", "西班牙语"),
        "de": ("German (Deutsch)", "Deutsch", "德语"),
        "ru": ("Russian (Русский)", "Русский", "俄语"),
        "pt": ("Portuguese (Português)", "Português", "葡萄牙语"),
        "it": ("Italian (Italiano)", "Italiano", "意大利语")
    }
    
    is_chinese = (summary_lang in ["zh", "zh-hant"])
    if summary_lang in lang_map:
        eng_name, local_name, chn_name = lang_map[summary_lang]
        if is_chinese:
            lang_rule = (
                f"CRITICAL: The summary must be written in {eng_name} ({local_name}) ONLY, regardless of the original language of the article.\n"
                f"- 必须且只能使用 {chn_name} ({local_name}) 撰写 SUMMARY 部分，绝对不要使用原文语言来写摘要。"
            )
            if is_numeric_length:
                lang_rule += (
                    f"\n- 【字数硬性上限】：摘要总字数必须控制在大约 {target_chars} 个汉字左右（建议控制在 {int(target_chars * 0.8)} 到 {int(target_chars * 1.15)} 字以内），绝对严禁超过 {int(target_chars * 1.2)} 字！\n"
                    f"- 请做到言简意赅、高度提炼，切勿冗长赘述。\n"
                    f"- 编写要求：{cn_structure_advice}"
                )
            reminder = f"\n\nReminder: You MUST write the SUMMARY in {eng_name} ({local_name}). (提示：请务必且只能使用 {chn_name} / {local_name} 撰写摘要。)"
        else:
            lang_rule = (
                f"CRITICAL: The summary must be written in {eng_name} ({local_name}) ONLY, regardless of the original language of the article.\n"
                f"- You MUST write the SUMMARY portion in {eng_name} ({local_name}) ONLY. Do NOT write the summary in the original language if it is different. You MUST translate and write it in {eng_name}."
            )
            if is_numeric_length:
                lang_rule += (
                    f"\n- The summary MUST target approximately {target_chars} characters in {eng_name}.\n"
                    f"- Provide details and explain arguments fully to satisfy the length requirement.\n"
                    f"- Requirements: {structure_advice}"
                )
            reminder = f"\n\nReminder: You MUST write the SUMMARY in {eng_name} ({local_name}) ONLY."
    else:
        lang_rule = "The summary must be in the same language as the article content."
        if is_numeric_length:
            lang_rule += f"\n- CRITICAL: The generated summary MUST target approximately {target_chars} characters. DO NOT make it too short.\n- Requirements: {structure_advice}"
        reminder = ""

    formatting_guidelines = (
        "- Formatting Guidelines (Extremely Important):\n"
        "  - Use markdown formatting to make the summary highly readable.\n"
        "  - Structure the summary primarily as a detailed bullet list starting with '-' (e.g., `- **Point Name**: Explanation`). Each bullet point should be highly informative, specific, and detailed.\n"
        "  - You may introduce the summary with a very brief opening paragraph (1-2 sentences), but the core of the summary must be structured as detailed list items rather than plain paragraphs.\n"
        "  - Selectively use double asterisks (`**text**`) to bold key conclusions, core arguments, or sentences that need focus to make the summary scannable."
    )
    if is_chinese:
        formatting_guidelines += (
            "\n- 格式与排版规范（极重要）：\n"
            "  - 必须使用 Markdown 格式排版，确保摘要易读、易扫视。\n"
            "  - 主要排版结构：必须以条目（无序列表 `- `）为核心排版结构，避免使用大段的文字叙述。每一个条目（例如：`- **核心要点**：详细细节与事实展开`）必须内容扎实、数据细节饱满，并合理换行展开。\n"
            "  - 可以在最开头有一句非常简短的导语（1-2句），但整个摘要的主体必须是详细具体的条目列表。\n"
            "  - 突出重点：选择性地将最重要的结论、核心词句或关键数据加粗（使用 `**加粗文本**`），让读者能一眼扫视出文章的精髓，但注意不要过度加粗。"
        )

    system_prompt = (
        "You are an expert RSS assistant. You are given the title, URL, and full-text content of an article.\n"
        "Your task is to:\n"
        "1. Verify if the title is misleading or clickbait compared to the actual content.\n"
        f"2. Generate a {length_desc}.\n\n"
        "IMPORTANT: Do NOT output any thinking process or reasoning. Output ONLY the final answer.\n\n"
        "Rules:\n"
        f"- {rule_desc}\n"
        "- If the content is empty or contains no text, reply exactly with: \"NO_CONTENT\"\n"
        f"- {lang_rule}\n"
        f"{formatting_guidelines}\n"
        "- Format your response EXACTLY like this (do NOT translate the prefix keys 'CLICKBAIT_NOTE:' and 'SUMMARY:'):\n"
        "CLICKBAIT_NOTE: <If the title is misleading, state the exact reason and clear up the discrepancy in 1 sentence. If NOT misleading, write NONE>\n"
        "SUMMARY: <write the detailed summary here>"
    )
    
    user_prompt = (
        f"Title: {title}\n"
        f"URL: {url}\n"
        f"Content:\n{content}"
        f"{reminder}"
    )
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

def generate_summary_sync(
    title: str, 
    url: str, 
    content: str, 
    length: Optional[str] = None,
    summary_lang: Optional[str] = None
) -> str:
    logger.info(f"generate_summary_sync called for title: {title[:50]}")
    config = settings.get_ai_config("summary", summary_length=length)
    messages = get_summary_messages(title, url, content, length=length, summary_lang=summary_lang)
    logger.info(f"Calling chat completion with model {config['model']}")
    result = call_chat_completion(config, messages, response_format_json=False)
    # If result contains SUMMARY:, extract it
    if "SUMMARY:" in result:
        summary, clickbait = parse_ai_summary_response(result)
        result = summary
    logger.info(f"generate_summary_sync returned {len(result)} chars")
    return result

def generate_summary_stream(
    title: str, 
    url: str, 
    content: str, 
    length: Optional[str] = None,
    summary_lang: Optional[str] = None
):
    config = settings.get_ai_config("summary", summary_length=length)
    messages = get_summary_messages(title, url, content, length=length, summary_lang=summary_lang)
    
    base_url = config["base_url"].rstrip("/")
    url_endpoint = f"{base_url}/chat/completions"
    
    headers = {"Content-Type": "application/json"}
    if config["api_key"]:
        headers["Authorization"] = f"Bearer {config['api_key']}"
        
    payload = {
        "model": config["model"],
        "messages": messages,
        "stream": True
    }
    if is_reasoning_model(config["model"]):
        payload["max_tokens"] = 8192
    elif config.get("max_tokens"):
        payload["max_tokens"] = config["max_tokens"]

    append_reasoning_disabler(payload, config["model"], config["base_url"], config.get("reasoning_disabler", "auto"))
    
    def fetch_stream(use_disabler):
        current_payload = dict(payload)
        if not use_disabler:
            for field in ["chat_template_kwargs", "thinking", "thinking_config", "think", "enable_thinking"]:
                current_payload.pop(field, None)
                
        filter_obj = ThinkFilter()
        buffer = ""
        in_summary = False
        
        with httpx.stream("POST", url_endpoint, headers=headers, json=current_payload, timeout=120.0) as response:
            if response.status_code == 400 and use_disabler:
                raise ValueError("retry_without_disablers")
            response.raise_for_status()
            
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data["choices"][0]["delta"]
                    text = delta.get("content")
                    if text is not None:
                        filtered = filter_obj.filter(text)
                        if filtered:
                            buffer += filtered
                            if not in_summary and "SUMMARY:" in buffer:
                                parts = buffer.split("SUMMARY:", 1)
                                yield_text = parts[1].strip()
                                in_summary = True
                                if yield_text:
                                    yield yield_text
                                buffer = ""
                            elif in_summary:
                                yield filtered
                except Exception as parse_err:
                    logger.debug(f"Stream parse error: {parse_err}")
                    
            flushed = filter_obj.flush()
            if flushed:
                if in_summary:
                    yield flushed
                else:
                    buffer += flushed
                    if "SUMMARY:" in buffer:
                        parts = buffer.split("SUMMARY:", 1)
                        yield parts[1].strip()

    try:
        try:
            yield from fetch_stream(use_disabler=True)
        except ValueError as e:
            if str(e) == "retry_without_disablers":
                logger.warning("Stream request returned 400; retrying without reasoning disablers")
                yield from fetch_stream(use_disabler=False)
            else:
                raise
    except Exception as e:
        logger.error(f"Error in stream summary: {e}", exc_info=True)
        raise

def parse_ai_summary_response(text: str) -> tuple[str, Optional[str]]:
    """
    Parses the formatted AI response into (summary, clickbait_note).
    """
    clickbait_note = None
    summary = ""
    
    # Check if SUMMARY: exists in the text
    if "SUMMARY:" in text:
        # Split by SUMMARY: and take everything after it
        parts = text.split("SUMMARY:", 1)
        before = parts[0].strip()
        after = parts[1].strip()
        
        # Check for CLICKBAIT_NOTE in the part before SUMMARY:
        if "CLICKBAIT_NOTE:" in before:
            note_val = before.split("CLICKBAIT_NOTE:", 1)[1].strip()
            if note_val.upper() != "NONE" and note_val:
                clickbait_note = note_val
        
        summary = after
    else:
        # Fallback: try to extract from first line
        lines = text.split("\n", 1)
        first_line = lines[0] if len(lines) > 0 else ""
        rest = lines[1] if len(lines) > 1 else ""
        
        if first_line.startswith("CLICKBAIT_NOTE:"):
            note_val = first_line.replace("CLICKBAIT_NOTE:", "").strip()
            if note_val.upper() != "NONE" and note_val:
                clickbait_note = note_val
        
        # If no SUMMARY: found, use the rest as summary
        summary = rest.strip() if rest else text.strip()
        
    return summary, clickbait_note

def get_chat_language_rule() -> str:
    lang_map = {
        "zh": ("Simplified Chinese (简体中文)", "简体中文"),
        "zh-hant": ("Traditional Chinese (繁体中文)", "繁體中文"),
        "en": ("English", "英文"),
        "ja": ("Japanese (日本語)", "日语"),
        "ko": ("Korean (한국어)", "韩语"),
        "fr": ("French (Français)", "法语"),
        "es": ("Spanish (Español)", "西班牙语"),
        "de": ("German (Deutsch)", "德语"),
        "ru": ("Russian (Русский)", "俄语"),
        "pt": ("Portuguese (Português)", "葡萄牙语"),
        "it": ("Italian (Italiano)", "意大利语")
    }
    target_lang = settings.summary_language
    if target_lang == "auto" or not target_lang:
        target_lang = settings.system_language
    if not target_lang:
        target_lang = "zh"

    if target_lang in lang_map:
        eng_name, chn_name = lang_map[target_lang]
        return (
            f"CRITICAL: You must answer and discuss in {eng_name} ONLY, regardless of the language of the article content or the user's questions.\n"
            f"- 必须且只能使用 {chn_name} 回答用户的所有提问，即使原文或用户提问是其他语言，也绝对不能用其他语言回复。"
        )
    else:
        return "Use the same language as the article content or the user's questions."

def generate_chat_response_stream(
    title: str, 
    fulltext: Optional[str], 
    summary: Optional[str], 
    chat_history: List[Dict[str, str]], 
    new_message: str
):
    """
    Stream chat completion response for right-column chat interaction.
    """
    config = settings.get_ai_config("chat")
    lang_rule = get_chat_language_rule()
    
    use_reasoning = config.get("use_reasoning", True)
    
    system_prompt = (
        "You are a helpful assistant integrated into an RSS reader.\n"
        "You are helping the user discuss a specific article.\n"
        "Use the article metadata below as your primary context:\n"
        f"Article Title: {title}\n"
        f"Article Summary: {summary or 'Not available'}\n"
        f"Article Fulltext:\n{fulltext or 'Not available'}\n\n"
        "Discuss this article with the user in a helpful, concise way. Do not output markdown code blocks unless necessary. "
        f"{lang_rule}"
    )
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": new_message})
    
    base_url = config["base_url"].rstrip("/")
    url_endpoint = f"{base_url}/chat/completions"
    
    headers = {"Content-Type": "application/json"}
    if config["api_key"]:
        headers["Authorization"] = f"Bearer {config['api_key']}"
        
    payload = {
        "model": config["model"],
        "messages": messages,
        "stream": True
    }
    if is_reasoning_model(config["model"]) and use_reasoning:
        payload["max_tokens"] = 8192
    elif config.get("max_tokens"):
        payload["max_tokens"] = config["max_tokens"]
        
    if not use_reasoning:
        append_reasoning_disabler(payload, config["model"], config["base_url"], config.get("reasoning_disabler", "auto"))
        
    try:
        filter_obj = ThinkFilter()
        with httpx.stream("POST", url_endpoint, headers=headers, json=payload, timeout=30.0) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0]["delta"]
                        
                        if not use_reasoning:
                            if ("reasoning_content" in delta and delta["reasoning_content"]) or ("reasoning" in delta and delta["reasoning"]):
                                continue
                            if "content" in delta and delta["content"] is not None:
                                clean_content = filter_obj.filter(delta["content"])
                                if clean_content:
                                    yield clean_content, False
                        else:
                            # Handle reasoning_content first if present
                            if "reasoning_content" in delta and delta["reasoning_content"]:
                                yield delta["reasoning_content"], True
                                continue
                                
                            if "reasoning" in delta and delta["reasoning"]:
                                yield delta["reasoning"], True
                                continue
                                
                            if "content" in delta and delta["content"] is not None:
                                clean_content, reasoning_content = filter_obj.filter_ex(delta["content"])
                                if reasoning_content:
                                    yield reasoning_content, True
                                if clean_content:
                                    yield clean_content, False
                    except Exception:
                        pass
            flushed = filter_obj.flush()
            if flushed:
                if use_reasoning and filter_obj.in_think:
                    yield flushed, True
                elif not filter_obj.in_think:
                    yield flushed, False
    except Exception as e:
        logger.error(f"Error in stream chat response: {e}", exc_info=True)
        raise

def generate_chat_response_sync(
    title: str, 
    fulltext: Optional[str], 
    summary: Optional[str], 
    chat_history: List[Dict[str, str]], 
    new_message: str
) -> str:
    """
    Sync chat completion response for right-column chat interaction.
    """
    config = settings.get_ai_config("chat")
    lang_rule = get_chat_language_rule()
    
    use_reasoning = config.get("use_reasoning", True)
    
    system_prompt = (
        "You are a helpful assistant integrated into an RSS reader.\n"
        "You are helping the user discuss a specific article.\n"
        "Use the article metadata below as your primary context:\n"
        f"Article Title: {title}\n"
        f"Article Summary: {summary or 'Not available'}\n"
        f"Article Fulltext:\n{fulltext or 'Not available'}\n\n"
        "Discuss this article with the user in a helpful, concise way. Do not output markdown code blocks unless necessary. "
        f"{lang_rule}"
    )
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": new_message})
    
    return call_chat_completion(config, messages, response_format_json=False, disable_reasoning=not use_reasoning)

def detect_language(text: str) -> str:
    """
    A simple, zero-dependency heuristics-based language detector.
    Returns: "zh", "ja", "ko", "en" (fallback)
    """
    if not text:
        return "en"
        
    # Sample up to 1000 characters to make it fast
    sample = text[:1000]
    total_len = len(sample)
    if total_len == 0:
        return "en"
        
    # Count character types
    # Hiragana and Katakana range (Japanese specific)
    ja_kana_count = sum(1 for char in sample if '\u3040' <= char <= '\u309f' or '\u30a0' <= char <= '\u30ff')
    
    # Hangul range (Korean specific)
    ko_hangul_count = sum(1 for char in sample if '\uac00' <= char <= '\ud7a3')
    
    # Unified Han Ideographs (Chinese, Japanese Kanji, Korean Hanja)
    han_count = sum(1 for char in sample if '\u4e00' <= char <= '\u9fff')
    
    # Latin alphabet count (English, French, etc.)
    latin_count = sum(1 for char in sample if 'a' <= char.lower() <= 'z')
    
    # Heuristics
    if ja_kana_count > 5:  # If it contains Japanese kana, it's Japanese
        return "ja"
    if ko_hangul_count > 5:  # If it contains Korean hangul, it's Korean
        return "ko"
        
    # Normalizing by non-whitespace length
    non_ws = sum(1 for char in sample if not char.isspace())
    if non_ws == 0:
        return "en"
        
    han_ratio = han_count / non_ws
    
    if han_ratio > 0.30:
        return "zh"  # Mostly Chinese
        
    return "en"      # Fallback to English (covers most Western languages)

def generate_translation(title: str, text: str, target_lang: str) -> str:
    """
    Translate the given text into the target language using AI.
    Guarantees paragraph structure preservation for bilingual rendering
    by chunking the source text to prevent truncation on long articles.
    """
    if not text:
        return ""

    # Split text into paragraphs
    paragraphs = text.split("\n")
    
    # Group paragraphs into chunks (e.g., target around 800-1000 characters per chunk)
    chunks = []
    current_chunk = []
    current_len = 0
    
    for p in paragraphs:
        p_len = len(p)
        if current_len + p_len > 800 and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [p]
            current_len = p_len
        else:
            current_chunk.append(p)
            current_len += p_len + 1  # +1 for newline
            
    if current_chunk:
        chunks.append("\n".join(current_chunk))
        
    import concurrent.futures
    
    config = settings.get_ai_config("summary")  # Use summary configuration
    
    lang_map = {
        "zh": ("Simplified Chinese (简体中文)", "简体中文", "简体中文"),
        "zh-hant": ("Traditional Chinese (繁体中文)", "繁體中文", "繁体中文"),
        "en": ("English", "English", "英文"),
        "ja": ("Japanese (日本語)", "日本語", "日语"),
        "ko": ("Korean (한국어)", "한국어", "韩语"),
        "fr": ("French (Français)", "Français", "法语"),
        "es": ("Spanish (Español)", "Español", "西班牙语"),
        "de": ("German (Deutsch)", "Deutsch", "德语"),
        "ru": ("Russian (Русский)", "Русский", "俄语"),
        "pt": ("Portuguese (Português)", "Português", "葡萄牙语"),
        "it": ("Italian (Italiano)", "Italiano", "意大利语")
    }
    
    if target_lang in lang_map:
        eng_name, local_name, chn_name = lang_map[target_lang]
    else:
        eng_name, local_name, chn_name = "English", "English", "英文"
        
    system_prompt = (
        "You are a professional translator.\n"
        f"Your task is to translate the given text into {eng_name} ({local_name}).\n"
        "Rules:\n"
        "- Keep the paragraph structure and line breaks EXACTLY identical to the source text.\n"
        "- Do NOT add any notes, explanations, introduction, or prefix. Output ONLY the translated paragraphs.\n"
        f"- Translate to {eng_name} ({local_name}) faithfully, maintaining the original tone and style.\n"
        "- Do NOT output any thinking process, reasoning, or <think> tags. Output ONLY the final translation.\n"
        f"- CRITICAL: Regardless of the source language, you must translate it into {eng_name} ({local_name}). "
        "Do NOT copy or output the original text if it is in a different language. You MUST output the translation in {local_name}.\n"
        "- 绝对不要输出任何思考过程、推理内容或 <think> 标签！只能输出最终的翻译文本。\n"
        f"- 必须且只能将文本翻译为 {chn_name} ({local_name})，绝对不要直接输出原文！请输出完整的翻译后文本。"
    )
    
    def translate_single_chunk(chunk_text: str) -> str:
        if not chunk_text.strip():
            return chunk_text
            
        user_content = f"Please translate the following text into {eng_name} ({local_name}). Do NOT output the original text, only output the translated text:\n\n{chunk_text}"
        if chn_name != "英文":
            user_content = f"请将以下文本翻译为{chn_name} ({local_name})。请务必翻译，不要输出原文，只输出翻译后的文本：\n\n{chunk_text}"
            
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        try:
            return call_chat_completion(config, messages, response_format_json=False)
        except Exception as e:
            logger.error(f"Error translating chunk: {e}", exc_info=True)
            return chunk_text

    # Run translation concurrently (limit to max 3 workers to prevent overwhelming the API backend)
    max_workers = min(3, len(chunks)) if chunks else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(translate_single_chunk, chunks)
        translated_chunks = list(results)
        
    return "\n".join(translated_chunks)

def identify_promotable_topics(entries: List[Dict[str, Any]], promote_threshold: int) -> List[Dict[str, Any]]:
    """
    Given a list of uncategorized entries, cluster recurring themes using AI
    and return list of promotions: [{'category_name': 'Topic A', 'entry_ids': [1, 2]}]
    """
    if not entries:
        return []
        
    config = settings.get_ai_config("classify")
    
    entries_list = []
    for entry in entries:
        entries_list.append({
            "id": entry["id"],
            "title": entry["title"]
        })
    entries_text = json.dumps(entries_list, ensure_ascii=False)
    
    system_prompt = (
        "You are an expert RSS assistant. You are given a list of article titles from a single feed.\n"
        f"Your task is to identify recurring, specific topics or themes that appear {promote_threshold} or more times.\n"
        "For each such topic/theme:\n"
        "1. Define a concise, clean category name (maximum 2-3 words, in the exact same language as the titles).\n"
        "2. List the exact entry IDs (integers) from the input that belong to this topic.\n\n"
        "Rules:\n"
        "- Do not create generic categories like 'News', 'Others', or 'General'. Focus on specific topic groupings (e.g. 'RTX 5090', 'iOS 20', 'OpenAI Sora').\n"
        "- Do not create a topic if it has fewer than the threshold count of articles.\n"
        "- Output must be a valid JSON object matching this schema:\n"
        "{\n"
        "  \"promotions\": [\n"
        "    {\n"
        "      \"category_name\": \"Topic Name\",\n"
        "      \"entry_ids\": [1, 2, ...]\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Analyze these uncategorized articles:\n\n{entries_text}"}
    ]
    
    try:
        content = call_chat_completion(config, messages)
        data = json.loads(content)
        return data.get("promotions", [])
    except Exception as e:
        logger.error(f"Error identifying promotable topics: {e}", exc_info=True)
        return []

def identify_duplicate_categories(category_names: List[str]) -> List[Dict[str, str]]:
    """
    Given a list of category names, use AI to identify duplicate/overlapping categories
    and return a list of merge instructions: [{'source': 'AI', 'target': '人工智能'}]
    """
    if len(category_names) < 2:
        return []
        
    config = settings.get_ai_config("classify")
    
    system_prompt = (
        "You are an expert RSS assistant. You are given a list of category names (drawers) for a single feed.\n"
        "Your task is to identify categories that are semantically duplicate, synonymous, or highly overlapping (e.g. 'AI' and 'Artificial Intelligence', '苹果' and 'Apple', 'Vue3' and 'Vue').\n"
        "For each duplicate pair, specify which one should be merged (source) into the other (target).\n"
        "Keep the more standard, comprehensive, or common name as the target.\n\n"
        "Output must be a valid JSON object matching this schema:\n"
        "{\n"
        "  \"merges\": [\n"
        "    {\n"
        "      \"source\": \"Duplicate Name to Delete\",\n"
        "      \"target\": \"Standard Name to Keep\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Analyze these category names:\n\n{json.dumps(category_names, ensure_ascii=False)}"}
    ]
    
    try:
        content = call_chat_completion(config, messages)
        data = json.loads(content)
        return data.get("merges", [])
    except Exception as e:
        logger.error(f"Error identifying duplicate categories: {e}", exc_info=True)
        return []

def clean_think_block(text: str) -> str:
    text = re.sub(r'(?s)<think>.*?</think>', '', text)
    return re.sub(r'(?s)<think>.*$', '', text)

class ThinkFilter:
    def __init__(self):
        self.in_think = False
        self.buf = ""

    def filter(self, chunk: str) -> str:
        clean, _ = self.filter_ex(chunk)
        return clean

    def filter_ex(self, chunk: str) -> tuple[str, str]:
        self.buf += chunk
        output = ""
        reasoning = ""
        while True:
            if self.in_think:
                idx = self.buf.find("</think>")
                if idx != -1:
                    reasoning += self.buf[:idx]
                    self.buf = self.buf[idx + len("</think>"):]
                    self.in_think = False
                    continue
                has_partial = False
                end_tag = "</think>"
                for i in range(1, len(end_tag)):
                    if self.buf.endswith(end_tag[:i]):
                        has_partial = True
                        break
                if has_partial:
                    for i in range(len(end_tag) - 1, 0, -1):
                        if self.buf.endswith(end_tag[:i]):
                            reasoning += self.buf[:len(self.buf) - i]
                            self.buf = end_tag[:i]
                            break
                else:
                    reasoning += self.buf
                    self.buf = ""
                break
            else:
                idx = self.buf.find("<think>")
                if idx != -1:
                    output += self.buf[:idx]
                    self.buf = self.buf[idx + len("<think>"):]
                    self.in_think = True
                    continue
                start_tag = "<think>"
                partial_idx = -1
                for i in range(1, len(start_tag)):
                    if self.buf.endswith(start_tag[:i]):
                        partial_idx = len(self.buf) - i
                        break
                if partial_idx != -1:
                    output += self.buf[:partial_idx]
                    self.buf = self.buf[partial_idx:]
                else:
                    output += self.buf
                    self.buf = ""
                break
        return output, reasoning

    def flush(self) -> str:
        if not self.in_think:
            res = self.buf
            self.buf = ""
            return res
        return ""

def is_reasoning_model(model: str) -> bool:
    m = model.lower()
    return "r1" in m or "qwq" in m or "reasoner" in m or "thinking" in m or "reasoning" in m or "qwen" in m or "3.6" in m or "3.5" in m or "a3b" in m or "ornith" in m

def append_reasoning_disabler(req_payload: Dict[str, Any], model: str, base_url: str, disabler_format: str = "auto"):
    m = model.lower()
    url = base_url.lower()
    fmt = (disabler_format or "auto").lower()
    
    # 1. Explicit disabler format specified by user config
    if fmt == "vllm":
        req_payload["chat_template_kwargs"] = {"enable_thinking": False}
        req_payload["enable_thinking"] = False
        return
    elif fmt == "deepseek":
        req_payload["thinking"] = {"type": "disabled"}
        return
    elif fmt == "gemini":
        req_payload["thinking_config"] = {"thinking_budget": 0}
        return
    elif fmt == "ollama":
        req_payload["think"] = False
        return
    elif fmt == "none":
        return
        
    # 2. Default Auto-matching
    # Gemini
    if "gemini" in m or "googleapis.com" in url:
        req_payload["thinking_config"] = {"thinking_budget": 0}
        return
        
    # DeepSeek, Kimi, GLM, MiniMax
    if any(x in m for x in ["deepseek", "kimi", "glm", "minimax"]) or any(x in url for x in ["deepseek", "moonshot", "zhipu"]):
        req_payload["thinking"] = {"type": "disabled"}
        return
        
    # Ollama
    if "localhost:11434" in url or "127.0.0.1:11434" in url or "ollama" in m:
        req_payload["think"] = False
        return
        
    # vLLM / Llama.cpp / Qwen / Others
    if is_reasoning_model(model):
        req_payload["chat_template_kwargs"] = {"enable_thinking": False}
        req_payload["enable_thinking"] = False
        return
        
    # Unknown model: Check if it's NOT a known standard non-reasoning model (like GPT/Claude)
    non_reasoning_keywords = ["gpt-4", "gpt-3.5", "claude", "gemini-1.5", "mixtral", "llama-3-", "llama-3.1-", "llama-3.2-"]
    if not any(kw in m for kw in non_reasoning_keywords):
        # Apply hybrid vLLM + Ollama disabler
        req_payload["chat_template_kwargs"] = {"enable_thinking": False}
        req_payload["enable_thinking"] = False
        req_payload["think"] = False

def test_llm_reasoning(api_base_url: str, api_key: str, model: str):
    import httpx
    url = f"{api_base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Please respond with exactly one word 'hello' and absolutely nothing else."}
        ]
    }
    
    append_reasoning_disabler(payload, model, api_base_url)
    
    is_retry = False
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=payload)
            
        if response.status_code == 400:
            # Retry without disablers
            for field in ["chat_template_kwargs", "thinking", "thinking_config", "think", "enable_thinking"]:
                payload.pop(field, None)
            is_retry = True
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, headers=headers, json=payload)
                
        if response.status_code != 200:
            raise Exception(f"API returned status {response.status_code}: {response.text}")
            
        result = response.json()
        if "choices" not in result or len(result["choices"]) == 0:
            raise Exception("API returned empty choices")
            
        choice = result["choices"][0]
        content = choice["message"].get("content") or ""
        reasoning_content = choice["message"].get("reasoning_content") or ""
        
        reasoning_status = "not_reasoning"
        has_reasoning = bool(reasoning_content) or "<think>" in content or "</think>" in content
        is_reasoning_model_name = is_reasoning_model(model)
        
        if is_reasoning_model_name or has_reasoning:
            if is_retry or has_reasoning:
                reasoning_status = "unable_to_disable"
            else:
                reasoning_status = "disabled_successfully"
                
        return content, reasoning_status
    except Exception as e:
        raise Exception(f"Reasoning test failed: {str(e)}")
