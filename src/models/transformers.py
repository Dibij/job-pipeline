"""Transformers converting source-specific raw payloads into NormalizedJob models."""
import email.utils
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

from src.models.job import NormalizedJob

logger = logging.getLogger(__name__)


import html

_MOJIBAKE_PATTERN = re.compile(
    r"([\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}|[\xf0-\xf4][\x80-\xbf]{3})+"
)

_ATS_LINK_PATTERNS = [
    re.compile(r"https?://(?:boards\.greenhouse\.io|job-boards\.greenhouse\.io|grnh\.se)/[^\s\"\'<>]+"),
    re.compile(r"https?://jobs\.lever\.co/[^\s\"\'<>]+"),
    re.compile(r"https?://jobs\.ashbyhq\.com/[^\s\"\'<>]+"),
    re.compile(r"https?://apply\.workable\.com/[^\s\"\'<>]+"),
]

COUNTRY_LOCK_RE = re.compile(
    r"\b(must (?:be )?(?:reside|live|located|based) in|"
    r"authori[sz]ed to work in|us citizen|green card|"
    r"w-?2 only|security clearance)\b",
    re.IGNORECASE,
)


def extract_country_restriction(content: Optional[str], location_raw: Optional[str] = None) -> Optional[str]:
    """Extract explicit country or citizenship restriction from text or location."""
    combined = f"{location_raw or ''} {content or ''}".strip()
    if not combined:
        return None
    match = COUNTRY_LOCK_RE.search(combined)
    if match:
        return match.group(0)
    return None


def extract_direct_ats_link(content: Optional[str]) -> Optional[str]:
    """Scan HTML or text for known ATS links and return the first clean match."""
    if not content:
        return None
    unescaped = html.unescape(html.unescape(content))
    for pat in _ATS_LINK_PATTERNS:
        match = pat.search(unescaped)
        if match:
            url = match.group(0)
            url = re.sub(r"[\.,;\)\]'\"]+$", "", url)
            return url
    return None


def fix_mojibake(text: str) -> str:
    """Recover UTF-8 byte sequences that were mistakenly decoded as latin-1, stray Â, and artifacts."""
    def repl(match):
        s = match.group(0)
        try:
            return s.encode("latin-1").decode("utf-8")
        except UnicodeDecodeError:
            return s

    text = _MOJIBAKE_PATTERN.sub(repl, text)
    # Stray Â (U+00C2) preceding spaces, NBSP, or quotes from mis-decoded UTF-8
    text = text.replace("\xc2\xa0", " ").replace("Â ", " ").replace("Â", "")
    replacements = [
        ("â€™", "'"),
        ("â€˜", "'"),
        ("â€œ", '"'),
        ("â€\x9d", '"'),
        ("â€“", "-"),
        ("â€”", "-"),
        ("â€¦", "..."),
        ("â€¢", "*"),
        ("â€", '"'),
        ("\ufffd", ""),  # unicode replacement character
    ]
    for bad, good in replacements:
        text = text.replace(bad, good)
    return text


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


