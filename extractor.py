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

def fetch_and_extract_fulltext(url: str) -> tuple[str, str, str]:
    """
    Fetch webpage content and extract clean fulltext.
    First tries trafilatura. If that fails, falls back to the JS rendering service if configured.
    Returns a tuple of (content, status, fetcher).
    """
    min_chars = settings.min_text_chars
    
    # Try 1: trafilatura direct fetch & extract
    logger.info(f"Extracting fulltext via trafilatura for URL: {url}")
    try:
        html = trafilatura.fetch_url(url)
        if html:
            if is_waf_or_blocked(html):
                logger.warning(f"trafilatura direct fetch hit WAF block for {url}")
            else:
                content = trafilatura.extract(html, include_images=True, output_format="markdown")
                if content and len(content) >= min_chars:
                    if is_waf_or_blocked(content):
                        logger.warning(f"trafilatura extracted content contains WAF indicators for {url}")
                    else:
                        logger.info(f"Successfully extracted fulltext ({len(content)} chars) via trafilatura")
                        return content, "ok", "trafilatura"
    except Exception as e:
        logger.warning(f"trafilatura direct fetch/extract failed for {url}: {e}")

    # Try 2: Fallback to JS rendering service
    rendering_cfg = settings.data.get("fulltext", {})
    rendering_service_url = rendering_cfg.get("rendering_service_url")
    
    if rendering_service_url:
        logger.info(f"Falling back to rendering service for URL: {url} -> {rendering_service_url}")
        try:
            # Call the rendering service (sending JSON payload)
            with httpx.Client(timeout=30.0) as client:
                response = client.post(rendering_service_url, json={"url": url})
            
            if response.status_code == 200:
                rendered_html = response.text
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
