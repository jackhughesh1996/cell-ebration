import streamlit as st
import google.generativeai as genai
import pdfplumber
import os
import re
import time
import json
from datetime import date
import io # Used to save files in memory

# --- (1) PAGE CONFIGURATION ---
st.set_page_config(
    page_title="VCE AI Teacher Toolkit",
    layout="wide"
)

# --- (2) PERSISTENT FILE HELPERS (for Gems) ---
# This app is "stateless" (no chat history) but we'll save Gems
def load_gems(filename="gems.json", default_data={}):
    if not os.path.exists(filename):
        save_to_file(filename, default_data)
        return default_data
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default_data

def save_to_file(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- (3) CORE GEMINI API FUNCTION ---
# This is our global function to call the API, now with smart delays
DELAYS = {
    "gemini-2.5-flash-lite": 5,
    "gemini-2.5-flash": 7,
    "gemini-2.5-pro": 13
}

def call_gemini_api(system_prompt, user_prompt, temperature, model_name):
    """A single, safe function to call the Gemini API."""
    api_key = st.session_state.get("api_key")
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
        delay = DELAYS.get(model_name, 7)
        time.sleep(delay)
        return response.text

    except Exception as e:
        st.error(f"An API error occurred: {e}")
        return None

# --- (4) DEFAULT GEMS & DATA ---
DEFAULT_GEMS = {
    "Blank Gem": "You are a helpful assistant.",
    
    "Test Generator (.docx)": """
You are an expert VCE exam designer. Your task is to generate a test in a specific format.
The user will provide the test format, a topic, and the number of questions.

**YOUR INSTRUCTIONS:**
1.  **Strictly Follow Format:** Adhere *exactly* to the provided test format.
2.  **Generate Content:** Create the requested number of questions on the given topic, matching the style of the format.
3.  **Provide Answers:** After the test, include a separate "Answer Key" section.
4.  **Output:** Your output must be plain text, ready to be pasted into a Word document. Do not use Markdown or HTML.
""",

    "PowerPoint Generator (.pptx)": """
You are an expert VCE educator. Your task is to generate the *content* for a PowerPoint presentation based on a textbook chunk.
The output format MUST be a specific JSON structure.

**INPUT:**
You will receive a chunk of text from a textbook.

**YOUR TASK:**
1.  Read the text and identify the main title and key concepts.
2.  Generate a title slide and several content slides based on the text.
3.  Respond *only* with a JSON object in this exact format:
    {
      "slides": [
        {"title": "Slide 1 Title", "body": ["Bullet point 1", "Bullet point 2"]},
        {"title": "Slide 2 Title", "body": ["Bullet point 1", "Bullet point 2", "Bullet point 3"]},
        {"title": "Slide 3 Title", "body": ["Bullet point 1", "Bullet point 2"]}
      ]
    }
""",
    "Gimkit Generator (.csv)": """
You are a question generator. Your task is to create a list of questions and answers on a given topic.
The output format MUST be a valid CSV (Comma Separated Values) text.

**YOUR INSTRUCTIONS:**
1.  Generate the requested number of question/answer pairs.
2.  Format your output as two columns: "Question", "Answer".
3.  Do NOT include a header row.
4.  Each question must be in quotes if it contains a comma.
5.  Each answer must be in quotes.

**EXAMPLE OUTPUT:**
"What is the capital of France?","Paris"
"Who wrote Hamlet?","William Shakespeare"
"What is 2+2?","4"
""",
    "Rubric Comment Generator": """
You are an expert VCE teacher, skilled at writing constructive feedback.
You will be given:
1.  The test questions.
2.  The rubric.
3.  A description of what the student did correctly and incorrectly.

**YOUR TASK:**
Generate a concise, constructive comment (1-2 paragraphs) for a student report.
-   Start with what the student did well, referencing the rubric.
-   Clearly explain what they missed or misunderstood, referencing the questions.
-   Provide a clear, actionable "next step" for improvement.
-   Maintain a professional and encouraging tone.
"""
}

# --- (5) THIS IS THE MAIN FUNCTION THAT RUNS THE APP ---
def main():
    """Main function to run the Streamlit app."""
    
    st.set_page_config(page_title="VCE AI Teacher Toolkit", layout="wide")

    # --- (A) SESSION STATE INITIALIZATION ---
    if "api_key" not in st.session_state:
        st.session_state.api_key = None
    if "gems" not in st.session_state:
        st.session_state.gems = load_gems("gems.json", DEFAULT_GEMS)
        
        # Migration Check: Add missing default Gems
        migrated = False
        for gem_name, gem_prompt in DEFAULT_GEMS.items():
            if gem_name not in st.session_state.gems:
                st.session_state.gems[gem_name] = gem_prompt
                migrated = True
        if migrated:
            save_to_file("gems.json", st.session_state.gems)

    # --- (B) UI: SIDEBAR ---
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

    # --- (C) UI: MAIN PAGE (TABS) ---
    st.title("VCE Resource Generators")
    
    tab_test, tab_ppt, tab_gimkit, tab_comment, tab_gems = st.tabs([
        "Test Generator (.docx)", 
        "PPT Generator (.pptx)", 
        "Gimkit Generator (.csv)", 
        "Comment Generator", 
        "Gem Creator"
    ])

    # --- TAB 1: TEST GENERATOR ---
    with tab_test:
        st.header("Test Generator (.docx)")
        gem_name = "Test Generator (.docx)"
        
        with st.expander("View/Edit Gem Prompt"):
            st.session_state.gems[gem_name] = st.text_area(
                "Prompt for Test Generator:",
                value=st.session_state.gems.get(gem_name),
                height=300,
                key="gem_test"
            )
        
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_input("Topic for the test:", "e.g., The Atkinson-Shiffrin Model")
            num_questions = st.number_input("Number of questions:", min_value=1, max_value=20, value=5)
        with col2:
            test_format = st.text_area(
                "Paste your test format here:",
                value="e.g., Question 1: Multiple Choice (2 marks)\nQuestion 2: Short Answer (4 marks)\n...",
                height=150
            )

        if st.button("Generate Test"):
            if not topic or not test_format:
                st.warning("Please fill in all fields.")
            else:
                user_prompt = f"Topic: {topic}\nNumber of Questions: {num_questions}\nTest Format:\n{test_format}"
                with st.spinner("Generating test and answer key..."):
                    response = call_gemini_api(
                        st.session_state.gems[gem_name],
                        user_prompt,
                        st.session_state.temperature,
                        st.session_state.model_name
                    )
                
                if response:
                    st.success("Test generated!")
                    from docx import Document
                    
                    # Create a Word doc in memory
                    doc = Document()
                    doc.add_heading(f"{topic} - Test", 0)
                    doc.add_paragraph(response)
                    
                    # Save to a memory buffer
                    bio = io.BytesIO()
                    doc.save(bio)
                    
                    st.download_button(
                        label="Download Test as .docx",
                        data=bio.getvalue(),
                        file_name=f"{topic.replace(' ', '_')}_test.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )

    # --- TAB 2: POWERPOINT GENERATOR ---
    with tab_ppt:
        st.header("PowerPoint Generator (.pptx)")
        gem_name = "PowerPoint Generator (.pptx)"
        
        with st.expander("View/Edit Gem Prompt"):
            st.session_state.gems[gem_name] = st.text_area(
                "Prompt for PPT Generator:",
                value=st.session_state.gems.get(gem_name),
                height=300,
                key="gem_ppt"
            )

        uploaded_file = st.file_uploader("Upload your textbook (PDF)", type="pdf")
        
        if st.button("Generate PowerPoint"):
            if not uploaded_file:
                st.warning("Please upload a PDF file.")
            else:
                with st.spinner(f"Reading {uploaded_file.name}..."):
                    try:
                        with pdfplumber.open(uploaded_file) as pdf:
                            text_content = ""
                            for page in pdf.pages:
                                text_content += page.extract_text() + "\n"
                    except Exception as e:
                        st.error(f"Failed to read PDF. Error: {e}")
                        text_content = None

                if text_content:
                    with st.spinner("Calling Gemini to generate slide content (this may take a moment)..."):
                        response = call_gemini_api(
                            st.session_state.gems[gem_name],
                            text_content,
                            st.session_state.temperature,
                            st.session_state.model_name
                        )
                    
                    if response:
                        try:
                            # Clean the response from markdown backticks
                            response_clean = re.sub(r'```json\n(.*?)\n```', r'\1', response, flags=re.DOTALL)
                            slide_data = json.loads(response_clean)
                            
                            from pptx import Presentation
                            
                            prs = Presentation()
                            
                            for slide_info in slide_data.get("slides", []):
                                slide_layout = prs.slide_layouts[1] # 1 is "Title and Content"
                                slide = prs.slides.add_slide(slide_layout)
                                slide.shapes.title.text = slide_info.get("title", "No Title")
                                
                                content_frame = slide.placeholders[1].text_frame
                                for body_item in slide_info.get("body", []):
                                    p = content_frame.add_paragraph()
                                    p.text = body_item
                                    p.level = 0
                            
                            # Save to a memory buffer
                            bio = io.BytesIO()
                            prs.save(bio)
                            
                            st.success("PowerPoint generated!")
                            st.download_button(
                                label="Download PowerPoint as .pptx",
                                data=bio.getvalue(),
                                file_name=f"{uploaded_file.name}_presentation.pptx",
                                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation"
                            )
                        
                        except json.JSONDecodeError:
                            st.error("AI returned invalid JSON. Could not create .pptx.")
                            st.text_area("Raw AI Output:", value=response, height=200)
                        except Exception as e:
                            st.error(f"Failed to create .pptx file. Error: {e}")
                            st.text_area("Raw AI Output:", value=response, height=200)

    # --- TAB 3: GIMKIT GENERATOR ---
    with tab_gimkit:
        st.header("Gimkit Generator (.csv)")
        gem_name = "Gimkit Generator (.csv)"
        
        with st.expander("View/Edit Gem Prompt"):
            st.session_state.gems[gem_name] = st.text_area(
                "Prompt for Gimkit Generator:",
                value=st.session_state.gems.get(gem_name),
                height=300,
                key="gem_gimkit"
            )
        
        topic_gimkit = st.text_input("Topic for questions:", "e.g., VCE Research Methods")
        num_gimkit = st.number_input("Number of questions:", min_value=5, max_value=50, value=15)
        
        if st.button("Generate Gimkit CSV"):
            if not topic_gimkit:
                st.warning("Please enter a topic.")
            else:
                user_prompt = f"Topic: {topic_gimkit}\nNumber of Questions: {num_gimkit}"
                with st.spinner("Generating questions..."):
                    response = call_gemini_api(
                        st.session_state.gems[gem_name],
                        user_prompt,
                        st.session_state.temperature,
                        st.session_state.model_name
                    )
                
                if response:
                    st.success("CSV content generated!")
                    
                    # Clean the response from markdown backticks
                    response_clean = re.sub(r'```csv\n(.*?)\n```', r'\1', response, flags=re.DOTALL)
                    
                    st.download_button(
                        label="Download Gimkit CSV",
                        data=response_clean.encode('utf-8'), # Encode to bytes
                        file_name=f"{topic_gimkit.replace(' ', '_')}_gimkit.csv",
                        mime="text/csv"
                    )
                    with st.expander("Preview raw CSV data"):
                        st.text(response_clean)

    # --- TAB 4: COMMENT GENERATOR ---
    with tab_comment:
        st.header("Rubric Comment Generator")
        gem_name = "Rubric Comment Generator"
        
        with st.expander("View/Edit Gem Prompt"):
            st.session_state.gems[gem_name] = st.text_area(
                "Prompt for Comment Generator:",
                value=st.session_state.gems.get(gem_name),
                height=300,
                key="gem_comment"
            )
        
        col1, col2 = st.columns(2)
        with col1:
            questions = st.text_area("Test Questions:", "e.g., Q1: Define 'IV'.\nQ2: Explain 'extraneous variable'.", height=200)
            rubric = st.text_area("Rubric Criteria:", "e.g., 'A: Clearly defines all terms.'\n'B: Provides accurate examples.'", height=200)
        with col2:
            student_performance = st.text_area(
                "Student's Performance:", 
                "e.g., 'Correctly defined IV in Q1, but confused 'extraneous' with 'confounding' in Q2. Did not provide an example.'", 
                height=410
            )

        if st.button("Generate Comment"):
            if not questions or not rubric or not student_performance:
                st.warning("Please fill in all three fields.")
            else:
                user_prompt = f"TEST QUESTIONS:\n{questions}\n\nRUBRIC:\n{rubric}\n\nSTUDENT PERFORMANCE:\n{student_performance}"
                with st.spinner("Generating comment..."):
                    response = call_gemini_api(
                        st.session_state.gems[gem_name],
                        user_prompt,
                        st.session_state.temperature,
                        st.session_state.model_name
                    )
                
                if response:
                    st.success("Comment generated!")
                    st.text_area("Generated Comment:", value=response, height=200)

    # --- TAB 5: GEM CREATOR (MANAGE GEMS) ---
    with tab_gems:
        st.header("Gem Creator (Manage Prompts)")
        st.write("Here you can create, edit, or delete the system prompts (Gems) used by the other tabs.")

        gem_list = list(st.session_state.gems.keys())
        
        selected_gem_name = st.selectbox("Select a Gem to Edit or Delete", options=[""] + gem_list, key="gem_editor_select")

        if selected_gem_name:
            # Edit/Delete mode
            current_name = selected_gem_name
            current_prompt = st.session_state.gems.get(selected_gem_name, "")
            
            gem_name = st.text_input("Gem Name", value=current_name)
            gem_prompt = st.text_area("Gem Prompt", value=current_prompt, height=300)
            
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("Update Gem"):
                    if current_name != gem_name: 
                        if gem_name in st.session_state.gems:
                            st.error("A Gem with that new name already exists.")
                        else:
                            del st.session_state.gems[current_name]
                            st.session_state.gems[gem_name] = gem_prompt
                            save_to_file("gems.json", st.session_state.gems)
                            st.success(f"Updated '{gem_name}'!")
                            st.rerun()
                    else:
                        st.session_state.gems[gem_name] = gem_prompt
                        save_to_file("gems.json", st.session_state.gems)
                        st.success(f"Updated '{gem_name}'!")
                        st.rerun()
            with col2:
                if st.button("Delete Gem", type="primary"):
                    if current_name == "Blank Chat Prompt":
                        st.error("Cannot delete the default 'Blank Chat Prompt'.")
                    else:
                        del st.session_state.gems[current_name]
                        save_to_file("gems.json", st.session_state.gems)
                        st.success(f"Deleted '{current_name}'!")
                        st.rerun()
            
        else:
            st.subheader("Create a New Gem")
            gem_name = st.text_input("New Gem Name", key="new_gem_name")
            gem_prompt = st.text_area("New Gem Prompt", key="new_gem_prompt", height=300)
            
            if st.button("Save New Gem"):
                if gem_name and gem_prompt:
                    if gem_name in st.session_state.gems:
                        st.error("A Gem with this name already exists.")
                    else:
                        st.session_state.gems[gem_name] = gem_prompt
                        save_to_file("gems.json", st.session_state.gems)
                        st.success(f"Saved new Gem: '{gem_name}'!")
                        st.rerun()
                else:
                    st.warning("Please provide both a name and a prompt.")


# --- (6) THIS BLOCK RUNS THE SCRIPT ---
if __name__ == "__main__":
    main()
