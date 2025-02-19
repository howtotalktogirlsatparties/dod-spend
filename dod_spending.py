import requests
from googlesearch import search
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import time
import argparse
import sys
import logging
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Dict, Set, Optional
import json
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger()

DEFAULT_QUERIES = {
    "FY 2024 DoD Budget": "DoD budget FY 2024 spending filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)",
    "FY 2025 DoD Budget": "DoD budget FY 2025 spending filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)",
    "FY 2024/2025 DoD Vendor Spending": "DoD vendor spending FY 2024 OR FY 2025 filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)"
}

class PDFSearcher:
    """A class to search for and collect PDF links from web queries."""
    
    def __init__(self, session: requests.Session, timeout: int = 10, max_workers: int = 5):
        self.session = session
        self.timeout = timeout
        self.max_workers = max_workers

    @lru_cache(maxsize=100)
    def _check_url(self, url: str) -> bool:
        """Check if a URL is a valid PDF link."""
        try:
            response = self.session.head(url, timeout=self.timeout, allow_redirects=True)
            return response.status_code == 200 and url.endswith(".pdf")
        except requests.RequestException:
            return False

    def _extract_pdf_links_from_page(self, url: str, verbose: bool = False) -> Set[str]:
        """Extract PDF links from a given webpage."""
        pdf_links = set()
        if url.endswith(".pdf"):
            if self._check_url(url):
                pdf_links.add(url)
                if verbose:
                    logger.debug(f"Direct PDF found: {url}")
            return pdf_links

        try:
            response = self.session.get(url, timeout=self.timeout)
            soup = BeautifulSoup(response.text, "html.parser")
            for link in soup.find_all("a", href=True):
                pdf_url = urljoin(url, link["href"])
                if pdf_url.endswith(".pdf") and self._check_url(pdf_url):
                    pdf_links.add(pdf_url)
                    if verbose:
                        logger.debug(f"Found PDF: {pdf_url}")
        except requests.RequestException as e:
            if verbose:
                logger.error(f"Error processing {url}: {str(e)}")
        return pdf_links

    def find_pdf_links(self, query: str, verbose: bool = False) -> Set[str]:
        """Search for PDF links based on a query."""
        pdf_links = set()
        logger.info(f"Searching: {query}")
        try:
            search_results = list(search(query, num_results=15))
        except Exception as e:
            logger.error(f"Search failed: {str(e)}")
            return pdf_links

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_url = {executor.submit(self._extract_pdf_links_from_page, url, verbose): url for url in search_results}
            for future in future_to_url:
                pdf_links.update(future.result())
                time.sleep(0.5) 
        return pdf_links

class FileHandler:
    """Handles saving search results to a file."""
    
    @staticmethod
    def save_results(filename: str, all_pdf_links: Dict[str, Set[str]], output_format: str = "txt") -> None:
        """Save the collected PDF links to a file in the specified format."""
        output_path = Path(filename)
        if output_format == "json":
            with output_path.open("w", encoding="utf-8") as f:
                json.dump({title: list(links) for title, links in all_pdf_links.items()}, f, indent=2)
        else:  # Default to txt
            with output_path.open("w", encoding="utf-8") as f:
                f.write(f"Search performed on: {time.ctime()}\n\n")
                for title, links in all_pdf_links.items():
                    f.write(f"{title}:\n")
                    for link in sorted(links):
                        f.write(f"  - {link}\n")
                    f.write("\n")
        logger.info(f"Results saved to {filename} (format: {output_format})")

def setup_session() -> requests.Session:
    """Set up a requests session with retries and a custom user agent."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount...
