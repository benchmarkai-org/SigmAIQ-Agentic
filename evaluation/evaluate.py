import json
import yaml
import requests
import time
from typing import Dict, List
import logging
import urllib3
import os
from dotenv import load_dotenv
from datetime import datetime
from langchain.evaluation import load_evaluator
from pathlib import Path

# Suppress SSL warnings
urllib3.disable_warnings()

# Configure logging
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
            timeout=300
        )
        response.raise_for_status()
        return response.json()["rule"]
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {str(e)}")
        raise Exception(f"Failed to generate rule: {str(e)}") 

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
                "assistant_id": config['JUDGE_ASSISTANT_ID']
            },
            headers={
                "Authorization": f"Bearer {config['SERVICE_API_KEY']}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            verify=False,
            timeout=300
        )
        response.raise_for_status()
        return response.json()["judgment"]
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Judge request failed: {str(e)}")
        raise Exception(f"Failed to get judgment: {str(e)}")

def evaluate_rule(generated_rule: str, expected_rule: str, config: Dict) -> tuple:
    """
    Evaluate a generated rule against the expected rule.
    Combines Langchain-based metrics with LLM judgment.
    Returns (metrics_dict, overall_score)
    """
    try:
        # Get Langchain-based metrics
        langchain_metrics = calculate_langchain_metrics(generated_rule, expected_rule)
        
        # Get LLM judgment
        llm_judgment = get_judge_comparison(generated_rule, expected_rule, config)
        
        # Combine all metrics into one dictionary
        combined_metrics = {
            **langchain_metrics,  # Include all Langchain metrics
            "llm_judgment": llm_judgment  # Add LLM judgment
        }
        
        # Calculate final score using all metrics
        overall_score = calculate_combined_score(combined_metrics)
        
        return combined_metrics, overall_score
        
    except Exception as e:
        logger.error(f"Evaluation failed: {str(e)}")
        raise

def calculate_langchain_metrics(generated_rule: str, expected_rule: str) -> dict:
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

        print(f"Debug - Metrics: {metrics}")
        return metrics
    
    except yaml.YAMLError:
        return {"valid_yaml": 0.0, "has_required_fields": 0.0,
                "detection_logic_similarity": 0.0, "metadata_completeness": 0.0}, 0.0


def calculate_combined_score(metrics: dict) -> float:
    """
    Calculate overall score incorporating both Langchain metrics and LLM judgment.
    Returns a weighted score between 0 and 1.
    """
    # Weights for different components
    weights = {
        "valid_yaml": 0.15,
        "has_required_fields": 0.20,
        "detection_logic_similarity": 0.25,
        "metadata_completeness": 0.10,
        "llm_judgment": 0.30
    }
    
    # Create a copy of metrics to avoid modifying the original
    metrics_for_calculation = metrics.copy()
    
    # Extract numerical score from llm_judgment if it exists
    if "llm_judgment" in metrics:
        try:
            # First try to parse the JSON string
            if isinstance(metrics["llm_judgment"], str):
                judgment_dict = json.loads(metrics["llm_judgment"])
                if isinstance(judgment_dict, dict):
                    llm_score = float(judgment_dict.get("score", 0.5))
                else:
                    # Handle legacy string case
                    score_mapping = {
                        "excellent": 1.0,
                        "good": 0.75,
                        "fair": 0.5,
                        "poor": 0.25,
                        "bad": 0.0
                    }
                    llm_score = score_mapping.get(metrics["llm_judgment"].lower(), 0.5)
            else:
                llm_score = float(metrics["llm_judgment"])
            
            metrics_for_calculation["llm_judgment"] = llm_score
        except (ValueError, AttributeError, TypeError, json.JSONDecodeError) as e:
            # If there's any error parsing the score, use a default value
            logger.warning(f"Could not parse LLM judgment score: {e}. Using default value of 0.5")
            metrics_for_calculation["llm_judgment"] = 0.5
    
    # Calculate weighted sum of all metrics
    overall_score = sum(
        metrics_for_calculation[k] * weights[k] 
        for k in weights 
        if k in metrics_for_calculation
    )
    
    # Normalize to ensure score is between 0 and 1
    return min(max(overall_score, 0.0), 1.0)

def run_evaluation(config: Dict, test_cases: List[Dict]) -> List[Dict]:
    """
    Run evaluation on all test cases and return results.
    """
    # Validate required config
    required_config = ['RULE_GENERATOR_URL', 'SERVICE_API_KEY', 
                      'OPENAI_ASSISTANT_ID', 'JUDGE_ASSISTANT_ID']
    if not all(key in config for key in required_config):
        raise ValueError(f"Missing required configuration. Need: {required_config}")
    
    results = []
    total_cases = len(test_cases)
    
    logger.info(f"Starting evaluation of {total_cases} test cases...")
    
    for idx, case in enumerate(test_cases, 1):
        try:
            logger.info(f"Processing case {idx}/{total_cases}: {case['query'][:50]}...")
            
            yaml_block = generate_rule(case["query"], config)
            
            # Evaluate using both Langchain metrics and LLM judgment
            metrics, score = evaluate_rule(yaml_block, case["expected_rule"], config)
            
            results.append({
                "query": case["query"],
                "generated_rule": yaml_block,
                "expected_rule": case["expected_rule"],
                "metrics": metrics,
                "overall_score": score,
                "llm_judgment_text": metrics["llm_judgment"]  # Extract from metrics
            })
            
            logger.info(f"Completed case {idx}/{total_cases} with score: {score:.2f}")
            
        except Exception as e:
            logger.error(f"Failed case {idx}/{total_cases}: {str(e)}")
            results.append({
                "query": case["query"],
                "error": str(e),
                "metrics": None,
                "overall_score": 0.0,
                "llm_judgment_text": None
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
    
    # Load configuration with modified default URL
    config = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "OPENAI_ASSISTANT_ID": os.getenv("OPENAI_ASSISTANT_ID"),
        "RULE_GENERATOR_URL": os.getenv("RULE_GENERATOR_URL", "http://127.0.0.1:5001"),
        "JUDGE_ASSISTANT_ID": os.getenv("JUDGE_ASSISTANT_ID"),
        "SERVICE_API_KEY": os.getenv("SERVICE_API_KEY")
    }
    
    # Debug print
    print(f"Using Rule Generator URL: {config['RULE_GENERATOR_URL']}")
    
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