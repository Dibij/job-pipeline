"""Extractors package."""
from src.extractors.base import BaseExtractor
from src.extractors.arbeitnow import ArbeitnowExtractor
from src.extractors.remotive import RemotiveExtractor
from src.extractors.himalayas import HimalayasExtractor
from src.extractors.weworkremotely import WWRExtractor
from src.extractors.remoteok import RemoteOKExtractor
from src.extractors.jobicy import JobicyExtractor

__all__ = [
    "BaseExtractor", "ArbeitnowExtractor", "RemotiveExtractor",
    "HimalayasExtractor", "WWRExtractor", "RemoteOKExtractor", "JobicyExtractor",
]