# Patterns for parsing Hacker News "Who is hiring?" thread headers
_HN_URL_EMAIL_RE = re.compile(
    r"^https?://|[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|\.(?:com|org|net|io|ai|tech|co|app|dev|me)(?:/|$)",
    re.IGNORECASE,
)
_HN_COMPENSATION_RE = re.compile(
    r"[$€£¥]"
    r"|\b(?:salary|equity|equity\s*\+?\s*salary|salary\s*\+?\s*equity|equity\s+only|doe|d\.o\.e\.|competitive\s+compensation|negotiable)\b"
    r"|\b\d+k\s*[-–/]\s*\d+k\b"
    r"|\b\d+[-–]\d+k\b"
    r"|\b\d+\s*k\s*(?:usd|eur|gbp|/year|/yr)\b",
    re.IGNORECASE,
)
_HN_WORK_TYPE_RE = re.compile(
    r"^(?:remote|onsite|hybrid|full[- ]?time|part[- ]?time|contract|contractor|freelance|internship|intern|visa|visa\s+sponsorship)$",
    re.IGNORECASE,
)
_HN_LOCATION_HINTS_RE = re.compile(
    r"\b(?:san francisco|sf|bay area|new york|nyc|london|berlin|toronto|austin|seattle|boston|zurich|amsterdam|paris|tokyo|chicago|los angeles|vancouver|montreal)\b"
    r"|,\s*(?:[A-Z]{2}\b|ontario|quebec|bc|alberta)"
    r"|\b(?:usa|us|uk|united states|united kingdom|canada|germany|france|netherlands|switzerland|australia|spain|ireland|poland|austria)\b"
    r"|\b(?:cet|cest|est|edt|pst|pdt|cst|cdt|gmt|utc)(?:\s*[±+-]\s*\d+)?\b"
    r"|\btime\s*zones?\b|\bhours\b"
    r"|\b(?:remote|onsite|hybrid)\s*\([^)]+\)",
    re.IGNORECASE,
)
_HN_ROLE_SIGNALS_RE = re.compile(
    r"\b(?:engineer|developer|programmer|architect|scientist|lead|manager|director|head of|vp|designer|specialist|analyst|cto|founder|co-founder|evaluator|sourcer|fellow)\b",
    re.IGNORECASE,
)
_HN_UNPARSEABLE_PATTERNS = [
    re.compile(r"\b(?:GMT|UTC)[-+]?\d+", re.IGNORECASE),
    re.compile(r"GMT\s*[-–—<>]+\s*GMT", re.IGNORECASE),
    re.compile(r"^\s*(?:remote|onsite|hybrid|unspecified|role-dependent|see below)\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:remote\s*\(.*?\)|onsite\s+in\s+.*?|\d+\s+days\s+hybrid\s+in\s+.*?)\s*$", re.IGNORECASE),
    re.compile(r",\s*[A-Z]{2}\b"),  # e.g. Austin, TX; Santa Clara, CA; Toronto, Ontario
    re.compile(r"\b(?:san francisco|new york|berlin|zurich|austin|toronto|seattle|london|tokyo|paris)\b", re.IGNORECASE),
    re.compile(r"^\s*https?://", re.IGNORECASE),
    re.compile(r"^\s*earth\s*$", re.IGNORECASE),
    re.compile(r"^\s*hacker news role\s*$", re.IGNORECASE),
    re.compile(r"^\s*multiple (?:roles|engineering)\b", re.IGNORECASE),
    re.compile(r"^\s*(?:design,\s*engineering,\s*gtm,\s*sales|future shaprs|lkjlkjxcv)\s*$", re.IGNORECASE),
]


def is_unparseable_hn_title(title: str) -> bool:
    """Check if HN title looks like a location, timezone, URL, or placeholder."""
    t = (title or "").strip()
    if not t or t.lower() in ("hacker news role", "earth", "remote", "see below", "equity + salary"):
        return True
    has_role = bool(_HN_ROLE_SIGNALS_RE.search(t))
    for pat in _HN_UNPARSEABLE_PATTERNS:
        if pat.search(t):
            if not has_role or t.lower().startswith("remote (") or t.lower().startswith("onsite in ") or "days hybrid in" in t.lower() or t.startswith("http"):
                return True
            if not has_role:
                return True
    if not has_role and ("," in t or "/" in t or len(t) < 5):
        return True
    return False


def transform_hackernews(payload: Dict[str, Any]) -> Optional[NormalizedJob]:
    """Transform Hacker News Who is hiring comment into NormalizedJob.

    Parses pipe- or dash-separated header into company, title, location, and remote status.
    Rejects rows where no valid role title exists (e.g. title looks like location or compensation).
    Sets exclude_reason='unparseable_title' when title cannot be parsed cleanly.
    """
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

        # Classify remaining parts to unswap title, location, compensation
        role_candidates: List[str] = []
        location_candidates: List[str] = []
        other_candidates: List[str] = []

        for p in parts[1:]:
            if _HN_URL_EMAIL_RE.search(p):
                continue
            if _HN_COMPENSATION_RE.search(p):
                continue
            if _HN_WORK_TYPE_RE.match(p):
                continue
            if _HN_ROLE_SIGNALS_RE.search(p):
                role_candidates.append(p)
                continue
            if _HN_LOCATION_HINTS_RE.search(p):
                location_candidates.append(p)
                continue
            other_candidates.append(p)

        if role_candidates:
            title = role_candidates[0]
        elif other_candidates:
            cand = other_candidates[0]
            title = cand
        else:
            # All parts were location, compensation, work_type, or URL — fallback title
            title = "Hacker News Role"

        if location_candidates:
            location_raw = location_candidates[0]
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
            if location_raw == "Remote":
                location_raw = remote_restriction
        elif m_paren and len(m_paren.group(1).strip()) <= 100:
            remote_restriction = m_paren.group(1).strip()
            if location_raw == "Remote":
                location_raw = remote_restriction
        elif m2 and len(m2.group(1).strip()) <= 100:
            remote_restriction = m2.group(1).strip()
            if location_raw == "Remote":
                location_raw = remote_restriction
    elif "onsite" in full_text_lower:
        is_remote = False
        if location_raw == "Remote":
            location_raw = "Onsite"
    else:
        is_remote = False
        if location_raw == "Remote":
            location_raw = "Unspecified"

    # Extract apply link
    apply_url = ""
    direct_ats = extract_direct_ats_link(raw_html)
    if direct_ats:
        apply_url = direct_ats
    else:
        raw_unescaped = html.unescape(raw_html)
        links = re.findall(r'href=["\'](https?://[^"\'\s>]+)["\']', raw_unescaped)
        if not links:
            links = re.findall(r'(https?://[^\s<>"()]+)', raw_unescaped)
        if links:
            apply_url = links[0]
        else:
            hn_id = payload.get("id")
            apply_url = f"https://news.ycombinator.com/item?id={hn_id}"

    posted_at = parse_timestamp(payload.get("time"))
    item_id = str(payload.get("id", "")).strip()

    exclude_reason = None
    if is_unparseable_hn_title(title):
        exclude_reason = "unparseable_title"

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
        exclude_reason=exclude_reason,
    )


