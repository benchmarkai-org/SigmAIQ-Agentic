import os
import glob
import time
import difflib
import json
import weave
from openai import OpenAI
import yaml
from tenacity import retry, wait_exponential, stop_after_attempt
from io import StringIO, BytesIO

instructions="""You are a cybersecurity detection engineering assistant bot specializing in Sigma Rule creation.
You are assisting a user in creating a new Sigma Rule based on the users question.  
The user's question is first used to find similar Sigma Rules from the the knowledge base which contains official 
Sigma Rules. The official Sigma Rules can be used as context as needed in conjunction with the detection specified
in the users question to create a new Sigma Rule.  
The created Sigma Rule should be in YAML format and use the official Sigma schema.  The detection field
can contain multiple 'selection' identifiers and multiple 'filter' identifiers as needed, 
which can be used in the condition field to select criteria and filter out criteria respectively.
Set the 'author' to 'SigmAIQ (AttackIQ)', the date to today's date, and the reference to 'https://github.com/AttackIQ/SigmAIQ'.
If you use other rules as context and derive the created Sigma Rules from the context rules, you must
include the original authors under the 'author' field in the new rule in addition to "SigmAIQ (AttackIQ),
and add the original rule IDs under the 'related' field. The valid 'types' under 'related' are the following:

    derived: The rule was derived from the referred rule or rules, which may remain active.
    obsoletes: The rule obsoletes the referred rule or rules, which aren't used anymore.
    merged: The rule was merged from the referred rules. The rules may be still existing and in use.
    renamed: The rule had previously the referred identifier or identifiers but was renamed for whatever reason, e.g. from a private naming scheme to UUIDs, to resolve collisions etc. It's not expected that a rule with this id exists anymore.
    similar: Use to relate similar rules to each other (e.g. same detection content applied to different log sources, rule that is a modified version of another rule with a different level)

If you are unsure about the Sigma rule schema, you can get the information from the official
Sigma specification here first: https://raw.githubusercontent.com/SigmaHQ/sigma-specification/main/Sigma_specification.md

------------

Sigma Rule Schema:

title
id [optional]
related [optional]
   - id {{rule-id}}
     type {{type-identifier}}
status [optional]
description [optional]
references [optional]
author [optional]
date [optional]
modified [optional]
tags [optional]
logsource
   category [optional]
   product [optional]
   service [optional]
   definition [optional]
   ...
detection
   {{search-identifier}} [optional]
      {{string-list}} [optional]
      {{map-list}} [optional]
      {{field: value}}> [optional]
   ... # Multiple search identifiers can be specified as needed and used in the condition
   condition
fields [optional]
falsepositives [optional]
level [optional]:"""

# Initialize the client properly
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Initialize Weave
weave.init(project_name="YAML_RAG_Project")

def cleanup_openai_files():
    """Delete all files from OpenAI storage."""
    try:
        # List all files
        files = client.files.list()
        
        # Delete each file
        for file in files.data:
            try:
                print(f"Deleting file: {file.filename} (ID: {file.id})")
                client.files.delete(file.id)
            except Exception as e:
                print(f"Error deleting file {file.filename}: {str(e)}")
        
        print("Finished cleaning up files")
        
    except Exception as e:
        print(f"Error listing files: {str(e)}")

def upload_yml_documents(directory_path, assistant_id):
    # Create a vector store called "Sigma Rules"
    vector_store = client.beta.vector_stores.create(name="Sigma Rules")
    file_ids = []
    
    # Now upload new files to the vector store
    yaml_files = glob.glob(os.path.join(directory_path, '**/*.yml'), recursive=True)
    
    for path in yaml_files:
        try:
            with open(path, 'rb') as file:
                # Convert YAML to JSON
                yaml_content = yaml.safe_load(file)
                json_content = json.dumps(yaml_content, indent=2)
                
                # Create a JSON file with a unique name
                json_filename = os.path.splitext(os.path.basename(path))[0] + '.json'
                file_like = BytesIO(json_content.encode('utf-8'))
                file_like.name = json_filename
                
                # Upload to OpenAI and add to vector store
                file_response = client.files.create(
                    file=file_like,
                    purpose='assistants'
                )
                
                # Add file to vector store
                client.beta.vector_stores.files.create_and_poll(
                    vector_store_id=vector_store.id,
                    file_id=file_response.id
                )   
                
                file_ids.append(file_response.id)
                print(f"Uploaded and vectorized: {json_filename}")
                
                # Cleanup
                file_like.close()
                del file_like
                
        except Exception as e:
            print(f"Error processing {path}: {str(e)}")
            continue
    
    # Associate the vector store with the assistant
    client.beta.assistants.update(
        assistant_id=assistant_id,
        tools=[{
            "type": "file_search",
            "vector_store_id": vector_store.id
        }]
    )
    
    print(f"Associated vector store with assistant")
    return vector_store.id


