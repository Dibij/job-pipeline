"""Transformers converting source-specific raw payloads into NormalizedJob models."""
import email.utils
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

from src.models.job import NormalizedJob


import html

_MOJIBAKE_PATTERN = re.compile(
    r"([\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}|[\xf0-\xf4][\x80-\xbf]{3})+"
)


def fix_mojibake(text: str) -> str:
    """Recover UTF-8 byte sequences that were mistakenly decoded as latin-1."""
    def repl(match):
        s = match.group(0)
        try:
            return s.encode("latin-1").decode("utf-8")
        except UnicodeDecodeError:
            return s
    return _MOJIBAKE_PATTERN.sub(repl, text)


def clean_description_text(content: Optional[str]) -> str:
    """Clean HTML tags, decode entities, repair mojibake, and normalize whitespace."""
    if not content:
        return ""
    # 1. Unescape HTML entities (twice for double-escaped entities like &amp;nbsp;)
    text = html.unescape(content)
    text = html.unescape(text)

    # 2. Strip HTML tags
    if "<" in text and ">" in text:
        soup = BeautifulSoup(text, "html.parser")
        text = soup.get_text(separator=" ")

    # 3. Repair mojibake
    text = fix_mojibake(text)

    # 4. Normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_html(html_content: Optional[str]) -> str:
    """Clean HTML tags and normalize whitespace into plain text."""
    return clean_description_text(html_content)


def parse_timestamp(dt_val: Any) -> Optional[datetime]:
    """Parse various datetime representations into UTC datetime."""
    if not dt_val:
        return None

    if isinstance(dt_val, (int, float)):
        # Epoch timestamp
        return datetime.fromtimestamp(dt_val, tz=timezone.utc)

    if isinstance(dt_val, str):
        dt_str = dt_val.strip()
        if not dt_str:
            return None
        # Try ISO format
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            pass
        # Try RFC 2822 format (used by RSS feeds, e.g. "Wed, 14 Oct 2026 07:31:00 +0000")
        try:
            return email.utils.parsedate_to_datetime(dt_str)
        except (ValueError, TypeError):
            pass

    return None


def transform_arbeitnow(payload: Dict[str, Any]) -> NormalizedJob:
    """Transform Arbeitnow raw item into NormalizedJob."""
    raw_desc = payload.get("description", "")
    plain_desc = strip_html(raw_desc) or payload.get("title", "")

    posted_at = parse_timestamp(payload.get("created_at"))
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]

    job_types = payload.get("job_types") or []
    job_type_str = job_types[0] if isinstance(job_types, list) and job_types else None

    return NormalizedJob(
        source="arbeitnow",
        external_id=str(payload.get("slug") or payload.get("url") or "").strip(),
        title=payload.get("title", "Untitled Position"),
        company_name=payload.get("company_name", "Unknown Company"),
        location_raw=payload.get("location"),
        is_remote=bool(payload.get("remote", False)),
        remote_restriction="unspecified",  # Arbeitnow does not expose a restriction field
        job_type=job_type_str,
        description_text=plain_desc,
        description_html=raw_desc,
        apply_url=payload.get("url", ""),
        tags=[str(t).strip() for t in tags if t],
        posted_at=posted_at,
    )


def transform_remotive(payload: Dict[str, Any]) -> NormalizedJob:
    """Transform Remotive raw item into NormalizedJob."""
    raw_desc = payload.get("description", "")
    plain_desc = strip_html(raw_desc) or payload.get("title", "")

    posted_at = parse_timestamp(payload.get("publication_date"))
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]

    location = payload.get("candidate_required_location") or ""
    is_remote = True  # All Remotive jobs are remote
    remote_restriction = location.strip() if location else "unspecified"  # source says nothing → unspecified

    return NormalizedJob(
        source="remotive",
        external_id=str(payload.get("id") or payload.get("url") or "").strip(),
        title=payload.get("title", "Untitled Position"),
        company_name=payload.get("company_name", "Unknown Company"),
        company_url=payload.get("company_logo_url"),
        location_raw=location,
        is_remote=is_remote,
        remote_restriction=remote_restriction,
        job_type=payload.get("job_type"),
        description_text=plain_desc,
        description_html=raw_desc,
        apply_url=payload.get("url", ""),
        tags=[str(t).strip() for t in tags if t],
        posted_at=posted_at,
    )


