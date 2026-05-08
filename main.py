import os
import json
import smtplib
from email.message import EmailMessage
from jobspy import scrape_jobs
from google import genai
from notion_client import Client
import pandas as pd
from dotenv import load_dotenv

# Load local environment variables if present
load_dotenv()

# Load Configuration
with open("config.json", "r") as f:
    config = json.load(f)

# Initialize Clients
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
notion_token = os.environ.get("NOTION_TOKEN", "")
if notion_token:
    notion = Client(auth=notion_token)
else:
    notion = None

# 1. AI Matching Logic
def analyze_match(title, jd, company):
    profile = config.get("profile", {})
    prompt = f"""
    You are a career consultant for a user with the following profile:
    Education: {profile.get('education')}
    Experience: {profile.get('experience')}
    Skills: {', '.join(profile.get('skills', []))}
    Career Level: {profile.get('career_level')}
    Preferences/Goals: {profile.get('preferences')}

    Your task:
    Analyze the provided Job Description (JD) and Job Title.
    Evaluate how well the student fits the role (0-100) based on their technical stack, career level, and especially their preferences/goals.
    Perform a semantic match. Do not just look for exact keyword matches. Consider whether the role aligns with what the user is looking for (e.g., if they want part-time, is it part-time? If they want architecture, does it involve system design?).

    Role: {title} at {company}
    JD: {jd[:3000]}

    Return ONLY a JSON object exactly like this, with no markdown formatting:
    {{"score": 85, "reason": "Good fit because...", "skills_missing": ["Docker", "AWS"]}}
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error calling Gemini or parsing response: {e}")
        return {"score": 0, "reason": "Error parsing response", "skills_missing": []}

# 2. Email Notification
def notify(job, analysis):
    email_addr = os.environ.get("EMAIL_ADDRESS")
    email_pass = os.environ.get("EMAIL_APP_PASSWORD")
    if not email_addr or not email_pass:
        print("Skipping email notification: missing credentials.")
        return

    msg = EmailMessage()
    msg.set_content(f"Match: {analysis.get('score')}%\nReason: {analysis.get('reason')}\nMissing Skills: {', '.join(analysis.get('skills_missing', []))}\nLink: {job.get('job_url')}")
    msg['Subject'] = f"🚀 {analysis.get('score')}% Match: {job.get('title')} @ {job.get('company')}"
    msg['From'], msg['To'] = email_addr, email_addr
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(email_addr, email_pass)
            smtp.send_message(msg)
            print(f"Email sent for {job.get('title')} at {job.get('company')}")
    except Exception as e:
        print(f"Failed to send email: {e}")

# 3. Main Workflow
def run():
    search_config = config.get("search", {})
    locations = search_config.get("locations", ["Singapore"])
    keywords = search_config.get("keywords", ["Software Engineer"])
    title_must_contain = search_config.get("title_must_contain", [])
    results_wanted = search_config.get("results_wanted_per_location", 10)
    hours_old = search_config.get("hours_old", 24)
    
    all_jobs = []
    
    for location in locations:
        for keyword in keywords:
            print(f"Scraping jobs for location: {location} with keyword: '{keyword}'")
            try:
                jobs = scrape_jobs(
                    site_name=["linkedin", "indeed"],
                    search_term=keyword,
                    location=location,
                    results_wanted=results_wanted,
                    hours_old=hours_old
                )
                if not jobs.empty:
                    all_jobs.append(jobs)
            except Exception as e:
                print(f"Error scraping for {location} with '{keyword}': {e}")
            
    if not all_jobs:
        print("No jobs found.")
        return
        
    jobs_df = pd.concat(all_jobs, ignore_index=True)
    jobs_df = jobs_df.drop_duplicates(subset=['job_url'])
    
    print(f"Found {len(jobs_df)} unique jobs. Analyzing matches...")
    
    for _, job in jobs_df.iterrows():
        title = str(job.get('title', 'Unknown'))
        
        # Skip jobs that don't match our title requirements
        if title_must_contain:
            if not any(term.lower() in title.lower() for term in title_must_contain):
                print(f"Skipping: '{title}' (Title does not contain required terms)")
                continue

        company = str(job.get('company', 'Unknown'))
        description = str(job.get('description', ''))
        url = str(job.get('job_url', ''))
        date_posted = str(job.get('date_posted', ''))
        
        analysis = analyze_match(title, description, company)
        score = analysis.get('score', 0)
        print(f"[{score}%] {title} at {company} - {analysis.get('reason')}")
        
        # Sync to Notion
        if notion:
            uni_name = config.get("notion", {}).get("university_name_for_connections", "NUS")
            company_encoded = company.replace(' ', '%20')
            connections_url = f"https://www.linkedin.com/search/results/people/?keywords={company_encoded}%20{uni_name}"
            
            properties = {
                "Role": {"title": [{"text": {"content": title[:2000]}}]},
                "Company": {"rich_text": [{"text": {"content": company[:2000]}}]},
                "Match Score": {"number": score},
                "Connections": {"url": connections_url[:2000]},
                "Link": {"url": url[:2000]}
            }
            if len(date_posted) >= 10 and date_posted.lower() not in ["nan", "nat", "none"]:
                properties["Date"] = {"date": {"start": date_posted[:10]}}
                
            try:
                notion.pages.create(
                    parent={"database_id": os.environ["NOTION_DB_ID"]},
                    properties=properties
                )
            except Exception as e:
                print(f"Failed to sync to Notion: {e}")
        
        if score >= 80:
            notify(job, analysis)

if __name__ == "__main__":
    run()
