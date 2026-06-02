import os
import json
import time
import pypdf
from google import genai
from playwright.sync_api import sync_playwright

EXTRACT_ELEMENTS_JS = """
() => {
    const serializableElements = [];
    const elements = document.querySelectorAll('input, textarea, select');
    
    function getUniqueSelector(el) {
        if (el.id) return `#${el.id}`;
        if (el.name) return `${el.tagName.toLowerCase()}[name="${el.name}"]`;
        
        let path = [];
        let curr = el;
        while (curr && curr.nodeType === Node.ELEMENT_NODE) {
            let selector = curr.nodeName.toLowerCase();
            if (curr.id) {
                selector += '#' + curr.id;
                path.unshift(selector);
                break;
            } else {
                let sibling = curr;
                let nth = 1;
                while (sibling = sibling.previousElementSibling) {
                    if (sibling.nodeName.toLowerCase() === curr.nodeName.toLowerCase()) nth++;
                }
                if (nth !== 1) selector += `:nth-of-type(${nth})`;
            }
            path.unshift(selector);
            curr = curr.parentNode;
        }
        return path.join(" > ");
    }

    for (const el of elements) {
        // Skip hidden fields or fields that are not visible
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || el.type === 'hidden') {
            continue;
        }
        
        let labelText = "";
        if (el.id) {
            const label = document.querySelector(`label[for="${el.id}"]`);
            if (label) labelText = label.innerText;
        }
        if (!labelText) {
            const parentLabel = el.closest('label');
            if (parentLabel) labelText = parentLabel.innerText;
        }
        if (!labelText) {
            let sibling = el.previousSibling;
            while (sibling) {
                if (sibling.nodeType === Node.TEXT_NODE && sibling.textContent.trim()) {
                    labelText = sibling.textContent.trim();
                    break;
                }
                if (sibling.nodeType === Node.ELEMENT_NODE) {
                    labelText = sibling.innerText || sibling.textContent || "";
                    if (labelText.trim()) break;
                }
                sibling = sibling.previousSibling;
            }
        }
        if (!labelText) {
            labelText = el.placeholder || el.name || el.id || "";
        }
        
        const elementData = {
            tagName: el.tagName.toLowerCase(),
            type: el.type || '',
            name: el.name || '',
            id: el.id || '',
            placeholder: el.placeholder || '',
            labelText: labelText.trim(),
            selector: getUniqueSelector(el)
        };
        
        if (el.tagName.toLowerCase() === 'select') {
            elementData.options = Array.from(el.options).map(opt => ({
                value: opt.value,
                text: opt.text.trim()
            }));
        }
        
        serializableElements.push(elementData);
    }
    return serializableElements;
}
"""

def extract_resume_text(pdf_path):
    if not os.path.exists(pdf_path):
        print(f"Resume PDF not found at: {pdf_path}")
        return ""
    try:
        reader = pypdf.PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return ""

def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables.")
    return genai.Client(api_key=api_key)

def handle_job_board_redirects(page):
    current_url = page.url
    # LinkedIn Job Page
    if "linkedin.com" in current_url:
        print("Detected LinkedIn job page. Looking for external apply button...")
        try:
            # Common LinkedIn apply selectors
            # Wait for apply button or easy apply button
            page.wait_for_selector(".jobs-apply-button, a[href*='apply'], button[aria-label*='Apply']", timeout=5000)
            apply_button = page.locator(".jobs-apply-button, a[href*='apply'], button[aria-label*='Apply']").first
            if apply_button.is_visible():
                print("Found Apply button. Clicking...")
                # Handle popup/tab redirect
                try:
                    with page.context.expect_page(timeout=10000) as new_page_info:
                        apply_button.click()
                    new_page = new_page_info.value
                    new_page.wait_for_load_state("load")
                    print(f"Redirected to external page: {new_page.url}")
                    return new_page
                except Exception as popup_err:
                    print(f"No popup opened, checking same page redirect... {popup_err}")
                    # If no popup, maybe it navigated in the same tab
                    page.wait_for_load_state("load")
                    return page
        except Exception as e:
            print(f"Error handling LinkedIn apply: {e}")
            
    # Indeed Job Page
    elif "indeed.com" in current_url:
        print("Detected Indeed job page. Looking for apply button...")
        try:
            page.wait_for_selector("a[href*='apply'], button:has-text('Apply Now'), #applyButton", timeout=5000)
            apply_button = page.locator("a[href*='apply'], button:has-text('Apply Now'), #applyButton").first
            if apply_button.is_visible():
                print("Found Indeed Apply button. Clicking...")
                try:
                    with page.context.expect_page(timeout=10000) as new_page_info:
                        apply_button.click()
                    new_page = new_page_info.value
                    new_page.wait_for_load_state("load")
                    print(f"Redirected to external page: {new_page.url}")
                    return new_page
                except Exception:
                    page.wait_for_load_state("load")
                    return page
        except Exception as e:
            print(f"Error handling Indeed apply: {e}")
            
    return page

