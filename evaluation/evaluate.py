import json
import yaml
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple
from langchain.evaluation import load_evaluator
from dotenv import load_dotenv
import os
import time
import requests

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
        # Ensure the URL doesn't end with a slash
        base_url = config['RULE_GENERATOR_URL'].rstrip('/')
        
        response = requests.post(
            f"{base_url}/generate",
            json={
                "query": query,
                "assistant_id": config['OPENAI_ASSISTANT_ID']
            },
            headers={"Authorization": f"Bearer {config['OPENAI_API_KEY']}"}
        )
        response.raise_for_status()
        return response.json()["rule"]
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {str(e)}")  # Add debug logging
        raise Exception(f"Failed to generate rule: {str(e)}")

def run_evaluation(config: Dict, test_cases: List[Dict]) -> List[Dict]:
    """
    Run evaluation on all test cases and return results.
    """
    results = []
    
    for case in test_cases:
        try:
            # Generate rule using microservice
            yaml_block = generate_rule(case["query"], config)
            
            # Evaluate the generated rule
            metrics, score = evaluate_rule(yaml_block, case["expected_rule"])
            
            results.append({
                "query": case["query"],
                "generated_rule": yaml_block,
                "expected_rule": case["expected_rule"],
                "metrics": metrics,
                "overall_score": score
            })
            
        except Exception as e:
            results.append({
                "query": case["query"],
                "error": str(e),
                "metrics": None,
                "overall_score": 0.0
            })
    
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
        "RULE_GENERATOR_URL": os.getenv("RULE_GENERATOR_URL", "http://127.0.0.1:5001")
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