def transform_ats_greenhouse(payload: Dict[str, Any], source: str) -> "NormalizedJob":
    """Transform Greenhouse board API item into NormalizedJob."""
    meta = payload.get("_ats_meta", {})
    company_name = meta.get("company_name") or payload.get("company_name", "Unknown Company")

    title = payload.get("title", "Untitled Position")
    loc_obj = payload.get("location") or {}
    location_raw = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj)
    content_html = payload.get("content", "")
    desc_clean = clean_description_text(content_html) if content_html else title
    is_remote = any(
        k in location_raw.lower() for k in ["remote", "anywhere", "virtual", "distributed"]
    ) or "remote" in title.lower()
    remote_restriction = location_raw.strip() if location_raw.strip() else "unspecified"

    apply_url = payload.get("absolute_url") or payload.get("url") or ""
    external_id = str(payload.get("id", "")).strip()

    return NormalizedJob(
        source=source,
        external_id=external_id,
        title=title,
        company_name=company_name,
        location_raw=location_raw or "Remote",
        is_remote=is_remote,
        remote_restriction=remote_restriction,
        job_type="full-time",
        description_text=desc_clean,
        description_html=content_html,
        apply_url=apply_url,
        tags=[],
    )


def transform_ats_lever(payload: Dict[str, Any], source: str) -> "NormalizedJob":
    """Transform Lever postings API item into NormalizedJob."""
    meta = payload.get("_ats_meta", {})
    company_name = meta.get("company_name") or "Unknown Company"

    title = payload.get("text", "Untitled Position")
    cats = payload.get("categories") or {}
    location_raw = cats.get("location", "") if isinstance(cats, dict) else ""
    workplace_type = str(payload.get("workplaceType", "")).lower()
    content_html = (payload.get("description", "") or "") + " " + (payload.get("additional", "") or "")
    desc_clean = clean_description_text(content_html) if content_html.strip() else (
        payload.get("descriptionPlain", "") or title
    )
    if workplace_type in ("hybrid", "onsite"):
        is_remote = False
        location_raw = f"{location_raw} ({workplace_type.capitalize()})" if location_raw else workplace_type.capitalize()
    elif workplace_type == "remote":
        is_remote = True
    else:
        is_remote = ("remote" in location_raw.lower()) or ("remote" in title.lower())
    remote_restriction = location_raw.strip() if location_raw.strip() else "unspecified"

    apply_url = payload.get("hostedUrl") or payload.get("applyUrl") or ""
    external_id = str(payload.get("id", "")).strip()

    return NormalizedJob(
        source=source,
        external_id=external_id,
        title=title,
        company_name=company_name,
        location_raw=location_raw or "Remote",
        is_remote=is_remote,
        remote_restriction=remote_restriction,
        job_type="full-time",
        description_text=desc_clean,
        description_html=content_html,
        apply_url=apply_url,
        tags=[],
    )


def transform_ats_ashby(payload: Dict[str, Any], source: str) -> "NormalizedJob":
    """Transform Ashby job board API item into NormalizedJob."""
    meta = payload.get("_ats_meta", {})
    company_name = meta.get("company_name") or "Unknown Company"

    title = payload.get("title", "Untitled Position")
    workplace_type = str(payload.get("workplaceType", "")).lower()

    loc_parts = []
    loc_name = payload.get("location")
    if loc_name:
        loc_parts.append(str(loc_name).strip())
    addr = payload.get("address") or {}
    post = addr.get("postalAddress") or {}
    country = post.get("addressCountry")
    region = post.get("addressRegion")
    if region and region not in loc_parts:
        loc_parts.append(str(region).strip())
    if country and country not in loc_parts:
        loc_parts.append(str(country).strip())

    if workplace_type in ("hybrid", "onsite"):
        is_remote = False
        loc_parts.append(f"({workplace_type.capitalize()})")
    elif workplace_type == "remote":
        is_remote = True
    else:
        is_remote = bool(payload.get("isRemote", False)) and (
            "remote" in (loc_name or "").lower() or "remote" in title.lower()
        )

    location_raw = ", ".join(loc_parts) if loc_parts else (loc_name or "")
    content_html = payload.get("descriptionHtml", "")
    desc_clean = clean_description_text(content_html) if content_html else (
        payload.get("descriptionPlain", "") or title
    )
    remote_restriction = location_raw.strip() if location_raw.strip() else "unspecified"

    apply_url = payload.get("jobUrl") or payload.get("applyUrl") or ""
    external_id = str(payload.get("id", "")).strip()

    return NormalizedJob(
        source=source,
        external_id=external_id,
        title=title,
        company_name=company_name,
        location_raw=location_raw or "Remote",
        is_remote=is_remote,
        remote_restriction=remote_restriction,
        job_type="full-time",
        description_text=desc_clean,
        description_html=content_html,
        apply_url=apply_url,
        tags=[],
    )


