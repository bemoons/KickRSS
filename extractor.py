import logging
import httpx
import trafilatura
from config import settings

logger = logging.getLogger(__name__)

def is_waf_or_blocked(html: str) -> bool:
    if not html:
        return False
    html_lower = html.lower()
    waf_keywords = [
        "aliyun_waf",
        "cf_app_waf",
        "为了更好的访问体验，请进行验证",
        "__cf_chl_opt",
        "challenge-platform",
        "sec-cpt",
        "安全验证"
    ]
    for kw in waf_keywords:
        if kw.lower() in html_lower:
            return True
    return False

def is_video_page(url: str, html_or_markdown: str) -> bool:
    if not html_or_markdown:
        return False
    lower_content = html_or_markdown.lower()
    
    # Direct HTML metadata and class checks
    if ('articleSection":"视频"' in html_or_markdown or
        'is_video_article":true' in html_or_markdown or
        'is_video_article":1' in html_or_markdown or
        'class="article__top-video"' in html_or_markdown or
        'class="video-player-container"' in html_or_markdown or
        'property="og:type" content="video"' in html_or_markdown or
        'property="og:type" content="video.other"' in html_or_markdown):
        return True
        
    # Markdown / General URL / CDN checks
    if "huxiu.com" in url:
        if ("s2-video.huxiucdn.com" in lower_content or
            "v2-video.huxiucdn.com" in lower_content or
            "[video " in lower_content):
            return True
            
    # General third-party embeds
    if ("player.bilibili.com" in lower_content or
        "youtube.com/embed" in lower_content or
        "player.vimeo.com" in lower_content):
        return True
        
    return False

def is_video_url(url: str) -> bool:
    lower_url = url.lower()
    return ("youtube.com/watch" in lower_url or
            "youtu.be/" in lower_url or
            "bilibili.com/video/" in lower_url or
            "v.qq.com/x/page/" in lower_url or
            "v.qq.com/x/cover/" in lower_url)



def fetch_and_extract_fulltext(url: str) -> tuple[str, str, str]:
    """
    Fetch webpage content and extract clean fulltext.
    First tries trafilatura. If that fails, falls back to the JS rendering service if configured.
    Returns a tuple of (content, status, fetcher).
    """
    min_chars = settings.min_text_chars
    
    # Strip tracking query parameters for huxiu.com to prevent triggering WAF block rules
    if "huxiu.com" in url and "?" in url:
        url = url.split("?")[0]
        
    if is_video_url(url):
        logger.info(f"Detected video page via URL pattern: {url}")
        return "此文章主要包含视频/多媒体内容，无正文可提取。请点击标题或右上角链接查看原始视频。", "video", "trafilatura"
    
    # Try 1: trafilatura direct fetch & extract
    logger.info(f"Extracting fulltext via trafilatura for URL: {url}")
    try:
        html = trafilatura.fetch_url(url)
        if html:
            if is_waf_or_blocked(html):
                logger.warning(f"trafilatura direct fetch hit WAF block for {url}")
            else:
                if is_video_page(url, html):
                    logger.info(f"Detected video page via direct HTML: {url}")
                    return "此文章主要包含视频/多媒体内容，无正文可提取。请点击标题或右上角链接查看原始视频。", "video", "trafilatura"
                content = trafilatura.extract(html, include_images=True, output_format="markdown")
                if content and len(content) >= min_chars:
                    if is_waf_or_blocked(content):
                        logger.warning(f"trafilatura extracted content contains WAF indicators for {url}")
                    else:
                        logger.info(f"Successfully extracted fulltext ({len(content)} chars) via trafilatura")
                        return content, "ok", "trafilatura"
    except Exception as e:
        logger.warning(f"trafilatura direct fetch/extract failed for {url}: {e}")

    # Try 2: Fallback based on config (jina or render_service)
    fallback_engine = settings.fallback_engine
    
    if fallback_engine == "jina":
        jina_url = settings.jina_reader_url
        if jina_url:
            if not jina_url.endswith("/"):
                jina_url += "/"
            full_jina_url = jina_url + url
            logger.info(f"Falling back to Jina Reader for URL: {url} -> {full_jina_url}")
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(full_jina_url)
                if response.status_code == 200:
                    jina_text = response.text or ""
                    if "Markdown Content:" in jina_text:
                        content = jina_text.split("Markdown Content:", 1)[1].strip()
                    else:
                        content = jina_text.strip()
                    
                    if is_video_page(url, content):
                        logger.info(f"Detected video page via Jina response: {url}")
                        return "此文章主要包含视频/多媒体内容，无正文可提取。请点击标题或右上角链接查看原始视频。", "video", "jina"
                    
                    if content and len(content) >= min_chars:
                        if is_waf_or_blocked(content):
                            logger.warning(f"Jina Reader extracted content contains WAF indicators for {url}")
                        else:
                            logger.info(f"Successfully extracted fulltext ({len(content)} chars) via Jina Reader")
                            return content, "ok", "jina"
                else:
                    logger.warning(f"Jina Reader returned status code {response.status_code}")
            except Exception as e:
                logger.error(f"Failed to fetch from Jina Reader for {url}: {e}")
                
    elif fallback_engine == "render_service":
        rendering_cfg = settings.data.get("fulltext", {})
        rendering_service_url = rendering_cfg.get("rendering_service_url")
        if rendering_service_url:
            logger.info(f"Falling back to rendering service for URL: {url} -> {rendering_service_url}")
            try:
                # Call the rendering service (sending JSON payload)
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(rendering_service_url, json={"url": url})
                
                if response.status_code == 200:
                    try:
                        rendered_html = response.json().get("html", "")
                    except Exception:
                        rendered_html = response.text
                    
                    if is_video_page(url, rendered_html):
                        logger.info(f"Detected video page via rendering service response: {url}")
                        return "此文章主要包含视频/多媒体内容，无正文可提取。请点击标题或右上角链接查看原始视频。", "video", "rendering_service"
                    
                    if is_waf_or_blocked(rendered_html):
                        logger.warning(f"Rendering service response hit WAF block for {url}")
                    else:
                        content = trafilatura.extract(rendered_html, include_images=True, output_format="markdown")
                        if content and len(content) >= min_chars:
                            if is_waf_or_blocked(content):
                                logger.warning(f"Rendering service extracted content contains WAF indicators for {url}")
                            else:
                                logger.info(f"Successfully extracted fulltext ({len(content)} chars) via rendering service")
                                return content, "ok", "rendering_service"
                else:
                    logger.warning(f"Rendering service returned status code {response.status_code}")
            except Exception as e:
                logger.error(f"Failed to fetch from rendering service for {url}: {e}")
                
    return "", "fetch_failed", "trafilatura"