def transform_himalayas(payload: Dict[str, Any]) -> NormalizedJob:
    """Transform Himalayas raw item into NormalizedJob."""
    raw_desc = payload.get("description", "")
    plain_desc = strip_html(raw_desc) or payload.get("excerpt") or payload.get("title", "")

    posted_at = parse_timestamp(payload.get("pubDate"))
    
    # Process tags from categories and seniority
    tags: List[str] = []
    cats = payload.get("categories") or []
    if isinstance(cats, list):
        tags.extend([str(c).strip() for c in cats if c])
    elif isinstance(cats, str):
        tags.append(cats.strip())

    sens = payload.get("seniority") or []
    if isinstance(sens, list):
        tags.extend([str(s).strip() for s in sens if s])
    elif isinstance(sens, str):
        tags.append(sens.strip())

    # Remote & Location
    loc_restrictions = payload.get("locationRestrictions") or []
    if isinstance(loc_restrictions, list) and loc_restrictions:
        loc_str = ", ".join(str(l).strip() for l in loc_restrictions if l)
        remote_restr = loc_str
    elif isinstance(loc_restrictions, str) and loc_restrictions.strip():
        loc_str = loc_restrictions.strip()
        remote_restr = loc_str
    else:
        loc_str = "Remote"
        remote_restr = "unspecified"

    external_id = str(payload.get("guid") or payload.get("applicationLink") or "").strip()

    return NormalizedJob(
        source="himalayas",
        external_id=external_id,
        title=payload.get("title", "Untitled Position"),
        company_name=payload.get("companyName", "Unknown Company"),
        company_url=payload.get("companyLogo"),
        location_raw=loc_str,
        is_remote=True,
        remote_restriction=remote_restr,
        job_type=payload.get("employmentType"),
        description_text=plain_desc,
        description_html=raw_desc,
        apply_url=payload.get("applicationLink") or payload.get("guid") or "",
        tags=tags,
        posted_at=posted_at,
    )


def transform_weworkremotely(payload: Dict[str, Any]) -> NormalizedJob:
    """Transform We Work Remotely RSS item into NormalizedJob."""
    raw_desc = payload.get("description", "")
    plain_desc = strip_html(raw_desc)

    # WWR titles are "Company: Job Title"
    raw_title = payload.get("title", "Untitled Position")
    if ": " in raw_title:
        company_name, title = raw_title.split(": ", 1)
    else:
        company_name = "Unknown Company"
        title = raw_title

    posted_at = parse_timestamp(payload.get("pubDate"))

    # Region represents location restriction
    region = (payload.get("region") or "").strip()
    if not region:
        remote_restriction = "unspecified"
        location_raw = "Remote"
    else:
        remote_restriction = region
        location_raw = region

    # Tags from category and type
    tags: List[str] = []
    cat = payload.get("category")
    if cat:
        tags.append(str(cat).strip())
    jtype = payload.get("type")

    external_id = str(payload.get("guid") or payload.get("link") or "").strip()

    return NormalizedJob(
        source="weworkremotely",
        external_id=external_id,
        title=title.strip(),
        company_name=company_name.strip(),
        location_raw=location_raw,
        is_remote=True,  # All WWR jobs are remote
        remote_restriction=remote_restriction,
        job_type=jtype,
        description_text=plain_desc or title,
        description_html=raw_desc,
        apply_url=payload.get("link") or payload.get("guid") or "",
        tags=tags,
        posted_at=posted_at,
    )


