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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

DEFAULT_QUERIES = {
    "FY 2024 DoD Budget": "DoD budget FY 2024 spending filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)",
    "FY 2025 DoD Budget": "DoD budget FY 2025 spending filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)",
    "FY 2024/2025 DoD Vendor Spending": "DoD vendor spending FY 2024 OR FY 2025 filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)"
}

class PDFSearcher:
    def __init__(self, session):
        self.session = session
        self.timeout = 10

    def find_pdf_links(self, query, verbose=False):
        pdf_links = set()
        if verbose:
            logging.info(f"Searching: {query}")
        try:
            search_results = list(search(query, num_results=15))
        except Exception as e:
            logging.error(f"Search failed: {str(e)}")
            return pdf_links

        for url in search_results:
            if url.endswith(".pdf"):
                try:
                    response = self.session.head(url, timeout=self.timeout, allow_redirects=True)
                    if response.status_code == 200:
                        pdf_links.add(url)
                        if verbose:
                            logging.debug(f"Found: {url}")
                except requests.RequestException:
                    continue
            else:
                try:
                    response = self.session.get(url, timeout=self.timeout)
                    soup = BeautifulSoup(response.text, "html.parser")
                    for link in soup.find_all("a", href=True):
                        pdf_url = urljoin(url, link["href"])
                        if pdf_url.endswith(".pdf"):
                            try:
                                pdf_response = self.session.head(pdf_url, timeout=self.timeout, allow_redirects=True)
                                if pdf_response.status_code == 200:
                                    pdf_links.add(pdf_url)
                                    if verbose:
                                        logging.debug(f"Found: {pdf_url}")
                            except requests.RequestException:
                                continue
                except requests.RequestException as e:
                    if verbose:
                        logging.error(f"Error processing {url}: {str(e)}")
                    continue
            time.sleep(1)
        return pdf_links

class FileHandler:
    @staticmethod
    def save_results(filename, all_pdf_links):
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"Search performed on: {time.ctime()}\n\n")
            for title, links in all_pdf_links.items():
                f.write(f"{title}:\n")
                for link in sorted(links):
                    f.write(f"{link}\n")
                f.write("\n")
        logging.info(f"Search complete! Results saved to {filename}")

def setup_session():
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
    session.mount("https://", adapter)
    return session

def main():
    parser = argparse.ArgumentParser(description="Search for DoD spending PDFs")
    parser.add_argument("-o", "--output", default=None, help="Output file (default: dod_spending_pdfs_TIMESTAMP.txt)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed search progress")
    parser.add_argument("-q", "--queries", nargs="*", help="Custom queries (title:query pairs), e.g., 'Title:search terms'")
    args = parser.parse_args()

    logging.getLogger().setLevel(logging.DEBUG if args.verbose else logging.INFO)
    session = setup_session()
    searcher = PDFSearcher(session)
    all_pdf_links = {}

    queries = {}
    if args.queries:
        for q in args.queries:
            try:
                title, query = q.split(":", 1)
                queries[title.strip()] = query.strip()
            except ValueError:
                logging.error(f"Invalid query format: {q}. Use 'Title:query'")
                sys.exit(1)
    else:
        queries = DEFAULT_QUERIES

    for title, query in queries.items():
        logging.info(f"{title}")
        pdf_links = searcher.find_pdf_links(query, args.verbose)
        all_pdf_links[title] = pdf_links
        if pdf_links:
            for index, pdf in enumerate(sorted(pdf_links), 1):
                logging.info(f"[{index}] {pdf}")
        else:
            logging.info("No PDFs found")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = args.output if args.output else f"dod_spending_pdfs_{timestamp}.txt"
    FileHandler.save_results(filename, all_pdf_links)

if __name__ == "__main__":
    main()
