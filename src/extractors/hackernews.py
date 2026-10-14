"""Hacker News 'Who is hiring?' official Firebase API extractor."""
import logging
from typing import Any, Dict, List, Optional
import requests

from src import config
from src.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class HackerNewsExtractor(BaseExtractor):
    """Extractor for Hacker News 'Who is hiring?' threads via official Firebase API.

    API Guidelines:
    - Official public Firebase REST API: https://github.com/HackerNews/API
    - Finds the latest 'Ask HN: Who is hiring?' thread posted by user 'whoishiring'.
    - Fetches top-level comments (kids) where companies post job listings.
    - Rate limit: Firebase API has no strict rate limit, but polite delay is enforced.
    """

    USER_URL = "https://hacker-news.firebaseio.com/v0/user/whoishiring.json"
    ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"

    def __init__(self, delay_seconds: float = 0.1):
        super().__init__(source_name="hackernews", delay_seconds=delay_seconds)

    def extract_external_id(self, item: Dict[str, Any]) -> str:
        """Extract unique external ID from HN item ID."""
        item_id = item.get("id")
        if item_id is not None:
            return str(item_id).strip()
        return ""

    def find_latest_hiring_story(self) -> Optional[Dict[str, Any]]:
        """Find the most recent 'Ask HN: Who is hiring?' story by user 'whoishiring'."""
        logger.info("[%s] Fetching submitted stories by user 'whoishiring'...", self.source_name)
        try:
            resp = self.session.get(self.USER_URL, timeout=config.REQUEST_TIMEOUT_SECONDS)
            resp.raise_for_status()
            user_data = resp.json()
        except Exception as exc:
            logger.error("[%s] Failed to fetch user 'whoishiring': %s", self.source_name, exc)
            return None

        submitted = (user_data or {}).get("submitted", [])
        # Check the first 10 submissions (whoishiring posts monthly threads)
        for sid in submitted[:10]:
            try:
                s_resp = self.session.get(
                    self.ITEM_URL.format(item_id=sid),
                    timeout=config.REQUEST_TIMEOUT_SECONDS,
                )
                s_resp.raise_for_status()
                story = s_resp.json()
                if story and "Ask HN: Who is hiring?" in story.get("title", ""):
                    logger.info(
                        "[%s] Found hiring story #%d: '%s' (%d comments)",
                        self.source_name,
                        sid,
                        story.get("title"),
                        len(story.get("kids", [])),
                    )
                    return story
            except Exception as exc:
                logger.warning("[%s] Failed to inspect item %s: %s", self.source_name, sid, exc)
            self.polite_sleep()

        logger.warning("[%s] No active 'Ask HN: Who is hiring?' story found.", self.source_name)
        return None

    def fetch_raw(self, limit: int = 50, max_pages: int = 1) -> List[Dict[str, Any]]:
        """Fetch top-level job comments from the latest 'Ask HN: Who is hiring?' story.

        Args:
            limit: Number of job comments to retrieve (default 50).
            max_pages: Ignored for HN comments, kept for BaseExtractor interface.
        """
        story = self.find_latest_hiring_story()
        if not story:
            return []

        kids = story.get("kids", [])
        if not kids:
            logger.info("[%s] Story #%s has no comments.", self.source_name, story.get("id"))
            return []

        target_kids = kids[:limit]
        collected: List[Dict[str, Any]] = []

        for kid in target_kids:
            try:
                resp = self.session.get(
                    self.ITEM_URL.format(item_id=kid),
                    timeout=config.REQUEST_TIMEOUT_SECONDS,
                )
                resp.raise_for_status()
                item = resp.json()
            except requests.exceptions.RequestException as exc:
                logger.warning("[%s] Error fetching comment %s: %s", self.source_name, kid, exc)
                continue
            except ValueError as exc:
                logger.warning("[%s] JSON parse error for comment %s: %s", self.source_name, kid, exc)
                continue

            if not item:
                continue

            # Skip deleted or dead comments, or comments without text
            if item.get("deleted") or item.get("dead") or not item.get("text"):
                continue

            # Store story reference in raw item
            item["story_id"] = story.get("id")
            item["story_title"] = story.get("title")
            collected.append(item)

            self.polite_sleep()

        logger.info("[%s] Retrieved %d active job comments.", self.source_name, len(collected))
        return collected
