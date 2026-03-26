import json
import os

def process_item(item, helper_code_data):
    if not isinstance(item, dict):
        return
        
    # Extract question_id
    question_id = None
    if "question" in item and "question_id" in item["question"]:
        question_id = item["question"]["question_id"]
    elif "question_id" in item:
        question_id = item["question_id"]
        
    if not question_id:
        return
        
    coding_details = item.get("coding_question_details", [])
    for detail in coding_details:
        language = detail.get("language")
        debug_helper_code = detail.get("debug_helper_code")
        
        # skip if debug_helper_code is null or empty as requested
        if debug_helper_code is None or debug_helper_code == "":
            continue
            
        helper_code_data.append({
            "debug_helper_code": debug_helper_code,
            "language": language,
            "question_id": question_id
        })

def main():
    print("Reading input.json...")
    try:
        with open("input.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            
        helper_code_data = []
        
        if isinstance(data, list):
            for item in data:
                process_item(item, helper_code_data)
        elif isinstance(data, dict):
            process_item(data, helper_code_data)
            
        # Save to a new JSON file
        with open("input_helper.json", "w", encoding="utf-8") as f:
            json.dump(helper_code_data, f, indent=4)
            
        print(f"Successfully generated input_helper.json with {len(helper_code_data)} items!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
