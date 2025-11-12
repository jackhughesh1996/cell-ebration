import streamlit as st
import google.generativeai as genai
import os
import re
import time
import json
from datetime import date
import io # Used to save files in memory
from docx import Document # For Word docs
from docx.shared import Pt # For setting font sizes
from docx.enum.text import WD_ALIGN_PARAGRAPH # For alignment

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
        
        # Auto-reset daily USAGE counter
        if filename == "usage.json" and data.get("date") != today_str:
            print("New day! Resetting API counters.") 
            save_to_file(filename, default_data)
            return default_data
        
        # Migrate old usage file format (if necessary)
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

# --- (3) WORD DOC HELPER FUNCTIONS ---
def inject_mcq_questions(doc, mcqs):
    """Finds the {{MCQ_SECTION}} placeholder and injects MCQs"""
    for para in doc.paragraphs:
        if "{{MCQ_SECTION}}" in para.text:
            para.text = "" # Clear the placeholder
            
            p_section = para.insert_paragraph_before()
            p_section.add_run("SECTION A – Multiple-Choice Questions").bold = True
            
            p_instructions = doc.add_paragraph()
            p_instructions.add_run("Answer all questions by selecting the correct option.")
            
            for i, q_data in enumerate(mcqs):
                doc.add_paragraph() 
                q_para = doc.add_paragraph()
                run = q_para.add_run(f"Question {i+1}\n")
                run.bold = True
                run = q_para.add_run(q_data.get("question_text", ""))
                run.bold = True
                
                for opt in q_data.get("options", []):
                    doc.add_paragraph(opt, style='List Paragraph')
            return True # Success
    return False # Placeholder not found

def inject_saq_questions(doc, saqs):
    """Finds the {{SAQ_SECTION}} placeholder and injects SAQs"""
    for para in doc.paragraphs:
        if "{{SAQ_SECTION}}" in para.text:
            para.text = "" # Clear the placeholder
            
            p_section = para.insert_paragraph_before()
            p_section.add_run("SECTION B – Short-Answer Questions").bold = True
            
            p_instructions = doc.add_paragraph()
            p_instructions.add_run("Answer all questions in the spaces provided.")
            
            for i, q_data in enumerate(saqs):
                doc.add_paragraph() 
                q_para = doc.add_paragraph()
                
                marks = q_data.get("marks", 1)
                run = q_para.add_run(f"Question {i+1} ({marks} mark{'s' if marks > 1 else ''})\n")
                run.bold = True
                run = q_para.add_run(q_data.get("question_text", ""))
                run.bold = True
                
                for _ in range(marks * 3):
                    doc.add_paragraph("_________________________________________________________________")
            
            return True # Success
    return False # Placeholder not found

