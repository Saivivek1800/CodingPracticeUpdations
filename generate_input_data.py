import json
import sys

def process_item(item, output_data):
    if "test_cases" in item:
        for tc in item["test_cases"]:
            if "id" in tc:
                key = tc["id"]
                output_data[key] = {
                    "input": tc.get("input", ""),
                    "output": tc.get("output", ""),
                }
    elif "id" in item:
        key = item["id"]
        output_data[key] = {
            "input": item.get("input", ""),
            "output": item.get("output", ""),
        }

def main():
    try:
        with open("input.json", "r") as f:
            data = json.load(f)
            
        output_data = {}
        
        if isinstance(data, list):
            for item in data:
                process_item(item, output_data)
        elif isinstance(data, dict):
            process_item(data, output_data)
                
        with open("input_data.json", "w") as f:
            json.dump(output_data, f, indent=4)
            
        print("Successfully formatted input.json to input_data.json without is_hidden and weightage")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
