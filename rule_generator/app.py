from flask import Flask, request, jsonify
from openai import OpenAI
import time
import os
from dotenv import load_dotenv

app = Flask(__name__)

# Add debug logging
@app.before_request
def log_request_info():
    app.logger.debug('Headers: %s', request.headers)
    app.logger.debug('Method: %s', request.method)
    app.logger.debug('URL: %s', request.url)

def generate_rule_with_assistant(client: OpenAI, assistant_id: str, query: str) -> str:
    """
    Generate a rule using OpenAI assistant.
    """
    thread = client.beta.threads.create()
    message = client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=query
    )
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant_id
    )
    
    # Wait for completion
    while True:
        run_status = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
        if run_status.status == 'completed':
            break
        time.sleep(1)
    
    # Get response
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    response = messages.data[0].content[0].text.value
    
    # Extract the YAML block from the response
    yaml_block = response.split("```yaml")[1].split("```")[0].strip()
    return yaml_block

@app.route('/generate', methods=['POST'])
def generate():
    app.logger.debug('Received request to /generate')
    # Verify authorization
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Missing or invalid authorization header'}), 401
    
    api_key = auth_header.split(' ')[1]
    
    # Get query from request
    data = request.get_json()
    if not data or 'query' not in data or 'assistant_id' not in data:
        return jsonify({'error': 'Missing query or assistant_id in request body'}), 400
    
    try:
        client = OpenAI(api_key=api_key)
        assistant_id = data['assistant_id']
        
        rule = generate_rule_with_assistant(client, assistant_id, data['query'])
        return jsonify({'rule': rule})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    load_dotenv()
    app.run(host='0.0.0.0', port=5000, debug=True)