from flask import Flask, request, jsonify
from openai import OpenAI
import time
import os
from dotenv import load_dotenv
from functools import wraps
import logging
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from secrets import compare_digest
from pathlib import Path

app = Flask(__name__)
# Configure CORS with strict settings
CORS(app, resources={r"/api/*": {"origins": os.getenv("ALLOWED_ORIGINS", "").split(",")}})

# Configure rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per day", "10 per minute"]
)

# Enhanced logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add environment variable for service API key
SERVICE_API_KEY = os.getenv('SERVICE_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Secure headers middleware
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            logger.warning("Unauthorized access attempt")
            return jsonify({'error': 'Missing or invalid authorization header'}), 401
        
        api_key = auth_header.split(' ')[1]
        # Use secure comparison to prevent timing attacks
        if not compare_digest(api_key, SERVICE_API_KEY):
            logger.warning("Invalid API key")
            return jsonify({'error': 'Invalid API key'}), 401
            
        return f(*args, **kwargs)
    return decorated

def wait_for_assistant_completion(client: OpenAI, thread_id: str, run_id: str) -> None:
    """
    Wait for an assistant run to complete.
    """
    while True:
        run_status = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run_id
        )
        if run_status.status == 'completed':
            break
        time.sleep(1)

def get_assistant_response(client: OpenAI, assistant_id: str, prompt: str) -> str:
    """
    Get a response from an OpenAI assistant.
    """
    thread = client.beta.threads.create()
    
    # Send message
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=prompt
    )
    
    # Create and wait for run
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant_id
    )
    
    wait_for_assistant_completion(client, thread.id, run.id)
    
    # Get response
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    return messages.data[0].content[0].text.value

def create_openai_client() -> OpenAI:
    """
    Create an OpenAI client with standard configuration.
    """
    return OpenAI(
        api_key=OPENAI_API_KEY,
        base_url="https://api.openai.com/v1"
    )

@app.route('/api/v1/rules', methods=['POST'])
@limiter.limit("10 per minute")
@require_api_key
def create_rule():
    try:
        data = request.get_json()
        if not data:
            logger.error("No JSON data in request")
            return jsonify({'error': 'Missing request body'}), 400
            
        required_fields = ['query', 'assistant_id']
        if not all(field in data for field in required_fields):
            logger.error(f"Missing required fields: {required_fields}")
            return jsonify({'error': 'Missing required fields'}), 400
            
        if len(data['query']) > 1000:
            return jsonify({'error': 'Query too long'}), 400
            
        client = create_openai_client()
        response = get_assistant_response(client, data['assistant_id'], data['query'])
        
        # Extract YAML block
        yaml_block = response.split("```yaml")[1].split("```")[0].strip()
        if not yaml_block or len(yaml_block) > 10000:
            raise ValueError("Invalid rule generated")
            
        return jsonify({'rule': yaml_block})
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/v1/judge', methods=['POST'])
@limiter.limit("10 per minute")
@require_api_key
def judge_rules():
    try:
        data = request.get_json()
        if not data:
            logger.error("No JSON data in request")
            return jsonify({'error': 'Missing request body'}), 400
            
        required_fields = ['rule1', 'rule2', 'assistant_id']
        if not all(field in data for field in required_fields):
            logger.error(f"Missing required fields: {required_fields}")
            return jsonify({'error': 'Missing required fields'}), 400
            
        if len(data['rule1']) > 5000 or len(data['rule2']) > 5000:
            return jsonify({'error': 'Rules too long'}), 400
            
        client = create_openai_client()
        judgment = get_assistant_response(
            client,
            data['assistant_id'],
            f"Compare these rules:\nRule 1:\n{data['rule1']}\nRule 2:\n{data['rule2']}"
        )
        
        return jsonify({"judgment": judgment})
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/v1/assess', methods=['POST'])
@limiter.limit("10 per minute")
@require_api_key
def assess_rule():
    try:
        data = request.get_json()
        if not data:
            logger.error("No JSON data in request")
            return jsonify({'error': 'Missing request body'}), 400
            
        required_fields = ['rule', 'assistant_id']
        if not all(field in data for field in required_fields):
            logger.error(f"Missing required fields: {required_fields}")
            return jsonify({'error': 'Missing required fields'}), 400
            
        if len(data['rule']) > 5000:
            return jsonify({'error': 'Rule too long'}), 400
            
        client = create_openai_client()
        assessment = get_assistant_response(
            client,
            data['assistant_id'],
            f"Please assess this Sigma rule:\n{data['rule']}"
        )
        
        return jsonify({"assessment": assessment})
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/v1/summarize-references', methods=['POST'])
@limiter.limit("5 per minute")
@require_api_key
def summarize_references():
    try:
        data = request.get_json()
        if not data:
            logger.error("No JSON data in request")
            return jsonify({'error': 'Missing request body'}), 400
            
        required_fields = ['reference_content', 'assistant_id']
        if not all(field in data for field in required_fields):
            logger.error(f"Missing required fields: {required_fields}")
            return jsonify({'error': 'Missing required fields'}), 400
            
        client = create_openai_client()
        summary = get_assistant_response(
            client,
            data['assistant_id'],
            f"Please summarize this reference content:\n\n{data['reference_content']}"
        )
        
        return jsonify({'summary': summary})
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/v1/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    load_dotenv()
    # Only enable debug mode in development
    debug_mode = os.getenv('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=5000, debug=debug_mode, ssl_context='adhoc')