def analyze_and_map_form(client, resume_text, personal_details, elements):
    prompt = f"""
    You are an automated assistant helping a user apply for a job.
    Here is the user's resume content:
    ---
    {resume_text}
    ---

    Here is the user's personal details and question preferences configuration:
    {json.dumps(personal_details, indent=2)}

    Here is a list of interactive form elements extracted from the job application page:
    {json.dumps(elements, indent=2)}

    Your task:
    1. Determine if this page requires creating an account or logging in to apply (e.g., if it is a login screen, sign-in screen, or requires authentication/registration first). If it does, set "requires_account": true.
    2. If it does not require an account, set "requires_account": false, and map the user's information to the form elements.
    3. For each element in the list, determine:
       - What action to perform: "fill", "check", "select", "upload", or "skip".
       - The value to fill, select, check, or upload.
       - If it's a file upload (type is "file") and is for the Resume or CV, the value should be the filename "NGOCMAI_RESUME_MAY.pdf". If it's for cover letter or other files, skip it unless configured.
       - For text/email/tel inputs, use the appropriate details from personal_details or resume_text.
       - For select elements (dropdowns), choose the option value that best matches the user's details. If there's a gender/diversity/ethnicity question, choose "Decline to Self-Identify" or equivalent.
       - For work authorization or citizenship screening questions, map them to the corresponding values in personal_details (e.g. "I will need sponsorship.", "international/Others (I'm not Singaporean/PR)").
       - For checkbox or radio options (like terms and conditions, privacy agreements), choose the one that enables submission, using "check" action.

    Return ONLY a JSON response in the following format (no markdown code blocks, just raw JSON):
    {{
      "requires_account": false,
      "actions": [
        {{
          "selector": "#selector_here",
          "frame_index": 0,
          "action": "fill|check|select|upload|skip",
          "value": "value_here"
        }}
      ]
    }}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error calling Gemini for form analysis: {e}")
        return {"requires_account": False, "actions": []}

def execute_form_actions(page, actions, resume_abs_path):
    print(f"Executing {len(actions)} form actions...")
    for idx, act in enumerate(actions):
        selector = act.get("selector")
        action_type = act.get("action")
        value = act.get("value")
        frame_idx = act.get("frame_index", 0)
        
        if action_type == "skip" or not selector:
            continue
            
        # Get appropriate frame
        frame = page.frames[frame_idx] if frame_idx < len(page.frames) else page
        
        try:
            locator = frame.locator(selector).first
            if not locator.is_visible():
                print(f"[{idx+1}] Skipping invisible element: {selector}")
                continue
                
            print(f"[{idx+1}] Action: {action_type} | Selector: {selector} | Value: {value}")
            
            if action_type == "fill":
                locator.focus()
                # Clear existing text first
                locator.fill("")
                locator.type(str(value))
            elif action_type == "check":
                locator.check()
            elif action_type == "select":
                locator.select_option(value=str(value))
            elif action_type == "upload":
                if "NGOCMAI_RESUME_MAY.pdf" in str(value):
                    if os.path.exists(resume_abs_path):
                        locator.set_input_files(resume_abs_path)
                        print(f"Uploaded resume: {resume_abs_path}")
                    else:
                        print(f"Resume PDF not found at absolute path: {resume_abs_path}")
                else:
                    print(f"Skipping non-resume upload: {value}")
        except Exception as e:
            print(f"Error executing action on {selector}: {e}")

def apply_to_job(job_url, config_data):
    app_config = config_data.get("application", {})
    mode = app_config.get("mode", "review")
    resume_path = app_config.get("resume_path", "NGOCMAI_RESUME_MAY.pdf")
    resume_abs_path = os.path.abspath(resume_path)
    personal_details = app_config.get("personal_details", {})
    
    print(f"Starting application pipeline for URL: {job_url}")
    
    # Read resume text
    resume_text = extract_resume_text(resume_abs_path)
    if not resume_text:
        print("Warning: Resume content is empty. Form filling quality might be affected.")
        
    client = get_gemini_client()
    
    with sync_playwright() as p:
        # Launch headed browser if mode is review, otherwise headless
        headless = (mode != "review")
        print(f"Launching browser (headless={headless})...")
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # Navigate to the job listing page
        print(f"Navigating to {job_url}...")
        try:
            page.goto(job_url, timeout=30000, wait_until="load")
        except Exception as err:
            print(f"Failed to load page directly: {err}")
            browser.close()
            return False
            
        # Follow job board apply button redirects
        page = handle_job_board_redirects(page)
        
        # Wait for page and any redirect navigation to settle
        print("Waiting for page and frames to settle...")
        try:
            page.wait_for_load_state("load", timeout=10000)
        except Exception:
            pass
            
        # Dynamically wait up to 15 seconds for a frame to load actual job application inputs
        print("Waiting for application form elements to render...")
        start_time = time.time()
        form_loaded = False
        while time.time() - start_time < 15:
            # Re-fetch frames since new iframes might have been injected
            for frame in page.frames:
                try:
                    raw_count = frame.evaluate("() => document.querySelectorAll('input, textarea, select').length")
                    # If any frame has more than 3 input elements, we assume the form has loaded
                    if raw_count >= 4:
                        form_loaded = True
                        break
                except Exception:
                    continue
            if form_loaded:
                break
            time.sleep(1.0)
            
        # Give it a tiny bit extra time to settle rendering
        time.sleep(2)
        
        print(f"Current page after redirection: {page.url}")
        
        # Extract interactive form elements from all frames
        print(f"Total frames: {len(page.frames)}")
        for idx, frame in enumerate(page.frames):
            print(f"Frame {idx}: name='{frame.name}', url='{frame.url}'")
            
        elements = []
        for idx, frame in enumerate(page.frames):
            try:
                # Get raw count of elements before filtering
                raw_count = frame.evaluate("() => document.querySelectorAll('input, textarea, select').length")
                print(f"Frame {idx} has {raw_count} raw input/textarea/select elements.")
                
                frame_elements = frame.evaluate(EXTRACT_ELEMENTS_JS)
                print(f"Frame {idx} has {len(frame_elements)} visible/serializable elements.")
                for el in frame_elements:
                    el['frame_index'] = idx
                    elements.append(el)
            except Exception as e:
                print(f"Error evaluating in Frame {idx}: {e}")
                continue
                
        if not elements:
            print("No interactive form elements found on the page. Taking debugging screenshot 'debug_no_elements.png'...")
            try:
                page.screenshot(path="debug_no_elements.png")
                print("Saved screenshot to debug_no_elements.png")
            except Exception as ss_err:
                print(f"Failed to save screenshot: {ss_err}")
            browser.close()
            return False
            
        print(f"Extracted {len(elements)} input elements. Mapping using Gemini...")
        
        # Send to Gemini to determine if page requires accounts, and map fields
        mapping = analyze_and_map_form(client, resume_text, personal_details, elements)
        
        if mapping.get("requires_account"):
            print("Page requires account creation/login. Skipping as per configuration.")
            browser.close()
            return False
            
        actions = mapping.get("actions", [])
        if not actions:
            print("No form mapping actions returned by Gemini.")
            browser.close()
            return False
            
        # Execute form filling actions
        execute_form_actions(page, actions, resume_abs_path)
        print("Form filling complete.")
        
        # Determine next steps based on mode
        if mode == "review":
            print("\n" + "="*80)
            print("REVIEW MODE ACTIVE")
            print("The application form has been pre-filled and the resume uploaded.")
            print("Please review the browser window, correct any errors, and manually click 'Submit'.")
            print("Press ENTER in this terminal when you are done to close the browser and proceed...")
            print("="*80 + "\n")
            input() # Wait for user to press enter in console
            browser.close()
            return True
        else:
            # Auto submit mode
            print("Auto mode active. Attempting to locate and click submit button...")
            try:
                # Common submit buttons selectors
                submit_selectors = [
                    "input[type='submit']",
                    "button[type='submit']",
                    "#submit-button",
                    ".submit-button",
                    "button:has-text('Submit')",
                    "button:has-text('Apply')",
                    "input:has-text('Submit')",
                    "input:has-text('Apply')"
                ]
                
                submitted = False
                for sel in submit_selectors:
                    btn = page.locator(sel).first
                    if btn.is_visible():
                        print(f"Found submit button with selector: {sel}. Clicking...")
                        btn.click()
                        submitted = True
                        break
                
                if submitted:
                    page.wait_for_load_state("networkidle", timeout=10000)
                    print("Form submission click executed. Waiting 5s for completion...")
                    time.sleep(5)
                    print(f"Completed submission. Final page url: {page.url}")
                    browser.close()
                    return True
                else:
                    print("Could not find a clear Submit button. Leaving browser open for review.")
                    input("Press ENTER to close the browser...")
                    browser.close()
                    return False
            except Exception as e:
                print(f"Error during auto-submission: {e}")
                browser.close()
                return False
