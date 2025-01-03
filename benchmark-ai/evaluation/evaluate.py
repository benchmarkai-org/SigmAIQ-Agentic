import json
import yaml
import logging 
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from langchain.evaluation import load_evaluator
from dotenv import load_dotenv
import os
import time
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_test_cases(test_file: str) -> List[Dict]:
    """
    Load test cases from a JSON file containing query-rule pairs.
    
    Expected format:
    [
        {
            "query": "Write a rule to detect...",
            "expected_rule": "title: Expected Rule\ndetection:..."
        },
        ...
    ]
    """
    with open(test_file, 'r') as f:
        return json.load(f)

def get_judge_comparison(rule1: str, rule2: str, config: Dict) -> Dict:
    """
    Get a judgment comparison between two rules using the judge endpoint.
    """
    try:
        base_url = config['RULE_GENERATOR_URL'].rstrip('/')
        
        response = requests.post(
            f"{base_url}/api/v1/judge",
            json={
                "rule1": rule1,
                "rule2": rule2,
                "assistant_id": config['JUDGE_ASSISTANT_ID']  # Note: needs new config value
            },
            headers={
                "Authorization": f"Bearer {config['SERVICE_API_KEY']}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            verify=False,  # Disable SSL verification
            timeout=300
        )
        response.raise_for_status()
        return response.json()["judgment"]
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Judge request failed: {str(e)}")
        raise Exception(f"Failed to get judgment: {str(e)}")


def evaluate_rule(generated_rule: str, expected_rule: str) -> Tuple[Dict, float]:
    """
    Evaluate a generated rule against the expected rule using multiple criteria.
    
    Returns:
        Tuple[Dict, float]: (detailed_metrics, overall_score)
    """
    # Parse YAML strings to dictionaries
    try:
        generated = yaml.safe_load(generated_rule)
        expected = yaml.safe_load(expected_rule)
        
        # Initialize metrics
        metrics = {
            "valid_yaml": 1.0,
            "has_required_fields": 0.0,
            "detection_logic_similarity": 0.0,
            "metadata_completeness": 0.0
        }
        
        # Check required fields
        required_fields = ["title", "detection", "logsource"]
        fields_present = sum(1 for field in required_fields if field in generated) / len(required_fields)
        metrics["has_required_fields"] = fields_present
        
        # Use LangChain evaluator for detection logic similarity
        try:
            evaluator = load_evaluator("string_distance")
            print(f"Debug - Generated detection: {str(generated.get('detection', {}))}")
            print(f"Debug - Expected detection: {str(expected.get('detection', {}))}")
            
            evaluation_result = evaluator.evaluate_strings(
                prediction=str(generated.get("detection", {})),
                reference=str(expected.get("detection", {}))
            )
            print(f"Debug - Evaluation result: {evaluation_result}")  # Added to see full result structure
            detection_similarity = evaluation_result["score"]  # Changed from .score to ["score"]
            metrics["detection_logic_similarity"] = detection_similarity
        except Exception as e:
            print(f"Error during string distance evaluation: {str(e)}")
            print(f"Error type: {type(e)}")
            metrics["detection_logic_similarity"] = 0.0
        
        # Calculate metadata completeness
        metadata_fields = ["description", "author", "date", "level", "tags"]
        metadata_score = sum(1 for field in metadata_fields if field in generated) / len(metadata_fields)
        metrics["metadata_completeness"] = metadata_score
        
        # Calculate overall score (weighted average)
        weights = {
            "valid_yaml": 0.2,
            "has_required_fields": 0.3,
            "detection_logic_similarity": 0.4,
            "metadata_completeness": 0.1
        }
        overall_score = sum(metrics[k] * weights[k] for k in metrics)
        
        return metrics, overall_score
        
    except yaml.YAMLError:
        return {"valid_yaml": 0.0, "has_required_fields": 0.0,
                "detection_logic_similarity": 0.0, "metadata_completeness": 0.0}, 0.0

def generate_rule(query: str, config: Dict) -> str:
    """
    Generate a rule by calling the rule generation microservice.
    """
    try:
        base_url = config['RULE_GENERATOR_URL'].rstrip('/')
        
        response = requests.post(
            f"{base_url}/api/v1/rules",
            json={
                "query": query,
                "assistant_id": config['OPENAI_ASSISTANT_ID']
            },
            headers={
                "Authorization": f"Bearer {config['SERVICE_API_KEY']}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            verify=False,  # Disable SSL verification
            timeout=30
        )
        
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            logger.info(f"Rate limit exceeded. Waiting {retry_after} seconds...")
            time.sleep(retry_after)
            return generate_rule(query, config)
            
        response.raise_for_status()
        return response.json()["rule"]
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            if e.response.status_code == 401:
                raise Exception("Authentication failed. Check your SERVICE_API_KEY.")
            elif e.response.status_code == 400:
                raise Exception(f"Bad request: {e.response.json().get('error', 'Unknown error')}")
        raise Exception(f"Failed to generate rule: {str(e)}")

def evaluate_rule(generated_rule: str, expected_rule: str, config: Dict) -> tuple:
    """
    Evaluate a generated rule against the expected rule.
    Now includes LLM judgment in the evaluation metrics.
    """
    try:
        # Get LLM judgment
        judgment = get_judge_comparison(generated_rule, expected_rule, config)
        
        # Your existing metrics calculation here...
        metrics = {
            "llm_judgment": judgment,
            # ... other metrics ...
        }
        
        # Calculate overall score (you might want to incorporate the LLM judgment 
        # into your scoring mechanism)
        score = calculate_score(metrics)
        
        return metrics, score
        
    except Exception as e:
        logger.error(f"Evaluation failed: {str(e)}")
        raise

def evaluate_rule_with_llm(expected_rule: str, generated_rule: str, config: Dict) -> Optional[Dict]:
    """
    Use an LLM to evaluate the generated rule against the expected rule.
    """
    try:
        base_url = config['RULE_GENERATOR_URL'].rstrip('/')
        
        response = requests.post(
            f"{base_url}/api/v1/evaluations",
            json={
                "expected_rule": expected_rule,
                "generated_rule": generated_rule,
                "assistant_id": config['OPENAI_JUDGE_ID']
            },
            headers={
                "Authorization": f"Bearer {config['SERVICE_API_KEY']}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            verify=not base_url.startswith('https://localhost'),
            timeout=300
        )
        
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            logger.info(f"Rate limit exceeded. Waiting {retry_after} seconds...")
            time.sleep(retry_after)
            return evaluate_rule_with_llm(expected_rule, generated_rule, config)
            
        response.raise_for_status()
        return response.json()
        
    except requests.exceptions.RequestException as e:
        logger.error(f"LLM evaluation failed: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            if e.response.status_code == 401:
                logger.error("Authentication failed. Check your SERVICE_API_KEY.")
            elif e.response.status_code == 400:
                logger.error(f"Bad request: {e.response.json().get('error', 'Unknown error')}")
        return None

def run_evaluation(config: Dict, test_cases: List[Dict]) -> List[Dict]:
    """
    Run evaluation on all test cases and return results.
    """
    results = []
    use_llm = bool(config.get('OPENAI_JUDGE_ID'))  # Check if judge ID is provided
    total_cases = len(test_cases)
    
    # Validate required config
    required_config = ['RULE_GENERATOR_URL', 'SERVICE_API_KEY', 
                      'OPENAI_ASSISTANT_ID', 'JUDGE_ASSISTANT_ID']
    if not all(key in config for key in required_config):
        raise ValueError(f"Missing required configuration. Need: {required_config}")
    
    logger.info(f"Starting evaluation of {total_cases} test cases...")
    
    for idx, case in enumerate(test_cases, 1):
        try:
            logger.info(f"Processing case {idx}/{total_cases}: {case['query'][:50]}...")
            
            # Generate rule using microservice
            yaml_block = generate_rule(case["query"], config)
            
            # Evaluate the generated rule (includes LLM judgment)
            metrics, score = evaluate_rule(yaml_block, case["expected_rule"], config)
 
            
            results.append({
                "query": case["query"],
                "generated_rule": yaml_block,
                "expected_rule": case["expected_rule"],
                "metrics": metrics,
                "overall_score": score
            })
            
            logger.info(f"Completed case {idx}/{total_cases} with score: {score:.2f}")
            
        except Exception as e:
            logger.error(f"Failed case {idx}/{total_cases}: {str(e)}")
            results.append({
                "query": case["query"],
                "error": str(e),
                "metrics": None,
                "overall_score": 0.0
            })
    
    logger.info(f"Evaluation complete. Processed {total_cases} cases.")
    return results

def save_results(results: List[Dict], output_dir: str):
    """
    Save evaluation results to a JSON file.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_path / f"evaluation_results_{timestamp}.json"
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    return output_file

def main():
    # Load environment variables
    load_dotenv()
    
    # Updated configuration
    config = {
        "SERVICE_API_KEY": os.getenv("SERVICE_API_KEY"),
        "OPENAI_ASSISTANT_ID": os.getenv("OPENAI_ASSISTANT_ID"),
        "OPENAI_JUDGE_ID": os.getenv("OPENAI_JUDGE_ID"),
        "RULE_GENERATOR_URL": os.getenv("RULE_GENERATOR_URL", "https://localhost:5001")
    }
    
    # Validate required configuration
    required_configs = ["SERVICE_API_KEY", "OPENAI_ASSISTANT_ID"]
    missing_configs = [key for key in required_configs if not config.get(key)]
    if missing_configs:
        raise ValueError(f"Missing required configuration: {', '.join(missing_configs)}")
    
    logger.info(f"Using Rule Generator URL: {config['RULE_GENERATOR_URL']}")
    
    # Load test cases
    test_cases = load_test_cases("query_rule_pairs.json")
    
    # Run evaluation
    results = run_evaluation(config, test_cases)
    
    # Save results
    output_file = save_results(results, "evaluation/results")
    
    # Print summary
    total_cases = len(results)
    successful_cases = sum(1 for r in results if r.get("metrics") is not None)
    avg_score = sum(r.get("overall_score", 0) for r in results) / total_cases
    
    print(f"\nEvaluation Summary:")
    print(f"Total test cases: {total_cases}")
    print(f"Successful generations: {successful_cases}")
    print(f"Average score: {avg_score:.2f}")
    print(f"Results saved to: {output_file}")

if __name__ == "__main__":
    main()