def transform_ats(source: str, payload: Dict[str, Any]) -> "NormalizedJob":
    """Dispatch ATS payload to the correct platform transformer.

    Source name format: 'ats:{board_slug}'.
    Platform is determined from '_ats_meta.platform' embedded by ATSBoardExtractor.
    """
    meta = payload.get("_ats_meta", {})
    platform = meta.get("platform", "").lower()
    if platform == "greenhouse":
        return transform_ats_greenhouse(payload, source)
    elif platform == "lever":
        return transform_ats_lever(payload, source)
    elif platform == "ashby":
        return transform_ats_ashby(payload, source)
    else:
        raise ValueError(
            f"[{source}] Unknown ATS platform in _ats_meta: '{platform}'. "
            "Expected 'greenhouse', 'lever', or 'ashby'."
        )


def transform_manual_nepal(payload: Dict[str, Any], source: str = "manual:nepal") -> NormalizedJob:
    """Transform manually imported job listing into NormalizedJob."""
    title = str(payload.get("title") or "").strip()
    company = str(payload.get("company_name") or payload.get("company") or "Unknown").strip()
    location = str(payload.get("location_raw") or payload.get("location") or "Kathmandu, Nepal").strip()
    is_remote = bool(payload.get("is_remote", False))
    desc_text = str(payload.get("description_text") or payload.get("description") or "").strip()
    apply_url = str(payload.get("apply_url") or payload.get("company_url") or "https://manual-import.local").strip()
    ext_id = str(payload.get("external_id") or "").strip()
    if not ext_id:
        ext_id = f"manual_{abs(hash(f'{title}_{company}_{location}'))}"

    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    return NormalizedJob(
        source=source,
        external_id=ext_id,
        title=title,
        company_name=company,
        company_url=str(payload.get("company_url") or "").strip() or None,
        location_raw=location,
        is_remote=is_remote,
        remote_restriction=str(payload.get("remote_restriction") or "nepal").strip() if not is_remote else str(payload.get("remote_restriction") or "unspecified").strip(),
        job_type=str(payload.get("job_type") or "full_time").strip(),
        description_text=desc_text,
        apply_url=apply_url,
        tags=tags,
    )


def transform_raw_listing(source: str, payload: Dict[str, Any]) -> Optional[NormalizedJob]:
    """Dispatcher transforming raw item payload based on source name."""
    source_lower = source.lower().strip()
    if source_lower == "arbeitnow":
        job = transform_arbeitnow(payload)
    elif source_lower == "remotive":
        job = transform_remotive(payload)
    elif source_lower == "himalayas":
        job = transform_himalayas(payload)
    elif source_lower == "weworkremotely":
        job = transform_weworkremotely(payload)
    elif source_lower == "remoteok":
        job = transform_remoteok(payload)
    elif source_lower == "jobicy":
        job = transform_jobicy(payload)
    elif source_lower == "hackernews":
        job = transform_hackernews(payload)
    elif source_lower.startswith("ats:"):
        job = transform_ats(source, payload)
    elif source_lower.startswith("manual:"):
        job = transform_manual_nepal(payload, source=source_lower)
    else:
        raise ValueError(f"No transformer registered for source: '{source}'")

    if job is None:
        return None

    # Task 9.8: If apply_url is not already an ATS link, check if description contains a direct ATS link
    if job.apply_url and not any(p.match(job.apply_url) for p in _ATS_LINK_PATTERNS):
        ats_link = extract_direct_ats_link(job.description_html) or extract_direct_ats_link(job.description_text)
        if ats_link:
            job.apply_url = ats_link

    # Extract explicit country restrictions (e.g. US citizen only, must reside in)
    country_lock = extract_country_restriction(job.description_text, job.location_raw)
    if country_lock and (not job.remote_restriction or job.remote_restriction == "unspecified"):
        job.remote_restriction = f"locked: {country_lock}"

    return job





