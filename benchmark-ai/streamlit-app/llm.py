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
    
    # Get the initial response
    initial_messages = client.beta.threads.messages.list(thread_id=thread.id)
    initial_response = initial_messages.data[0].content[0].text.value
    
    # Add reflection prompt that explicitly references the initial response
    reflection_prompt = f"""Here is the initial Sigma rule response:

{initial_response}

Please review this response considering the following aspects:

1. Detection Logic Validation
- Have I correctly translated the user's detection intent into Sigma syntax?
- Are the selected field names valid for the specified log source?
- Could this detection generate false positives? If so, have I added appropriate filters?
- Does the condition logic accurately combine selections and filters?
- Have I considered common evasion techniques that might bypass this detection?

2. Log Source Assessment
- Is the logsource configuration specific enough?
- Have I specified all required fields (category, product, service)?
- Will this rule work across different log formats for the specified source?

3. Context Integration
- If I used existing rules as reference:
  * Have I properly credited original authors?
  * Have I correctly specified related rule IDs?
  * Is the relationship type (derived, similar, etc.) accurate?
  * Have I improved upon or differentiated from existing rules?

4. Rule Metadata Completeness
- Is the title clear and descriptive?
- Does the description explain the detection's purpose and potential threats?
- Are all relevant tags included for proper categorization?
- Have I specified an appropriate severity level?
- Are false positive scenarios documented?
- Have I included relevant references?

5. Technical Coverage
- Does this rule cover all relevant variations of the attack/behavior?
- Have I considered different OS platforms if applicable?
- Are there edge cases I should address?

Based on this analysis:
1. What improvements are needed to the above rule?
2. What additional context or filters would make it more accurate?
3. How can we reduce false positives while maintaining effectiveness?

Please provide your response in the following format:
1. Analysis of the initial rule
2. The improved Sigma rule in a code block
3. Explanation of improvements made"""

    # Add reflection prompt to thread
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=reflection_prompt
    )
    
    # Run reflection analysis
    reflection_run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id
    )
    
    # Poll until reflection run is complete
    while True:
        reflection_run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=reflection_run.id
        )
        if reflection_run.status == "completed":
            break
        elif reflection_run.status in ["failed", "cancelled", "expired"]:
            raise Exception(f"Reflection run failed with status: {reflection_run.status}")
        time.sleep(1)
    
    # Get both responses
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    reflection_response = messages.data[0].content[0].text.value
    
    # Process file citations
    referenced_files = set()
    print(f"Message content types: {[content.type for content in reflection_response]}")
    for content in reflection_response:
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
    
    # Format the response to include both rules
    formatted_response = f"""
### Original Sigma Rule:
{initial_response}

### Improved Sigma Rule:
{reflection_response}

### Explanation:
1. Analysis of the initial rule
2. The improved Sigma rule in a code block
3. Explanation of improvements made"""
    
    return formatted_response, list(referenced_files)