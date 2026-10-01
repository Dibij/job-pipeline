"""JD Section Extraction module.

Splits a raw job description string into labeled sections:
  - title
  - company
  - location
  - responsibilities
  - requirements
  - nice_to_have
  - benefits
  - company_blurb
  - legal_eeo
  - other

Strategy (in order):
1. Strip residual HTML tags.
2. Detect explicit headings (ALL CAPS, Title Case, or markdown ## style).
3. If headings found, assign text blocks to sections by keyword-matching the heading.
4. If no headings, fall back to keyword-scanning sentences/bullets into sections.
5. Classify unmatched text as 'other'.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

SECTION_KEYS = [
    "title",
    "company",
    "location",
    "responsibilities",
    "requirements",
    "nice_to_have",
    "benefits",
    "company_blurb",
    "legal_eeo",
    "other",
]


@dataclass
class JDSections:
    title: str = ""
    company: str = ""
    location: str = ""
    responsibilities: str = ""
    requirements: str = ""
    nice_to_have: str = ""
    benefits: str = ""
    company_blurb: str = ""
    legal_eeo: str = ""
    other: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {k: getattr(self, k) for k in SECTION_KEYS}

    def non_empty(self) -> Dict[str, str]:
        return {k: v for k, v in self.as_dict().items() if v.strip()}


# ---------------------------------------------------------------------------
# Keyword maps for heading classification
# ---------------------------------------------------------------------------

_HEADING_SECTION_MAP: List[Tuple[str, re.Pattern]] = [
    ("responsibilities", re.compile(
        r"\b(responsibilities|what you.ll do|role overview|your role|"
        r"the role|key duties|duties|about the role|day.to.day|"
        r"what you will do|position overview)\b",
        re.IGNORECASE,
    )),
    ("requirements", re.compile(
        r"\b(requirements?|qualifications?|must.have|required skills?|"
        r"what we.re looking for|what you.ll need|you have|you bring|"
        r"minimum qualifications?|basic qualifications?|skills? required|"
        r"we need|you should have|what you need|experience required|"
        r"our ideal candidate|desired qualifications?)\b",
        re.IGNORECASE,
    )),
    ("nice_to_have", re.compile(
        r"\b(nice.to.have|bonus|preferred|plus if you|would be great|"
        r"bonus points?|it would be great|advantageous|desirable|"
        r"even better if|extra credit|ideal but not required|"
        r"we.d love|not required but)\b",
        re.IGNORECASE,
    )),
    ("benefits", re.compile(
        r"\b(benefits?|perks?|compensation|what we offer|why join us|"
        r"we offer|our offer|what.s in it for you|why work|"
        r"our package|total rewards?|salary|salary range|"
        r"working here|why us)\b",
        re.IGNORECASE,
    )),
    ("company_blurb", re.compile(
        r"\b(about us|about the company|who we are|our company|company overview|"
        r"our mission|the company|our story|what we do|about \w+)\b",
        re.IGNORECASE,
    )),
    ("legal_eeo", re.compile(
        r"\b(equal opportunity|eeo|diversity|inclusion|affirmative action|"
        r"disability|veteran|accommodation|legal notice|privacy policy|"
        r"gdpr|right to work|equal employment|non.discrimination)\b",
        re.IGNORECASE,
    )),
]

# Keywords to detect inside sentences for fallback mode
_SENTENCE_CLUES: List[Tuple[str, re.Pattern]] = [
    ("requirements", re.compile(
        r"\b(you (must|should|will) (have|possess|know|be)|"
        r"required|mandatory|must-have|we require|"
        r"\d\+\s*years? (of )?experience|minimum experience)\b",
        re.IGNORECASE,
    )),
    ("nice_to_have", re.compile(
        r"\b(bonus|preferred|nice to have|ideally|plus|advantageous|"
        r"not required|desirable|it would be|we.d love)\b",
        re.IGNORECASE,
    )),
    ("responsibilities", re.compile(
        r"\b(you will|you.ll|your job|your responsibilities|"
        r"responsible for|work on|collaborate with|you.re going to|"
        r"your tasks|day-to-day)\b",
        re.IGNORECASE,
    )),
    ("benefits", re.compile(
        r"\b(we offer|competitive salary|remote.first|flexible (hours?|schedule)|"
        r"health insurance|stock options|equity|401k|pto|paid time off|"
        r"work.from.home|unlimited pto|annual bonus|perks)\b",
        re.IGNORECASE,
    )),
    ("legal_eeo", re.compile(
        r"\b(equal opportunity|eeo|right to work|disability|gdpr|"
        r"privacy|non.discrimination|all qualified applicants?)\b",
        re.IGNORECASE,
    )),
    ("company_blurb", re.compile(
        r"\b(we are (a|an|the)|our (company|mission|vision|platform|product|"
        r"team|culture|values)|founded in|headquartered)\b",
        re.IGNORECASE,
    )),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HTML_TAG = re.compile(r"<[^>]+>", re.IGNORECASE)
_MULTIPLE_BLANK_LINES = re.compile(r"\n{3,}")
_BULLET_LINE = re.compile(r"^\s*[-•*▪▸‣◦→·]\s+", re.MULTILINE)


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities.
    
    Converts block-level list items to bullet lines before stripping so
    the content cannot later be misidentified as section headings.
    """
    # Convert <li> items to bullet lines first
    text = re.sub(r"<li[^>]*>", "\n• ", text, flags=re.IGNORECASE)
    # Convert block-level elements to newlines
    text = re.sub(r"<(?:br|hr|p|div|h[1-6]|ul|ol)[^>]*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(?:p|div|h[1-6]|ul|ol|li)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = _HTML_TAG.sub(" ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace(
        "&gt;", ">"
    ).replace("&nbsp;", " ").replace("&#8203;", "").replace("&quot;", '"')
    return re.sub(r"[ \t]{2,}", " ", text)


def _normalise_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTIPLE_BLANK_LINES.sub("\n\n", text)
    return text.strip()


_HEADING_PATTERN = re.compile(
    r"^(?:"
    # ALL CAPS line (≥3 chars, optional trailing colon)
    r"[A-Z][A-Z &/'-]{2,}:?"
    r"|"
    # Markdown headings ## or ###
    r"#{1,3}\s+.+"
    r")$",
    re.MULTILINE,
)

# Known single-word or short headings common in JDs
_KNOWN_HEADINGS = {
    "requirements", "qualifications", "responsibilities",
    "benefits", "perks", "compensation", "overview",
    "summary", "about", "experience", "skills",
    "location", "salary", "role",
}


def _is_heading_line(line: str) -> bool:
    """Return True if line looks like a section heading, not a sentence."""
    stripped = line.strip().rstrip(":")
    if not stripped or len(stripped) < 3:
        return False
    # Headings are short and don't end with a period
    if len(stripped) > 80 or stripped.rstrip(":").endswith("."):
        return False

    # 1. Matches ALL CAPS or markdown pattern
    if _HEADING_PATTERN.match(stripped):
        return True

    # 2. Known single-word heading (case-insensitive)
    if stripped.lower() in _KNOWN_HEADINGS:
        return True

    # 3. Short phrase (≤ 7 words) where first word is Title Case and line
    #    doesn't look like a sentence (no verb contraction mid-sentence etc.)
    #    Allows: "What You'll Do", "Nice to Have", "About the Company", etc.
    words = stripped.split()
    if 2 <= len(words) <= 7:
        # First word must start with a capital
        if words[0][0].isupper():
            # No mid-sentence punctuation (commas, semicolons, parentheses)
            if not re.search(r"[,;()]", stripped):
                # Exclude lines that look like bullet list items
                # (start with a verb or contain "and" style continuation)
                first_word = words[0].lower()
                if first_word not in {
                    "build", "maintain", "write", "design", "develop", "work",
                    "create", "implement", "ensure", "manage", "support",
                    "help", "drive", "collaborate", "adapt", "transform",
                    "localize", "uphold", "coordinate",
                }: 
                    return True

    return False


def _classify_heading(heading: str) -> str:
    """Map a heading string to a section key."""
    for section_key, pattern in _HEADING_SECTION_MAP:
        if pattern.search(heading):
            return section_key
    return "other"


def _classify_sentence(sentence: str) -> str:
    """Classify a sentence / bullet into a section key by its content."""
    for section_key, pattern in _SENTENCE_CLUES:
        if pattern.search(sentence):
            return section_key
    return "other"


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------


def extract_sections(
    description_text: str,
    title: str = "",
    company: str = "",
    location: str = "",
) -> JDSections:
    """Split a raw JD description into structured sections.

    Args:
        description_text: Raw JD string, may contain HTML.
        title: Job title (pre-populated from structured data).
        company: Company name (pre-populated from structured data).
        location: Location string (pre-populated from structured data).

    Returns:
        JDSections dataclass with populated string fields.
    """
    sections = JDSections(
        title=title.strip(),
        company=company.strip(),
        location=location.strip(),
    )

    if not description_text:
        return sections

    # 1. Clean HTML and normalise whitespace
    clean = _strip_html(description_text)
    clean = _normalise_whitespace(clean)

    # 2. Split into lines and try heading detection
    lines = clean.split("\n")

    # Collect (heading_or_None, text_block) pairs
    blocks: List[Tuple[Optional[str], List[str]]] = []
    current_heading: Optional[str] = None
    current_block: List[str] = []

    for line in lines:
        if _is_heading_line(line) and len(line.strip()) < 80:
            # Save previous block
            if current_block or current_heading is not None:
                blocks.append((current_heading, current_block))
            current_heading = line.strip().rstrip(":")
            current_block = []
        else:
            if line.strip():
                current_block.append(line)

    # Flush last block
    if current_block or current_heading is not None:
        blocks.append((current_heading, current_block))

    heading_blocks_found = any(h is not None for h, _ in blocks)

    if heading_blocks_found:
        # --- Mode A: heading-driven assignment ---
        for heading, block_lines in blocks:
            block_text = "\n".join(block_lines).strip()
            if not block_text:
                continue
            if heading is None:
                # Text before any heading → company blurb or other
                _append_to(sections, "company_blurb", block_text)
            else:
                key = _classify_heading(heading)
                _append_to(sections, key, f"**{heading}**\n{block_text}")
    else:
        # --- Mode B: fallback — no headings detected ---
        # Split into paragraphs / bullets and classify each
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", clean) if p.strip()]
        for para in paragraphs:
            key = _classify_sentence(para)
            _append_to(sections, key, para)

    return sections


def _append_to(sections: JDSections, key: str, text: str) -> None:
    """Append text to the appropriate field of a JDSections object."""
    current = getattr(sections, key, "") or ""
    if current:
        setattr(sections, key, current + "\n\n" + text)
    else:
        setattr(sections, key, text)
