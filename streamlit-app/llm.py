import os
from openai import OpenAI
from tenacity import retry, wait_exponential, stop_after_attempt
import time
import weave

weave.init("sigmaiq-streamlit")

# Load assistant instructions from external file
INSTRUCTIONS_FILE = os.path.join(os.path.dirname(__file__), "instructions.txt")
INSTRUCTIONS = open(INSTRUCTIONS_FILE, "r").read()

@weave.op() # 🐝
def update_assistant(client, assistant_id, new_instructions):
    """
    Updates an OpenAI assistant with new instructions
    Args:
        client: OpenAI client instance
        assistant_id: ID of the assistant to update
        new_instructions: New instructions text to update the assistant with
    Returns:
        Updated assistant object
    """
    try:
        updated_assistant = client.beta.assistants.update(
            assistant_id=assistant_id,
            instructions=new_instructions,
        )
        print("Successfully updated assistant instructions")
        return updated_assistant
    except Exception as e:
        print(f"Error updating assistant: {str(e)}")
        raise

@weave.op() # 🐝
def init_client_and_assistant(config):
    """
    Initializes OpenAI client and retrieves/updates the assistant
    Args:
        config: Dictionary containing OPENAI_API_KEY and ASSISTANT_ID
    Returns:
        Tuple of (OpenAI client, updated assistant)
    """
    client = OpenAI(api_key=config["OPENAI_API_KEY"])
    assistant = client.beta.assistants.retrieve(config["ASSISTANT_ID"])
    assistant = update_assistant(
        client=client,
        assistant_id=assistant.id,
        new_instructions=INSTRUCTIONS,
    )
    return client, assistant

@weave.op() # 🐝
@retry(wait=wait_exponential(min=1, max=60), stop=stop_after_attempt(5))
def generate_answer(client, query, assistant):
    """
    Generates an answer using the OpenAI assistant
    Args:
        client: OpenAI client instance
        query: User's input question
        assistant: OpenAI assistant instance
    Returns:
        Tuple of (response text, list of referenced files)
    Raises:
        Exception: If the run fails or expires
    """
    # Initialize a new thread for the conversation
    thread = client.beta.threads.create()
    
    # Add the user's query to the thread
    client.beta.threads.messages.create(thread_id=thread.id, role="user", content=query)
    
    # Start the assistant's response generation
    run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=assistant.id)
    
    # Poll until the run is complete
    while True:
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        if run.status == "completed":
            break
        elif run.status in ["failed", "cancelled", "expired"]:
            raise Exception(f"Run failed with status: {run.status}")
        time.sleep(1)
    
    # Get the assistant's response
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    last_message = messages.data[0]  # Get the most recent message
    
    # Process any file citations in the response
    referenced_files = set()
    print(f"Message content types: {[content.type for content in last_message.content]}")
    for content in last_message.content:
        # Process text content for file citations
        if content.type == "text":
            print(f"Found text content: {content.text}")
            print(f"Has annotations attribute: {hasattr(content.text, 'annotations')}")
            if hasattr(content.text, "annotations"):
                print(f"Annotations: {content.text.annotations}")
                for annotation in content.text.annotations:
                    print(f"Annotation type: {annotation.type}")
                    if annotation.type == "file_citation":
                        try:
                            # Retrieve and store referenced file information
                            file_info = client.files.retrieve(annotation.file_citation.file_id)
                            referenced_files.add(file_info.filename)
                            print(f"Added file: {file_info.filename}")
                        except Exception as e:
                            print(f"Error retrieving file citation: {str(e)}")
    
    return last_message.content[0].text.value, list(referenced_files)