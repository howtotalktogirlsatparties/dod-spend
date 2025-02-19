import requests
from googlesearch import search
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from colorama import Fore, Style, init
import time
import argparse
import sys

init(autoreset=True)

DEFAULT_QUERIES = {
    "FY 2024 DoD Budget": "DoD budget FY 2024 spending filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)",
    "FY 2025 DoD Budget": "DoD budget FY 2025 spending filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)",
    "FY 2024/2025 DoD Vendor Spending": "DoD vendor spending FY 2024 OR FY 2025 filetype:pdf site:*.edu | site:*.org | site:*.gov -inurl:(signup | login)"
}

def setup_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    return session

def find_pdf_links(query, session, verbose=False):
    pdf_links = set()
    timeout = 10
    
    if verbose:
        print(f"{Fore.CYAN}Searching: {query}{Style.RESET_ALL}")
    
    try:
        search_results = list(search(query, num_results=15))
    except Exception as e:
        print(f"{Fore.RED}Search failed: {str(e)}{Style.RESET_ALL}", file=sys.stderr)
        return pdf_links

    for url in search_results:
        if url.endswith(".pdf"):
            try:
                response = session.head(url, timeout=timeout, allow_redirects=True)
                if response.status_code == 200:
                    pdf_links.add(url)
                    if verbose:
                        print(f"{Fore.GREEN}Found: {url}{Style.RESET_ALL}")
            except requests.RequestException:
                continue
        else:
            try:
                response = session.get(url, timeout=timeout)
                soup = BeautifulSoup(response.text, "html.parser")
                
                for link in soup.find_all("a", href=True):
                    pdf_url = urljoin(url, link["href"])
                    if pdf_url.endswith(".pdf"):
                        try:
                            pdf_response = session.head(pdf_url, timeout=timeout, allow_redirects=True)
                            if pdf_response.status_code == 200:
                                pdf_links.add(pdf_url)
                                if verbose:
                                    print(f"{Fore.GREEN}Found: {pdf_url}{Style.RESET_ALL}")
                        except requests.RequestException:
                            continue
            except requests.RequestException as e:
                if verbose:
                    print(f"{Fore.RED}Error processing {url}: {str(e)}{Style.RESET_ALL}", file=sys.stderr)
                continue
                
        time.sleep(1)
        
    return pdf_links

def main():
    parser = argparse.ArgumentParser(description="Search for DoD spending PDFs")
    parser.add_argument("-o", "--output", default=None, help="Output file (default: dod_spending_pdfs_TIMESTAMP.txt)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed search progress")
    parser.add_argument("-q", "--queries", nargs="*", help="Custom queries (title:query pairs), e.g., 'Title:search terms'")
    args = parser.parse_args()

    session = setup_session()
    all_pdf_links = {}
    
    queries = {}
    if args.queries:
        for q in args.queries:
            try:
                title, query = q.split(":", 1)
                queries[title.strip()] = query.strip()
            except ValueError:
                print(f"{Fore.RED}Invalid query format: {q}. Use 'Title:query'{Style.RESET_ALL}", file=sys.stderr)
                sys.exit(1)
    else:
        queries = DEFAULT_QUERIES

    for title, query in queries.items():
        print(f"\n{Fore.CYAN}{title}{Style.RESET_ALL}")
        pdf_links = find_pdf_links(query, session, args.verbose)
        all_pdf_links[title] = pdf_links
        
        if pdf_links:
            for index, pdf in enumerate(sorted(pdf_links), 1):
                print(f"{Fore.YELLOW}[{index}] {pdf}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}No PDFs found{Style.RESET_ALL}")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = args.output if args.output else f"dod_spending_pdfs_{timestamp}.txt"
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"Search performed on: {time.ctime()}\n\n")
        for title, links in all_pdf_links.items():
            f.write(f"{title}:\n")
            for link in sorted(links):
                f.write(f"{link}\n")
            f.write("\n")
    
    print(f"\n{Fore.MAGENTA}Search complete! Results saved to {filename}{Style.RESET_ALL}")

if __name__ == "__main__":
    main()
