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
from dataclasses import dataclass
from typing import Dict, Set, Optional, List
from concurrent.futures import ThreadPoolExecutor
import threading
import csv
from pathlib import Path
from io import BytesIO
try:
    from pypdf import PdfReader
    PDF_METADATA_AVAILABLE = True
except ImportError:
    PDF_METADATA_AVAILABLE = False

DEFAULT_QUERIES = {
    "FY 2024 DoD Budget": "DoD budget FY 2024 spending cur filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)",
    "FY 2025 DoD Budget": "DoD budget FY 2025 spending cur filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)",
    "FY 2024/2025 DoD Vendor Spending": "DoD vendor spending FY 2024 OR FY 2025 cur filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)"
}

@dataclass
class Config:
    timeout: int = 10  
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    max_retries: int = 3
    backoff_factor: float = 1.5
    retry_status_codes: tuple = (429, 500, 502, 503, 504)
    search_results_limit: int = 15
    max_workers: int = 8
    rate_limit_calls: int = 1  
    rate_limit_period: float = 2.0 
    connection_pool_maxsize: int = 20  
    validate_pdf_content: bool = True  
    cache_file: str = ".pdf_cache.txt"  
    extract_metadata: bool = False  


class RateLimiter:
    """Simple rate limiter to prevent getting blocked by search engines."""
    
    def __init__(self, calls: int, period: float):
        self.calls = calls
        self.period = period
        self.timestamps = []
        self.lock = threading.Lock()
        
    def __enter__(self):
        with self.lock:
            now = time.time()

            self.timestamps = [t for t in self.timestamps if now - t < self.period]
            
            if len(self.timestamps) >= self.calls:
                sleep_time = self.period - (now - self.timestamps[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
            
            self.timestamps.append(time.time())
            
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class SessionManager:
    def __init__(self, config: Config):
        self.config = config
        self.session = self._create_session()
        self.rate_limiter = RateLimiter(
            calls=config.rate_limit_calls, 
            period=config.rate_limit_period
        )
    
    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({"User-Agent": self.config.user_agent})
        
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            status_forcelist=self.config.retry_status_codes,
            allowed_methods=["HEAD", "GET"]
        )
        
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=self.config.connection_pool_maxsize,
            pool_maxsize=self.config.connection_pool_maxsize
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def get(self, url: str, **kwargs) -> requests.Response:
        with self.rate_limiter:
            return self.session.get(url, timeout=self.config.timeout, **kwargs)
    
    def head(self, url: str, **kwargs) -> requests.Response:
        with self.rate_limiter:
            return self.session.head(url, timeout=self.config.timeout, **kwargs)


class PDFCache:
    """Cache for storing processed URLs to avoid redundant downloads."""
    
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self.memory_cache = set()
        self.lock = threading.Lock()
        self._load_cache()
    
    def _load_cache(self) -> None:
        """Load cache from disk if available."""
        try:
            with open(self.cache_file, 'r') as f:
                self.memory_cache = set(line.strip() for line in f)
        except (FileNotFoundError, IOError):
            self.memory_cache = set()
    
    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            with open(self.cache_file, 'w') as f:
                for url in self.memory_cache:
                    f.write(f"{url}\n")
        except IOError as e:
            logging.warning(f"Failed to save cache: {e}")
    
    def contains(self, url: str) -> bool:
        """Check if URL is in cache."""
        with self.lock:
            return url in self.memory_cache
    
    def add(self, url: str) -> None:
        """Add URL to cache and save to disk."""
        with self.lock:
            self.memory_cache.add(url)
            self._save_cache()


class PDFMetadataExtractor:
    """Extract metadata from PDFs."""
    
    @staticmethod
    def extract(pdf_content: bytes) -> Dict:
        """Extract basic metadata from PDF content."""
        if not PDF_METADATA_AVAILABLE:
            return {}
            
        try:
            with BytesIO(pdf_content) as f:
                reader = PdfReader(f)
                info = reader.metadata
                if info:
                    return {
                        "title": info.get("/Title", ""),
                        "author": info.get("/Author", ""),
                        "creation_date": info.get("/CreationDate", ""),
                        "pages": len(reader.pages)
                    }
        except Exception as e:
            logging.debug(f"Failed to extract PDF metadata: {e}")
        
        return {}


class PDFSearcher:
    def __init__(self, session_manager: SessionManager, config: Config):
        self.session_manager = session_manager
        self.config = config
        self.cache = PDFCache(config.cache_file)
        self.metadata_extractor = PDFMetadataExtractor()
    
    def find_pdf_links(self, query: str, verbose: bool = False) -> List[Dict]:
        """Find PDF links for a given query with metadata."""
        pdf_results = []
        
        if verbose:
            logging.info(f"Searching: {query}")
            
        try:

            search_results = list(search(query, num_results=self.config.search_results_limit))
            
            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                future_to_url = {
                    executor.submit(self._process_url, url, verbose): url 
                    for url in search_results
                }
                
                for future in future_to_url:
                    try:
                        result = future.result()
                        if result:
                            pdf_results.extend(result)
                    except Exception as e:
                        if verbose:
                            logging.debug(f"Error processing URL: {e}")
                            
        except Exception as e:
            logging.error(f"Search failed for '{query}': {e}")
            
        return pdf_results
    
    def _process_url(self, url: str, verbose: bool) -> List[Dict]:
        """Process a URL to find PDF links."""
        results = []
        
        if self.cache.contains(url):
            return results
            
        try:
            if url.lower().endswith(".pdf"):
                pdf_info = self._check_direct_pdf(url, verbose)
                if pdf_info:
                    results.append(pdf_info)
            else:
                pdf_links = self._scrape_page_for_pdfs(url, verbose)
                results.extend(pdf_links)
                
            self.cache.add(url)
            
        except Exception as e:
            if verbose:
                logging.debug(f"Error processing {url}: {e}")
                
        return results
    
    def _check_direct_pdf(self, url: str, verbose: bool) -> Optional[Dict]:
        """Check if URL is a valid PDF and extract metadata if needed."""
        try:

            head_response = self.session_manager.head(url, allow_redirects=True)
            
            if head_response.status_code != 200 or "application/pdf" not in head_response.headers.get("Content-Type", ""):
                return None
                
            if self.config.validate_pdf_content:
                response = self.session_manager.get(url, stream=True)
                header = response.raw.read(5)
                if header != b"%PDF-":
                    return None
                    
            result = {"url": url, "source": "direct", "metadata": {}}
            
            if self.config.extract_metadata and PDF_METADATA_AVAILABLE:
                try:
                    response = self.session_manager.get(url)
                    metadata = self.metadata_extractor.extract(response.content)
                    result["metadata"] = metadata
                except Exception as e:
                    if verbose:
                        logging.debug(f"Failed to extract metadata from {url}: {e}")
                        
            if verbose:
                logging.debug(f"Found PDF: {url}")
                
            return result
            
        except requests.RequestException:
            return None
    
    def _scrape_page_for_pdfs(self, url: str, verbose: bool) -> List[Dict]:
        """Scrape a web page for PDF links."""
        results = []
        
        try:
            response = self.session_manager.get(url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            pdf_urls = set()
            for link in soup.find_all("a", href=True):
                href = link["href"].lower()
                if href.endswith(".pdf"):
                    pdf_url = urljoin(url, link["href"])
                    pdf_urls.add(pdf_url)
            
            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                future_to_url = {
                    executor.submit(self._check_direct_pdf, pdf_url, verbose): pdf_url 
                    for pdf_url in pdf_urls
                }
                
                for future in future_to_url:
                    result = future.result()
                    if result:
                        result["referring_page"] = url
                        results.append(result)
                        
        except requests.RequestException:
            pass
            
        return results


class FileHandler:
    @staticmethod
    def save_results(filename: str, search_results: Dict[str, List[Dict]]) -> None:
        """Save search results to CSV file."""
        try:
            with Path(filename).open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                
                writer.writerow(["Search Performed On", time.ctime()])
                writer.writerow([])
                
                headers = ["Query", "PDF Link"]
                if PDF_METADATA_AVAILABLE and any(
                    any(result["metadata"] for result in results)
                    for results in search_results.values()
                ):
                    headers.extend(["Title", "Author", "Pages"])
                
                writer.writerow(headers)
                
                total_pdfs = 0
                for title, results in search_results.items():
                    for result in sorted(results, key=lambda x: x["url"]):
                        row = [title, result["url"]]
                        
                        if "metadata" in result and len(headers) > 2:
                            metadata = result["metadata"]
                            row.extend([
                                metadata.get("title", ""),
                                metadata.get("author", ""),
                                metadata.get("pages", "")
                            ])
                            
                        writer.writerow(row)
                        
                    total_pdfs += len(results)
                    writer.writerow([])
                    
                writer.writerow(["Total PDFs Found", total_pdfs])
                
            logging.info(f"Results saved to {filename}")
            
        except IOError as e:
            logging.error(f"Failed to save results to {filename}: {e}")


class SearchApplication:
    def __init__(self):
        self.config = Config()
        self.session_manager = SessionManager(self.config)
        self.searcher = PDFSearcher(self.session_manager, self.config)

    def run(self) -> None:
        args = self._parse_args()
        self._setup_logging(args.verbose)
        
        if args.metadata and PDF_METADATA_AVAILABLE:
            self.config.extract_metadata = True
        
        search_results = self._perform_searches(args)
        self._save_results(args.output, search_results)

    def _parse_args(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="Search for DoD spending PDFs")
        parser.add_argument("-o", "--output", type=str, default=None, 
                           help="Output CSV file path")
        parser.add_argument("-v", "--verbose", action="store_true",
                           help="Enable verbose logging")
        parser.add_argument("-q", "--queries", nargs="*", type=str,
                           help="Custom queries in format 'Title:query'")
        parser.add_argument("-m", "--metadata", action="store_true",
                           help="Extract PDF metadata (requires pypdf)")
        parser.add_argument("-w", "--workers", type=int,
                           help="Number of worker threads")
        parser.add_argument("--no-cache", action="store_true",
                           help="Disable URL caching")
        return parser.parse_args()

    def _setup_logging(self, verbose: bool) -> None:
        logging.basicConfig(
            level=logging.DEBUG if verbose else logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)],
            force=True
        )

    def _get_queries(self, args: argparse.Namespace) -> Dict[str, str]:
        if not args.queries:
            return DEFAULT_QUERIES
            
        queries = {}
        for q in args.queries:
            try:
                title, query = q.split(":", 1)
                queries[title.strip()] = query.strip()
            except ValueError:
                logging.error(f"Invalid query format: {q}. Expected 'Title:query'")
                sys.exit(1)
                
        return queries

    def _perform_searches(self, args: argparse.Namespace) -> Dict[str, List[Dict]]:
        queries = self._get_queries(args)
        search_results = {}
        
        if args.workers:
            self.config.max_workers = args.workers
            
        if args.no_cache:
            self.config.cache_file = None
        
        with ThreadPoolExecutor(max_workers=min(len(queries), self.config.max_workers)) as executor:
            future_to_title = {
                executor.submit(self.searcher.find_pdf_links, query, args.verbose): title 
                for title, query in queries.items()
            }
            
            for future in future_to_title:
                title = future_to_title[future]
                logging.info(f"{title}")
                
                try:
                    pdf_results = future.result()
                    search_results[title] = pdf_results
                    
                    for index, pdf in enumerate(sorted(pdf_results, key=lambda x: x["url"]), 1):
                        url = pdf["url"]
                        metadata_info = ""
                        
                        if "metadata" in pdf and pdf["metadata"]:
                            meta = pdf["metadata"]
                            if "title" in meta and meta["title"]:
                                metadata_info = f" - {meta['title']}"
                                
                        logging.info(f"[{index}] {url}{metadata_info}")
                        
                    if not pdf_results:
                        logging.info("No PDFs found")
                        
                except Exception as e:
                    logging.error(f"Failed to process {title}: {e}")
                    
        return search_results

    def _save_results(self, output: Optional[str], search_results: Dict[str, List[Dict]]) -> None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = output if output else f"dod_spending_pdfs_{timestamp}.csv"
        FileHandler.save_results(filename, search_results)


if __name__ == "__main__":
    SearchApplication().run()
