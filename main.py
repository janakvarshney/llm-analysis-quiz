from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import httpx
import pdfplumber
import pandas as pd
import io
import re
import time

from playwright.sync_api import sync_playwright


SECRET = "janak-llm-quiz-2025-x19!a" 


class QuizPayload(BaseModel):
    email: str
    secret: str
    url: str


app = FastAPI()

def render_page_sync(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        html = page.content()
        browser.close()
        return html



# UTILITIES
def download_file(url: str) -> bytes:
    with httpx.Client(timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def extract_sum_from_pdf(pdf_bytes: bytes, page_index=1) -> float:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[page_index]
        table = page.extract_table()

        df = pd.DataFrame(table[1:], columns=table[0])
        value_col = None

        for col in df.columns:
            if col.strip().lower() == "value":
                value_col = col
                break

        if value_col is None:
            raise ValueError("No column named 'value' found")

        df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
        return float(df[value_col].sum())


def solve_one(email, secret, url):
    print(f"\n==============================")
    print(f"Solving Quiz: {url}")
    print("==============================")

    html = render_page_sync(url)

    # 1. Find submit URL
    submit_url_match = re.search(r"Post your answer to\s+(https?://\S+)", html)
    if not submit_url_match:
        print("Error: submit URL not found in page")
        return None
    submit_url = submit_url_match.group(1)

    # 2. Identify PDF
    pdf_url_match = re.search(
        r'href="(https?://[^"]+\.pdf)"', html, flags=re.IGNORECASE
    )

    answer = None

    if pdf_url_match:
        pdf_url = pdf_url_match.group(1)
        print(f"Downloading PDF: {pdf_url}")

        pdf_bytes = download_file(pdf_url)
        answer = extract_sum_from_pdf(pdf_bytes, page_index=1)

        print(f"Computed Answer = {answer}")

    else:
        print("No PDF handler matched yet")
        return None

    payload = {"email": email, "secret": secret, "url": url, "answer": answer}

    print("Submitting answer...")

    with httpx.Client(timeout=60) as client:
        resp = client.post(submit_url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    print("Response:", data)

    return data.get("url") 

def solve_quiz_chain(email, secret, start_url, limit_seconds=180):
    t0 = time.time()
    url = start_url

    while url and time.time() - t0 < limit_seconds:
        url = solve_one(email, secret, url)

    print("\nQuiz processing finished.\n")


@app.post("/quiz")
def quiz_endpoint(request: QuizPayload):

    if request.secret != SECRET:
        raise HTTPException(status_code=403, detail="Secret Key Invalid")

    solve_quiz_chain(request.email, request.secret, request.url)

    return {"status": "OK", "message": "Quiz task processed successfully"}
