import logging
import xml.etree.ElementTree as ET
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def parse_opml(opml_content: bytes) -> List[Dict[str, Any]]:
    """
    Parse OPML file content and extract feed details.
    Each returned feed dict has keys: title, url, site_url.
    """
    feeds = []
    try:
        # Parse XML from bytes
        root = ET.fromstring(opml_content)
        
        # Look for all outline elements recursively
        for outline in root.findall(".//outline"):
            xml_url = outline.get("xmlUrl")
            if xml_url:
                title = outline.get("title") or outline.get("text") or xml_url
                site_url = outline.get("htmlUrl")
                feeds.append({
                    "title": title.strip(),
                    "url": xml_url.strip(),
                    "site_url": site_url.strip() if site_url else None
                })
    except Exception as e:
        logger.error(f"Failed to parse OPML XML content: {e}", exc_info=True)
        raise ValueError("Invalid OPML XML content") from e
        
    return feeds

def generate_opml(feeds: List[Dict[str, Any]]) -> str:
    """
    Generate an OPML XML string from a list of feed records.
    Each feed record should have keys: title, url, site_url.
    """
    import xml.etree.ElementTree as ET
    import xml.dom.minidom
    
    opml = ET.Element("opml", version="1.0")
    
    head = ET.SubElement(opml, "head")
    title_el = ET.SubElement(head, "title")
    title_el.text = "KickRSS Subscriptions"
    
    body = ET.SubElement(opml, "body")
    
    for f in feeds:
        title = f.get("title") or f.get("url") or ""
        xml_url = f.get("url") or ""
        html_url = f.get("site_url") or ""
        
        outline_attrs = {
            "type": "rss",
            "text": title,
            "title": title,
            "xmlUrl": xml_url,
        }
        if html_url:
            outline_attrs["htmlUrl"] = html_url
            
        ET.SubElement(body, "outline", **outline_attrs)
        
    rough_string = ET.tostring(opml, encoding="utf-8")
    reparsed = xml.dom.minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

