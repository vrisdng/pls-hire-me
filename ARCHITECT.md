graph TD
    A[GitHub Actions] -->|Trigger: Daily 8 AM| B(Python Script)
    B -->|1. Scrape| C[JobSpy Library]
    C -->|LinkedIn/Glassdoor Data| B
    B -->|2. Analyze| D[Gemini 2.5 Flash-Lite API]
    D -->|Match Score & Reasoning| B
    B -->|3. Sync| E[Notion API]
    E -->|Update Table| F[(Notion Database)]
    B -->|4. Notify| G[Gmail SMTP]
    G -->|Direct Email| H[User Inbox]

### The Functional Workflow
- Search (Scraping):
The agent searches for keywords (Vibecoder, ML Engineer, Infra, etc.) with a specific seniority filter (Internship, Entry Level). It targets listings from the last 24 hours to avoid duplicates.

## Contextual Ranking (AI):
The script sends the JD to Gemini. The LLM evaluates it against a specific profile: Year 3 CS student at NUS, 6-month internship, expertise in React, TypeScript, Swift, and C. It outputs a Match Score (0-100) and a one-sentence "Reasoning."

## Lead Enrichment:
The script programmatically creates a LinkedIn Alumni Link using the company name and the university name (NUS). This appears as a clickable URL in Notion.

## Database Update:
A new row is created in your Notion table. If a job with the same URL already exists, the script skips it to prevent spam.

## Instant Alert:
If a job meets a certain threshold (e.g., Match Score > 75%), the agent triggers a smtplib call to your email, including the link to the Notion page for immediate action.

## Core Components
Layer,Tool,"2026 ""Free Tier"" Status"
Orchestrator,GitHub Actions,"2,000 min/mo (Private) or Unlimited (Public)."

The Crawler,JobSpy (Python),Open-source. No API keys or costs for LinkedIn/Glassdoor.

The Brain,Gemini 2.5 Flash-Lite,"1,000 requests/day for free (Google AI Studio)."

The Storage,Notion,Free personal account with unlimited API access.

The Messenger,Gmail SMTP,Free via Google App Passwords.