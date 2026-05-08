
# 🚀 Gemini Job-Hunter Agent (NUS Edition)

An automated, zero-cost agent that crawls **LinkedIn** and **Glassdoor**, evaluates roles against an **NUS CS student profile** using **Gemini 1.5 Flash**, syncs leads to **Notion**, and sends **Email Alerts**.

## 🏗️ Architecture Overview

1. **Orchestrator:** GitHub Actions (runs daily at 01:00 UTC).
2. **Scraper:** `python-jobspy` (crawls job boards without API fees).
3. **Brain:** `gemini-1.5-flash` (free-tier AI for matching and JD analysis).
4. **Database:** Notion API (stores and organizes job leads).
5. **Notifications:** Gmail SMTP (sends instant match alerts).

---

## 🛠️ Setup Instructions

### 1. Notion Configuration

* Create a Notion Database with these properties:
* `Role` (Title)
* `Company` (Select)
* `Match Score` (Number)
* `Connections` (URL)
* `Link` (URL)
* `Date` (Date)


* Create an integration at [developers.notion.com](https://www.notion.so/my-integrations).
* **Share** the database with your integration (Top right `...` -> `Connect to`).

### 2. Gmail Setup

* Enable 2-Step Verification on your Google Account.
* Generate an **App Password** at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
* Save the 16-character code.

### 3. GitHub Secrets

Go to your Repo Settings -> **Secrets and Variables** -> **Actions** and add:

* `NOTION_TOKEN`: Your Notion integration secret.
* `NOTION_DB_ID`: The 32-character ID from your Database URL.
* `GEMINI_API_KEY`: From [Google AI Studio](https://aistudio.google.com/).
* `EMAIL_ADDRESS`: Your Gmail.
* `EMAIL_APP_PASSWORD`: The 16-character App Password.

---

## 🐍 The Agent Code (`main.py`)

```python
import os
import json
import smtplib
from email.message import EmailMessage
from jobspy import scrape_jobs
import google.generativeai as genai
from notion_client import Client

# Initialize Clients
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
notion = Client(auth=os.environ["NOTION_TOKEN"])
model = genai.GenerativeModel('gemini-1.5-flash')

# 1. AI Matching Logic
def analyze_match(title, jd, company):
    prompt = f"""
    User: Year 3 CS Student at NUS. 6-mo internship. Skills: React, TS, Swift, SwiftUI, C.
    Evaluate match (0-100) for this role: {title} at {company}.
    JD: {jd[:3000]}
    Return JSON: {{"score": int, "reason": "str", "skills_missing": []}}
    """
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    return json.loads(response.text)

# 2. Email Notification
def notify(job, analysis):
    msg = EmailMessage()
    msg.set_content(f"Match: {analysis['score']}%\nReason: {analysis['reason']}\nLink: {job['job_url']}")
    msg['Subject'] = f"🚀 {analysis['score']}% Match: {job['title']} @ {job['company']}"
    msg['From'], msg['To'] = os.environ["EMAIL_ADDRESS"], os.environ["EMAIL_ADDRESS"]
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(os.environ["EMAIL_ADDRESS"], os.environ["EMAIL_APP_PASSWORD"])
        smtp.send_message(msg)

# 3. Main Workflow
def run():
    jobs = scrape_jobs(
        site_name=["linkedin", "glassdoor"],
        search_term="Software Engineer, ML Engineer, Vibecoder, Frontend, Product Manager",
        location="Singapore", # Update to "London, UK" or "Berlin" for Europe goals
        results_wanted=10,
        hours_old=24
    )

    for _, job in jobs.iterrows():
        analysis = analyze_match(job['title'], job['description'], job['company'])
        
        # Sync to Notion
        notion.pages.create(
            parent={"database_id": os.environ["NOTION_DB_ID"]},
            properties={
                "Role": {"title": [{"text": {"content": job['title']}}]},
                "Company": {"select": {"name": job['company']}},
                "Match Score": {"number": analysis['score']},
                "Connections": {"url": f"https://www.linkedin.com/search/results/people/?keywords={job['company']}%20NUS"},
                "Link": {"url": job['job_url']},
                "Date": {"date": {"start": job['date_posted']}}
            }
        )
        
        if analysis['score'] >= 80:
            notify(job, analysis)

if __name__ == "__main__":
    run()

```

---

## 🚀 Deployment (`.github/workflows/agent.yml`)

```yaml
name: Job Agent
on:
  schedule:
    - cron: '0 1 * * *'
jobs:
  run-agent:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - sudo apt-get install python3
      - run: pip install python-jobspy notion-client google-generativeai pandas
      - run: python main.py
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_DB_ID: ${{ secrets.NOTION_DB_ID }}
          EMAIL_ADDRESS: ${{ secrets.EMAIL_ADDRESS }}
          EMAIL_APP_PASSWORD: ${{ secrets.EMAIL_APP_PASSWORD }}

```

---

## 🎯 Targeting Strategy

* **Keywords:** Included `Vibecoder` for niche listings and `ML Engineer`/`Infra` for core CS roles.
* **Europe Goal:** To pivot your search toward your European internship goal, simply update the `location` variable in `main.py` to `London` or `Amsterdam`.
* **Alumni Power:** Every Notion entry automatically generates a LinkedIn link filtered for **NUS Alumni** at that specific company.