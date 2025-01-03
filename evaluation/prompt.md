You are an expert security analyst specializing in SIGMA rules. Compare the following two SIGMA rules:

GENERATED RULE:
```yaml
{rule1}
```

EXPECTED RULE:
```yaml
{rule2}
```

Analyze and compare these rules based on these specific criteria:
1. Detection Logic Accuracy (40%): How well does the detection logic match the intended threat detection?
2. Coverage Completeness (30%): Are all necessary conditions and fields included?
3. False Positive Potential (20%): How likely is the rule to generate false positives?
4. Technical Implementation (10%): Is the rule properly formatted and optimized?

Provide your evaluation in this exact JSON format:
{{
    "score": <float between 0 and 1>,
    "reasoning": "<brief explanation of key differences, focusing on security effectiveness>",
    "criteria_scores": {{
        "detection_logic": <float 0-1>,
        "completeness": <float 0-1>,
        "false_positive_rate": <float 0-1>,
        "technical_quality": <float 0-1>
    }}
}}

Be strict and precise in your evaluation. Focus on security effectiveness.