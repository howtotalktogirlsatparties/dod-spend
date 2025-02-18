import requests
from googlesearch import search
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from colorama import Fore, Style, init

init(autoreset=True)

queries = {
    "🔵 FY 2024 DoD Budget PDFs": "DoD budget FY 2024 spending filetype:pdf",
    "🟢 FY 2025 DoD Budget PDFs": "DoD budget FY 2025 spending filetype:pdf"
}

def find_pdf_links(query):
    pdf_links = set()
    for url in search(query, num_results=10):
        if url.endswith(".pdf"):
            pdf_links.add(url)
        else:
            try:
                page = requests.get(url)
                soup = BeautifulSoup(page.text, "html.parser")
                for link in soup.find_all("a", href=True):
                    pdf_url = urljoin(url, link["href"])
                    if pdf_url.endswith(".pdf"):
                        pdf_links.add(pdf_url)
            except requests.exceptions.RequestException:
                continue
    return pdf_links

all_pdf_links = {}
for title, query in queries.items():
    print(f"\n{Fore.CYAN + Style.BRIGHT}{title}{Style.RESET_ALL}\n")
    pdf_links = find_pdf_links(query)
    all_pdf_links[title] = pdf_links
    for index, pdf in enumerate(pdf_links, 1):
        print(f"{Fore.YELLOW}[{index}] {Fore.GREEN}{pdf}{Style.RESET_ALL}")

with open("dod_spending_pdfs.txt", "w") as f:
    for title, links in all_pdf_links.items():
        f.write(f"\n{title}:\n")
        for link in links:
            f.write(link + "\n")

print(f"\n{Fore.MAGENTA}✅ Search complete! PDF links saved in 'dod_spending_pdfs.txt'{Style.RESET_ALL}")