def transform_remoteok(payload: Dict[str, Any]) -> NormalizedJob:
    """Transform Remote OK raw item into NormalizedJob."""
    raw_desc = payload.get("description", "")
    plain_desc = strip_html(raw_desc) or payload.get("position", "")

    posted_at = parse_timestamp(payload.get("date") or payload.get("epoch"))

    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]

    location = (payload.get("location") or "").strip()
    if not location or location.lower() == "remote":
        location_raw = "Remote"
        remote_restriction = "unspecified"
    elif location.lower() in ("worldwide", "anywhere"):
        location_raw = location
        remote_restriction = location
    else:
        location_raw = location
        remote_restriction = location

    external_id = str(payload.get("id") or payload.get("slug") or "").strip()

    return NormalizedJob(
        source="remoteok",
        external_id=external_id,
        title=payload.get("position", "Untitled Position"),
        company_name=payload.get("company", "Unknown Company"),
        company_url=payload.get("company_logo") or payload.get("logo"),
        location_raw=location_raw,
        is_remote=True,  # All Remote OK jobs are remote
        remote_restriction=remote_restriction,
        description_text=plain_desc,
        description_html=raw_desc,
        apply_url=payload.get("apply_url") or payload.get("url") or "",
        tags=[str(t).strip() for t in tags if t],
        posted_at=posted_at,
    )


def transform_jobicy(payload: Dict[str, Any]) -> NormalizedJob:
    """Transform Jobicy raw item into NormalizedJob."""
    raw_desc = payload.get("jobDescription", "")
    plain_desc = strip_html(raw_desc) or payload.get("jobExcerpt") or payload.get("jobTitle", "")

    posted_at = parse_timestamp(payload.get("pubDate"))

    # Tags from jobIndustry
    tags: List[str] = []
    industries = payload.get("jobIndustry") or []
    if isinstance(industries, list):
        tags.extend([str(i).strip() for i in industries if i])
    elif isinstance(industries, str):
        tags.append(industries.strip())

    # jobGeo is a comma-separated location restriction string
    geo = (payload.get("jobGeo") or "").strip()
    if not geo:
        location_raw = "Remote"
        remote_restriction = "unspecified"
    elif geo.lower() in ("worldwide", "anywhere"):
        location_raw = geo
        remote_restriction = geo
    else:
        location_raw = geo
        remote_restriction = geo

    job_types = payload.get("jobType") or []
    job_type = job_types[0] if isinstance(job_types, list) and job_types else None

    external_id = str(payload.get("id") or payload.get("jobSlug") or "").strip()

    return NormalizedJob(
        source="jobicy",
        external_id=external_id,
        title=payload.get("jobTitle", "Untitled Position"),
        company_name=payload.get("companyName", "Unknown Company"),
        company_url=payload.get("companyLogo"),
        location_raw=location_raw,
        is_remote=True,  # All Jobicy listings are remote
        remote_restriction=remote_restriction,
        job_type=job_type,
        description_text=plain_desc,
        description_html=raw_desc,
        apply_url=payload.get("url") or "",
        tags=tags,
        posted_at=posted_at,
    )