# --- (4) DEFAULT DATA ---
DEFAULT_GEM_PROMPT = """
You are an expert VCE Science exam designer.
Your task is to generate a list of Multiple Choice Questions (MCQs) and Short Answer Questions (SAQs) based on a topic and a rubric.
Your output MUST be a single, valid JSON object. Do not include ```json backticks or any other text.

**CRITICAL INSTRUCTIONS:**
1.  **Rubric Coverage:** You *must* generate at least one question that assesses each and every criterion in the provided rubric.
2.  **Question Types:** Generate the exact number of MCQs and SAQs requested.
3.  **Strict JSON:** The entire output must be a single JSON object.

**JSON FORMAT:**
{
  "mcqs": [
    {
      "question_text": "The tendency to attribute our successes to internal factors and failures to external factors is called:",
      "options": [
        "A. Fundamental attribution error",
        "B. Actor-observer bias",
        "C. Self-serving bias",
        "D. Cognitive dissonance"
      ]
    }
  ],
  "saqs": [
    {
      "question_text": "Explain the difference between the 'affective' and 'behavioural' components of an attitude, providing an example for each.",
      "marks": 4
    }
  ]
}
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
        page_title="VCE Test Generator",
        layout="wide"
    )

    # --- (B) SESSION STATE INITIALIZATION ---
    if "api_key" not in st.session_state:
        st.session_state.api_key = None

    if "usage_data" not in st.session_state:
        st.session_state.usage_data = load_from_file("usage.json", DEFAULT_USAGE)

    # --- (C) UI: SIDEBAR ---
    st.sidebar.title("VCE AI Teacher Toolkit")
    st.sidebar.markdown("Welcome! This app helps you generate VCE resources. **Please enter your own Google API key below to get started.**")

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
        min_value=0.0, max_value=2.0, value=st.session_state.get("temperature", 0.0),
        step=0.1, key="temperature",
        help="0.0 = Factual, 2.0 = Creative"
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
    st.title("VCE Test Generator (.docx)")
    st.info("This tool uses a `test_template.docx` file. **This file MUST be in the same folder as the app (or in your GitHub repo).** Please update it with the placeholders (e.g., `{{SUBJECT_TITLE}}`, `{{MCQ_SECTION}}`, etc.).")
    
    # Store the prompt in the session state so it's editable
    if "gem_prompt" not in st.session_state:
        st.session_state.gem_prompt = DEFAULT_GEM_PROMPT
    
    with st.expander("View/Edit Gem Prompt"):
        st.session_state.gem_prompt = st.text_area(
            "Prompt for Test Generator:",
            value=st.session_state.gem_prompt,
            height=300,
            key="gem_test"
        )
    
    st.subheader("1. Fill in Title Page Details")
    col1, col2, col3 = st.columns(3)
    with col1:
        subject_title = st.text_input("Subject Title", "Year 7 Science")
    with col2:
        unit_title = st.text_input("Unit/SAC Title", "Unit 2 SAC Outcome 1")
    with col3:
        year = st.text_input("Year", "2025")

    st.subheader("2. Define Test Structure")
    col1, col2 = st.columns(2)
    with col1:
        num_mcq = st.number_input("Number of MCQs", min_value=0, value=10)
        marks_mcq = st.number_input("Total Marks for MCQs", min_value=0, value=10)
    with col2:
        num_saq = st.number_input("Number of SAQs", min_value=0, value=5)
        marks_saq = st.number_input("Total Marks for SAQs", min_value=0, value=10)
    
    st.subheader("3. Provide Content & Rubric")
    topic = st.text_input("Topic for the test:", "Year 7 Biology")
    rubric_text = st.text_area("Paste Rubric Here (to ensure question coverage):", "e.g., 'Criterion 1: Defines key terms.'\n'Criterion 2: Applies concepts to scenarios.'", height=150)

    if st.button("Generate Test"):
        if not all([topic, rubric_text, subject_title, unit_title, year]):
            st.warning("Please fill in all fields to generate the test.")
        elif not st.session_state.api_key:
            st.error("API Key not set. Please enter your API key in the sidebar.")
        else:
            user_prompt = f"""
            Topic: {topic}
            Rubric: {rubric_text}
            Number of MCQs: {num_mcq}
            Number of SAQs: {num_saq}
            Total Marks for SAQs: {marks_saq}
            """
            with st.spinner("Calling Gemini to generate questions (as JSON)..."):
                response = call_gemini_api(
                    st.session_state.gem_prompt,
                    user_prompt,
                    st.session_state.temperature,
                    st.session_state.model_name,
                    st.session_state.api_key # Pass the key explicitly
                )
            
            if response:
                try:
                    st.write("  > AI returned content. Parsing JSON...")
                    
                    json_start = response.find('{')
                    json_end = response.rfind('}') + 1
                    if json_start == -1 or json_end == -1:
                        raise json.JSONDecodeError("No JSON object found in response.", response, 0)
                    response_clean = response[json_start:json_end]
                    data = json.loads(response_clean)
                    
                    st.write("  > JSON parsed. Opening `test_template.docx`...")
                    
                    template_path = "test_template.docx"
                    if not os.path.exists(template_path):
                        st.error(f"`{template_path}` not found! Please create it and add the placeholders (e.g., {{SUBJECT_TITLE}}).")
                        st.stop()
                        
                    doc = Document(template_path)
                    
                    st.write("  > Replacing placeholders...")
                    total_questions = num_mcq + num_saq
                    total_marks = marks_mcq + marks_saq
                    
                    replacements = {
                        "{{SUBJECT TITLE}}": subject_title,
                        "{{SUBJECT_TITLE}}": subject_title,
                        "{{Unit Title}}": unit_title,
                        "{{UNIT_TITLE}}": unit_title,
                        "{{YEAR}}": year,
                        "{{MCQ_NUM}}": str(num_mcq),
                        "{{MCQ_MARKS}}": str(marks_mcq),
                        "{{SAQ_NUM}}": str(num_saq),
                        "{{SAQ_MARKS}}": str(marks_saq),
                        "{{TOTAL_QUESTIONS}}": str(total_questions),
                        "{{TOTAL_MARKS}}": str(total_marks),
                    }
                    
                    all_paragraphs = list(doc.paragraphs)
                    for table in doc.tables:
                        for row in table.rows:
                            for cell in row.cells:
                                all_paragraphs.extend(cell.paragraphs)

                    for p in all_paragraphs:
                        for key, value in replacements.items():
                            if key in p.text:
                                p.text = p.text.replace(key, value)
                                if key in ["{{SUBJECT TITLE}}", "{{SUBJECT_TITLE}}", "{{Unit Title}}", "{{UNIT_TITLE}}", "{{YEAR}}"]:
                                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    
                    st.write("  > Injecting MCQs and SAQs...")
                    mcq_success = inject_mcq_questions(doc, data.get("mcqs", []))
                    saq_success = inject_saq_questions(doc, data.get("saqs", []))
                    
                    if not mcq_success:
                        st.warning("Could not find '{{MCQ_SECTION}}' placeholder. MCQs were not added.")
                    if not saq_success:
                        st.warning("Could not find '{{SAQ_SECTION}}' placeholder. SAQs were not added.")

                    st.write("  > Saving to memory buffer...")
                    bio = io.BytesIO()
                    doc.save(bio)
                    
                    st.success("Test generated!")
                    st.download_button(
                        label="Download Test as .docx",
                        data=bio.getvalue(),
                        file_name=f"{subject_title.replace(' ', '_')}_{unit_title.replace(' ', '_')}_test.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )
                    
                except json.JSONDecodeError:
                    st.error("AI returned invalid JSON. Could not create .docx.")
                    st.text_area("Raw AI Output (for debugging):", value=response, height=200)
                except Exception as e:
                    st.error(f"Failed to create .docx file. Error: {e}")
                    st.text_area("Raw AI Output (for debugging):", value=response, height=200)

# --- (6) THIS BLOCK RUNS THE SCRIPT ---
if __name__ == "__main__":
    main()
