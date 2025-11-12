import streamlit as st
import google.generativeai as genai
import pdfplumber
import os
import re
import time
import json
from datetime import date
import io # Used to save files in memory
from pptx import Presentation # <-- NEW: For PowerPoint files

# --- (1) PERSISTENT FILE HELPERS (FOR USAGE COUNTER) ---
def load_from_file(filename, default_data):
    """Loads data from a JSON file. If file doesn't exist or is old, creates a new one."""
    today_str = str(date.today())
    
    if not os.path.exists(filename):
        save_to_file(filename, default_data)
        return default_data
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if filename == "usage.json" and data.get("date") != today_str:
            print("New day! Resetting API counters.") 
            save_to_file(filename, default_data)
            return default_data
        
        if filename == "usage.json" and "count" in data and "counts" not in data:
            new_data = {
                "date": data.get("date", today_str),
                "counts": {"total_legacy_calls": data.get("count", 0)}
            }
            save_to_file(filename, new_data)
            return new_data

        return data
            
    except json.JSONDecodeError:
        print(f"Error reading {filename}. File might be corrupt. Creating a new one.")
        save_to_file(filename, default_data)
        return default_data

def save_to_file(filename, data):
    """Saves data to a JSON file."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- (2) CORE GEMINI API FUNCTION ---
DELAYS = {
    "gemini-2.5-flash-lite": 5,
    "gemini-2.5-flash": 7,
    "gemini-2.5-pro": 13
}

def call_gemini_api(system_prompt, user_prompt, temperature, model_name, api_key):
    """
    A single, safe function to call the Gemini API.
    It checks for an API key, updates the usage counter, and respects rate limits.
    """
    if not api_key:
        st.error("API Key not set. Please enter your API key in the sidebar.")
        return None

    try:
        genai.configure(api_key=api_key)
        config = genai.GenerationConfig(temperature=temperature)
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
            generation_config=config
        )
        
        response = model.generate_content(user_prompt)
        
        # Increment the per-model counter
        if model_name not in st.session_state.usage_data["counts"]:
            st.session_state.usage_data["counts"][model_name] = 0
        st.session_state.usage_data["counts"][model_name] += 1
        save_to_file("usage.json", st.session_state.usage_data)
        
        delay = DELAYS.get(model_name, 7)
        time.sleep(delay)
        
        return response.text

    except Exception as e:
        st.error(f"An API error occurred: {e}")
        return None

# --- (3) CONTENT EXTRACTION FUNCTIONS ---

def extract_text_from_pdf(file_bytes):
    """Extracts text from an uploaded PDF file."""
    text = ""
    with pdfplumber.open(file_bytes) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def extract_text_from_pptx(file_bytes):
    """Extracts text from an uploaded PowerPoint file."""
    text = ""
    prs = Presentation(file_bytes)
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                text += shape.text + "\n"
    return text

# --- (4) DEFAULT DATA ---
DEFAULT_GEM_PROMPT = """
You are a VCE question generator. Your task is to create a list of questions and answers
for a Gimkit quiz, based on the provided text.

**YOUR INSTRUCTIONS:**
1.  **Read the Text:** Read the provided source text to get context for the questions.
2.  **Generate Questions:** Create the requested number of questions.
3.  **Format:** You MUST format your output as a valid CSV (Comma Separated Values)
    with 5 columns, matching the Gimkit template:
    `Question,Correct Answer,Incorrect Answer 1,Incorrect Answer 2,Incorrect Answer 3`
