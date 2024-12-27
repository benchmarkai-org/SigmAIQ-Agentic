import json
import os
from typing import List, Dict
from sigma.rule import SigmaRule
from pathlib import Path

def create_sigma_rule_obj(yaml_content: str) -> SigmaRule:
    """Convert YAML content string to SigmaRule object"""
    # Use the Sigma library to parse YAML content into a SigmaRule object
    return SigmaRule.from_yaml(yaml_content)

def process_rules_to_query_pairs(rules_dir: str) -> List[Dict]:
    """
    Process Sigma rules and convert them to query-rule pairs where:
    - query is the rule's description
    - expected_rule is the complete rule in YAML format
    
    Args:
        rules_dir: Directory containing Sigma rule YAML files
    """
    # Convert string path to Path object for better path handling
    rules_path = Path(rules_dir)
    # Initialize list to store our query-rule pairs
    query_rule_pairs = []
    
    # Walk through all yaml files in directory and subdirectories
    for yaml_file in rules_path.rglob("*.yml"):
        try:
            # Read the YAML content from file
            with open(yaml_file, 'r', encoding='utf-8') as f:
                yaml_content = f.read()
            
            # Parse YAML into a SigmaRule object
            sigma_rule = create_sigma_rule_obj(yaml_content)
            
            # Skip rules that don't have descriptions
            if not hasattr(sigma_rule, 'description') or not sigma_rule.description:
                continue
                
            # Create a pair containing the rule description and its full YAML content
            pair = {
                "query": sigma_rule.description,
                "expected_rule": yaml_content
            }
            
            # Add to our collection
            query_rule_pairs.append(pair)
            print(f"✅ Processed rule: {sigma_rule.title}")
                
        except Exception as e:
            # Log any errors encountered while processing individual rules
            print(f"❌ Error processing rule {yaml_file}: {e}")
    
    print(f"\nProcessed {len(query_rule_pairs)} rules")
    return query_rule_pairs

def save_query_rule_pairs(pairs: List[Dict], output_file: str = "query_rule_pairs.json"):
    """Save query-rule pairs to a JSON file"""
    # Write the pairs to a JSON file with pretty printing (indent=4)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(pairs, f, indent=4)
    print(f"\nResults saved to {output_file}")

def main():
    """
    Process Sigma rules and create query-rule pairs JSON file
    """
    # Set default rules directory (can be overridden via command line)
    rules_dir = "./sigma_core/rules/linux/network_connection/"
    
    # Check if a directory was provided as a command line argument
    import sys
    if len(sys.argv) > 1:
        rules_dir = sys.argv[1]
    
    # Validate that the rules directory exists
    if not os.path.exists(rules_dir):
        print(f"Error: Rules directory '{rules_dir}' not found")
        sys.exit(1)
    
    # Process all rules and save results to JSON
    pairs = process_rules_to_query_pairs(rules_dir)
    save_query_rule_pairs(pairs)

# Only run the main function if this script is being run directly
if __name__ == "__main__":
    main()
