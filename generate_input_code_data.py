import json
import sys

def process_details(details, output_data):
    if not details:
        return
        
    code_id = None
    for detail in details:
        if "code_id" in detail:
            code_id = detail["code_id"]
            break
            
    if code_id:
        if code_id not in output_data:
            output_data[code_id] = []
            
        for detail in details:
            formatted_detail = {}
            if "code_content" in detail:
                formatted_detail["code_content"] = detail["code_content"]
            if "language" in detail:
                formatted_detail["language"] = detail["language"]
            
            if formatted_detail:
                # Add deduplication check
                if formatted_detail not in output_data[code_id]:
                    output_data[code_id].append(formatted_detail)

def process_item(item, output_data):
    if not isinstance(item, dict):
        return
        
    if "coding_question_details" in item:
        process_details(item["coding_question_details"], output_data)
        
    if "solutions" in item:
        for solution in item["solutions"]:
            if "code_details" in solution:
                process_details(solution["code_details"], output_data)
            elif "code_content" in solution:
                process_details([solution], output_data)

def main():
    try:
        print("Loading JSON...")
        with open("input.json", "r") as f:
            data = json.load(f)
        print(f"Loaded JSON. Data type: {type(data)}")
            
        output_data = {}
        
        if isinstance(data, list):
            print(f"Processing list of {len(data)} items...")
            for idx, item in enumerate(data):
                process_item(item, output_data)
                if idx % 10 == 0:
                    print(f"Processed {idx} items...")
        elif isinstance(data, dict):
            process_item(data, output_data)
        
        print("Writing output...")
        with open("input_code_data.json", "w") as f:
            json.dump(output_data, f, indent=4)
            
        print("Successfully formatted input.json to input_code_data.json (excluding unwanted fields).")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
