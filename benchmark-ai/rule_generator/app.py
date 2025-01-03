from flask import Flask, request, jsonify
from openai import OpenAI
import time
import os
from dotenv import load_dotenv
from functools import wraps
import secrets
import logging
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from secrets import compare_digest

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

def judge_rules_with_assistant(client: OpenAI, assistant_id: str, rule1: str, rule2: str) -> dict:
    """
    Compare two rules using OpenAI assistant and return a judgment.
    """
    # Construct the comparison query
    comparison_data = {
        "rule1": rule1,
        "rule2": rule2
    }
    
    thread = client.beta.threads.create()
    message = client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=f"{comparison_data}"
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
    
    return {"judgment": response}

@app.route('/api/v1/rules', methods=['POST'])
@limiter.limit("10 per minute")  # Rate limiting per endpoint
@require_api_key
def create_rule():
    try:
        # Input validation
        data = request.get_json()
        if not data:
            logger.error("No JSON data in request")
            return jsonify({'error': 'Missing request body'}), 400
            
        required_fields = ['query', 'assistant_id']
        if not all(field in data for field in required_fields):
            logger.error(f"Missing required fields: {required_fields}")
            return jsonify({'error': 'Missing required fields'}), 400
            
        # Validate query length
        if len(data['query']) > 1000:  # Adjust limit as needed
            return jsonify({'error': 'Query too long'}), 400
            
        # Initialize OpenAI client with only the required parameters
        client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url="https://api.openai.com/v1"  # Explicitly set base URL
        )
        
        rule = generate_rule_with_assistant(client, data['assistant_id'], data['query'])
        
        # Sanitize/validate response before returning
        if not rule or len(rule) > 10000:  # Adjust limit as needed
            raise ValueError("Invalid rule generated")
            
        return jsonify({'rule': rule})
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/v1/judge', methods=['POST'])
@limiter.limit("10 per minute")
@require_api_key
def judge_rules():
    try:
        # Input validation
        data = request.get_json()
        if not data:
            logger.error("No JSON data in request")
            return jsonify({'error': 'Missing request body'}), 400
            
        required_fields = ['rule1', 'rule2', 'assistant_id']
        if not all(field in data for field in required_fields):
            logger.error(f"Missing required fields: {required_fields}")
            return jsonify({'error': 'Missing required fields'}), 400
            
        # Validate rules length
        if len(data['rule1']) > 5000 or len(data['rule2']) > 5000:  # Adjust limit as needed
            return jsonify({'error': 'Rules too long'}), 400
            
        client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url="https://api.openai.com/v1"
        )
        
        judgment = judge_rules_with_assistant(
            client, 
            data['assistant_id'], 
            data['rule1'], 
            data['rule2']
        )
        
        return jsonify(judgment)
        
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