4.  **Strict Output:** Do NOT add any other text, explanation, or ```csv backticks.
    Your entire response must be *only* the raw CSV data rows.

**EXAMPLE OUTPUT:**
"What is the capital of France?","Paris","London","Berlin","Rome"
"Who wrote Hamlet?","William Shakespeare","Charles Dickens","Leo Tolstoy","Jane Austen"
"""

DEFAULT_USAGE = {
    "date": str(date.today()),
    "counts": {
        "gemini-2.5-flash-lite": 0,
        "gemini-2.5-flash": 0,
        "gemini-2.5-pro": 0
    }
}

# --- (5) MAIN APP FUNCTION ---
def main():
    """Main function to run the Streamlit app."""
    
    st.set_page_config(
        page_title="Gimkit CSV Generator",
        layout="wide"
    )

    # --- (B) SESSION STATE INITIALIZATION ---
    if "api_key" not in st.session_state:
        st.session_state.api_key = None

    if "usage_data" not in st.session_state:
        st.session_state.usage_data = load_from_file("usage.json", DEFAULT_USAGE)
    
    if "gem_prompt" not in st.session_state:
        st.session_state.gem_prompt = DEFAULT_GEM_PROMPT

    # --- (C) UI: SIDEBAR ---
    st.sidebar.title("Configuration")
    st.sidebar.markdown("Enter your Google API key to activate the app.")

    st.session_state.api_key = st.sidebar.text_input(
        "Enter your Google API Key",
        type="password",
        value=st.session_state.get("api_key")
    )

    model_name = st.sidebar.selectbox(
        "Choose your AI model",
        ("gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"),
        key="model_name"
    )

    temperature = st.sidebar.slider(
        "Set AI 'creativity' (Temperature)",
        min_value=0.0, max_value=2.0, value=st.session_state.get("temperature", 0.7),
        step=0.1, key="temperature",
        help="0.0 = Factual, 0.7 = Balanced, 2.0 = Wildly Creative"
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("Daily Usage")
    counts = st.session_state.usage_data.get("counts", {})
    LIMITS = {"gemini-2.5-flash-lite": 1000, "gemini-2.5-flash": 250, "gemini-2.5-pro": 50}

    if not counts:
        st.sidebar.text("No calls made today.")
    else:
        for model, count in counts.items():
            limit = LIMITS.get(model, 1)
            label = f"{model} ({count} / {limit})"
            progress = min(count / limit, 1.0)
            st.sidebar.text(label)
            st.sidebar.progress(progress)

    if st.sidebar.button("Reset All Counters"):
        st.session_state.usage_data = DEFAULT_USAGE
        save_to_file("usage.json", st.session_state.usage_data)
        st.rerun()

    # --- (D) UI: MAIN PAGE ---
    st.title("Gimkit CSV Generator")
    st.info("This tool reads a PDF or PowerPoint, generates questions, and formats them for Gimkit.")
    
    with st.expander("View/Edit Gem Prompt"):
        st.session_state.gem_prompt = st.text_area(
            "Prompt for Gimkit Generator:",
            value=st.session_state.gem_prompt,
            height=300,
            key="gem_gimkit"
        )
    
    st.subheader("1. Upload Your Content")
    uploaded_file = st.file_uploader(
        "Upload a PDF or PowerPoint file",
        type=["pdf", "pptx"],
        key="content_uploader"
    )

    st.subheader("2. Set Question Count")
    num_questions = st.number_input(
        "Number of questions to generate:",
        min_value=5, max_value=50, value=15
    )
    
    st.subheader("3. Generate")
    if st.button("Generate Gimkit CSV"):
        if not uploaded_file:
            st.warning("Please upload a file.")
        elif not st.session_state.api_key:
            st.error("API Key not set in sidebar.")
        else:
            source_text = ""
            with st.spinner(f"Reading {uploaded_file.name}..."):
                try:
                    file_bytes = io.BytesIO(uploaded_file.getvalue())
                    if uploaded_file.type == "application/pdf":
                        source_text = extract_text_from_pdf(file_bytes)
                    elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
                        source_text = extract_text_from_pptx(file_bytes)
                    
                    # Truncate text to avoid hitting token limits (e.g., ~30k chars)
                    if len(source_text) > 30000:
                        st.warning("File is very large. Summarizing based on the first ~30,000 characters.")
                        source_text = source_text[:30000]
                        
                except Exception as e:
                    st.error(f"Failed to read file. Error: {e}")
                    source_text = None

            if source_text:
                user_prompt = f"""
                Please generate {num_questions} questions based on the following text:
                
                ---
                {source_text}
                ---
                """
                
                with st.spinner("Calling Gemini to generate questions..."):
                    response = call_gemini_api(
                        st.session_state.gem_prompt,
                        user_prompt,
                        st.session_state.temperature,
                        st.session_state.model_name,
                        st.session_state.api_key
                    )
                
                if response:
                    st.success("Questions generated!")
                    
                    # Clean the AI's response
                    response_clean = re.sub(r'```csv\n(.*?)\n```', r'\1', response, flags=re.DOTALL)
                    response_clean = response_clean.strip()
                    
                    # Add the official Gimkit header
                    gimkit_header = "Question,Correct Answer,Incorrect Answer 1,Incorrect Answer 2 (Optional),Incorrect Answer 3 (Optional)\n"
                    final_csv_data = gimkit_header + response_clean
                    
                    st.download_button(
                        label="Download Gimkit CSV",
                        data=final_csv_data.encode('utf-8'),
                        file_name=f"{uploaded_file.name}_gimkit_quiz.csv",
                        mime="text/csv"
                    )
                    with st.expander("Preview raw CSV data"):
                        st.text(final_csv_data)

# --- (6) THIS BLOCK RUNS THE SCRIPT ---
if __name__ == "__main__":
    main()
