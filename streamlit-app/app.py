# Import required libraries
import streamlit as st
import re
from llm import init_client_and_assistant, generate_answer

def load_config():
    """
    Load configuration settings from Streamlit secrets.
    
    Returns:
        dict: Configuration dictionary containing:
            - OPENAI_API_KEY: API key for OpenAI authentication
            - ASSISTANT_ID: ID of the OpenAI assistant to use
    """
    return {"OPENAI_API_KEY": st.secrets["OPENAI_API_KEY"], "ASSISTANT_ID": st.secrets["ASSISTANT_ID"]}

def process_answer_sections(text):
    """
    Process AI response text into separate code and text sections while maintaining order.
    
    Args:
        text (str): Raw text response from the AI assistant containing
                   markdown-formatted code blocks and regular text.
    
    Returns:
        list: List of tuples, each containing:
            - section_type (str): Either 'code' or 'text'
            - language (str|None): Programming language for code blocks, None for text
            - content (str): The actual content of the section
    """
    # Regular expression to match code blocks with optional language specification
    pattern = r"(```(?:yaml|python|json|\w+)?\n.*?```)"
    
    # Split text into code and non-code sections while preserving order
    parts = re.split(pattern, text, flags=re.DOTALL)
    sections = []
    
    for part in parts:
        if part.strip():
            # Check if this part is a code block
            code_block_match = re.match(r"```(\w+)?\n(.*?)```", part, re.DOTALL)
            if code_block_match:
                # Extract language and content from code block
                language = code_block_match.group(1) or "text"
                content = code_block_match.group(2)
                sections.append(("code", language, content))
            else:
                # Handle regular text sections
                sections.append(("text", None, part.strip()))
    return sections

def run():
    """
    Main application function that sets up the Streamlit UI and handles user interactions.
    
    This function:
    1. Initializes the OpenAI client and assistant
    2. Creates the web interface elements
    3. Handles user input and rule generation
    4. Displays the generated results
    5. Manages error cases and user feedback
    
    No parameters or return values as it's the main app runner.
    """
    # Initialize OpenAI client and assistant if not already in session state
    if "client" not in st.session_state:
        config = load_config()
        st.session_state.client, st.session_state.assistant = init_client_and_assistant(config)

    # Set up the main UI elements
    st.title("Sigma Rule Generator")
    st.write("Enter your query to generate a Sigma rule.")
    query = st.text_area("Query", height=100, placeholder="Write a Sigma Rule that detects...")

    # Handle rule generation when button is clicked
    if st.button("Generate Rule"):
        if query:
            with st.spinner("Generating Sigma rule..."):
                try:
                    # Generate the rule using the AI assistant
                    answer, referenced_files = generate_answer(
                        st.session_state.client, query, st.session_state.assistant
                    )
                    
                    # Process and display the response sections
                    sections = process_answer_sections(answer)
                    for section_type, language, content in sections:
                        if section_type == "code":
                            # Display code blocks with syntax highlighting
                            st.code(content, language=language)
                        else:
                            # Display regular text as markdown
                            st.markdown(content)
                            
                    # Show any referenced files used in generation
                    if referenced_files:
                        st.write("Referenced files:", ", ".join(referenced_files))
                        
                except Exception as e:
                    st.error(f"Error generating rule: {str(e)}")
        else:
            st.warning("Please enter a query first.")

# Entry point of the application
if __name__ == "__main__":
    run()