# Step 1: Create an assistant with the file_search tool and upload files (as needed)
@weave.op()
def get_or_create_assistant(root_directory, force_upload_files=True):
    # Get from environment variable
    ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID', '')  # Empty string if not found
    
    try:
        if ASSISTANT_ID:  # Only try to retrieve if we have an ID
            assistant = client.beta.assistants.retrieve(ASSISTANT_ID)
            print("Using existing assistant")
            if force_upload_files:
                print("Uploading and attaching YAML documents...")
                file_ids = upload_yml_documents(root_directory, assistant.id)
                print(f"Uploaded and attached {len(file_ids)} files")
            return assistant
    except:
        print(f"Assistant {ASSISTANT_ID} not found or invalid, creating new assistant...")
    
    # Create new assistant (either because ID wasn't found or no ID provided)
    assistant = client.beta.assistants.create(
        name="YAMLDocumentAssistant",
        model="gpt-4o",
        instructions=instructions,
        tools=[{"type": "file_search"}]
    )
    print(f"Created new assistant with OPENAI_ASSISTANT_ID={assistant.id}")
    print("Please save this ID in your environment variables as OPENAI_ASSISTANT_ID")
    
    # Upload and attach files for new assistant
    print("Uploading and attaching YAML documents...")
    file_ids = upload_yml_documents(root_directory, assistant.id)
    print(f"Uploaded and attached {len(file_ids)} files")
    
    return assistant

# Define the root directory path where YAML files are stored
root_directory = "./sigmaiq/llm/data/sigma/rules/"
# Force file upload even if assistant exists (useful for updating files)
assistant = get_or_create_assistant(root_directory, force_upload_files=False)



def update_assistant(assistant_id, new_instructions):
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

# Call this each time in case the instructions need to be updated
assistant = update_assistant(
    assistant_id=assistant.id,
    new_instructions=instructions,
)

# Step 2: Process a user query
@retry(wait=wait_exponential(min=1, max=60), stop=stop_after_attempt(5))
@weave.op()
def generate_answer(query, assistant):
    # Create an empty thread first
    thread = client.beta.threads.create()

    # Add the message to the thread
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=query
    )

    # Create and run the thread
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id
    )

    while True:
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
        if run.status == 'completed':
            break
        elif run.status in ['failed', 'cancelled', 'expired']:
            raise Exception(f"Run failed with status: {run.status}")
        time.sleep(1)

    # Retrieve messages
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    last_message = messages.data[0]  # Get the most recent message

    # Extract file citations if any
    referenced_files = set()
    print(f"Message content types: {[content.type for content in last_message.content]}")
    
    for content in last_message.content:
        # Check if content is text type
        if content.type == 'text':
            print(f"Found text content: {content.text}")
            # Check if annotations exist
            print(f"Has annotations attribute: {hasattr(content.text, 'annotations')}")
            if hasattr(content.text, 'annotations'):
                print(f"Annotations: {content.text.annotations}")
                for annotation in content.text.annotations:
                    print(f"Annotation type: {annotation.type}")
                    if annotation.type == 'file_citation':
                        try:
                            file_info = client.files.retrieve(annotation.file_citation.file_id)
                            referenced_files.add(file_info.filename)
                            print(f"Added file: {file_info.filename}")
                        except Exception as e:
                            print(f"Error retrieving file citation: {str(e)}")

    return last_message.content[0].text.value, list(referenced_files)

# Example usage
query = "Write a Sigma Rule that detects use of the powershell command with special characters."
answer, referenced_files = generate_answer(query, assistant)

print("Answer:", answer)
print("Referenced Files:", referenced_files)

def cleanup_openai_files():
    """Delete all files from OpenAI storage."""
    try:
        # List all files
        files = client.files.list()
        
        # Delete each file
        for file in files.data:
            try:
                print(f"Deleting file: {file.filename} (ID: {file.id})")
                client.files.delete(file.id)
            except Exception as e:
                print(f"Error deleting file {file.filename}: {str(e)}")
        
        print("Finished cleaning up files")
        
    except Exception as e:
        print(f"Error listing files: {str(e)}")