def transform_hackernews(payload: Dict[str, Any]) -> NormalizedJob:
    """Transform Hacker News Who is hiring comment into NormalizedJob."""
    raw_html = payload.get("text", "")
    plain_desc = strip_html(raw_html)

    # First line / paragraph contains the structured header
    first_part = raw_html.split("<p>")[0] if "<p>" in raw_html else raw_html.split("\n")[0]
    header = strip_html(first_part)

    # Standardize common delimiters: em-dash, en-dash, bullet, middle dot -> pipe
    header_clean = header.replace("\u2014", "|").replace("\u2013", "|").replace("\u2022", "|").replace("\u00b7", "|")
    parts = [p.strip() for p in header_clean.split("|") if p.strip()]

    # Extract company, title, location
    company_name = "Unknown Company"
    title = "Hacker News Role"
    location_raw = "Remote"
    remote_restriction = "unspecified"
    is_remote = False

    # Check for clean "Company | Role | Location" header:
    # Must have at least 2 parts, and first part is <= 80 chars without multi-sentence text
    is_clean_header = (
        len(parts) >= 2
        and len(parts[0]) <= 80
        and not any(s in parts[0] for s in [". ", "? ", "! "])
    )

    if is_clean_header:
        # First part is almost always the company name
        comp_candidate = parts[0]
        comp_candidate = re.sub(r"https?://[^\s)]+", "", comp_candidate)
        comp_candidate = re.sub(r"\(.*?\)", "", comp_candidate).strip()
        if comp_candidate:
            company_name = comp_candidate

        # Find title among remaining parts
        title_found = False
        for p in parts[1:]:
            p_lower = p.lower()
            # Skip pure URLs
            if p_lower.startswith("http://") or p_lower.startswith("https://") or any(ext in p_lower for ext in [".com", ".tech", ".io", ".ai", ".org", ".co"]):
                continue
            # Skip if this part is just generic status
            if p_lower in ["remote", "onsite", "hybrid", "full-time", "part-time", "contract"]:
                continue
            if not title_found:
                title = p
                title_found = True
                break

        if not title_found and len(parts) > 1:
            title = parts[1]
    else:
        # No clean header: fallback title, full text only in description
        title = "Hacker News Role"
        # Try to extract clean company if header starts with "Company - " or "Company: " (<= 50 chars)
        match_co = re.match(r"^([A-Za-z0-9\s&.,'-]{2,50})\s+[-–—:]\s+", header)
        if match_co:
            cand = match_co.group(1).strip()
            if not any(stop in cand.lower() for stop in ["we are", "looking for", "hiring", "http"]):
                company_name = cand

    # Detect remote status
    full_text_lower = f"{header} {plain_desc}".lower()
    if "remote" in full_text_lower:
        is_remote = True
        # Look for explicit remote restriction in header (e.g. REMOTE(Worldwide), (Remote US), Remote - Europe)
        m_prefix = re.search(r"remote\s*\(([^)]+)\)", header, re.IGNORECASE)
        m_paren = re.search(r"\(([^)]*\bremote\b[^)]*)\)", header, re.IGNORECASE)
        m2 = re.search(r"remote\s*[-–—:]\s*([A-Za-z\s,]{2,40})", header, re.IGNORECASE)
        if m_prefix and len(m_prefix.group(1).strip()) <= 100:
            remote_restriction = m_prefix.group(1).strip()
            location_raw = remote_restriction
        elif m_paren and len(m_paren.group(1).strip()) <= 100:
            remote_restriction = m_paren.group(1).strip()
            location_raw = remote_restriction
        elif m2 and len(m2.group(1).strip()) <= 100:
            remote_restriction = m2.group(1).strip()
            location_raw = remote_restriction
        else:
            location_raw = "Remote"
            remote_restriction = "unspecified"
    elif "onsite" in full_text_lower:
        is_remote = False
        location_raw = "Onsite"
        remote_restriction = "unspecified"
    else:
        is_remote = False
        location_raw = "Unspecified"
        remote_restriction = "unspecified"

    # Extract apply link
    apply_url = ""
    links = re.findall(r'href=["\'](https?://[^"\']+)["\']', raw_html)
    if not links:
        links = re.findall(r'(https?://[^\s<>"()]+)', raw_html)
    if links:
        apply_url = links[0]
    else:
        hn_id = payload.get("id")
        apply_url = f"https://news.ycombinator.com/item?id={hn_id}"

    posted_at = parse_timestamp(payload.get("time"))
    item_id = str(payload.get("id", "")).strip()

    return NormalizedJob(
        source="hackernews",
        external_id=item_id,
        title=title.strip(),
        company_name=company_name.strip(),
        location_raw=location_raw.strip(),
        is_remote=is_remote,
        remote_restriction=remote_restriction.strip(),
        description_text=plain_desc or title,
        description_html=raw_html,
        apply_url=apply_url,
        tags=["HackerNews", "Who is Hiring"],
        posted_at=posted_at,
    )


def transform_raw_listing(source: str, payload: Dict[str, Any]) -> NormalizedJob:
    """Dispatcher transforming raw item payload based on source name."""
    source_lower = source.lower().strip()
    if source_lower == "arbeitnow":
        return transform_arbeitnow(payload)
    elif source_lower == "remotive":
        return transform_remotive(payload)
    elif source_lower == "himalayas":
        return transform_himalayas(payload)
    elif source_lower == "weworkremotely":
        return transform_weworkremotely(payload)
    elif source_lower == "remoteok":
        return transform_remoteok(payload)
    elif source_lower == "jobicy":
        return transform_jobicy(payload)
    elif source_lower == "hackernews":
        return transform_hackernews(payload)
    else:
        raise ValueError(f"No transformer registered for source: '{source}'")





