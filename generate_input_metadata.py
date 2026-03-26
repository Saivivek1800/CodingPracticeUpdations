import json

def process_item(item, output_data):
    if isinstance(item, dict):
        if "question" in item:
            q = item["question"]
            if "question_id" in q and "metadata" in q and q["metadata"] is not None:
                if isinstance(q["metadata"], dict):
                    output_data["question_data"][q["question_id"]] = json.dumps(q["metadata"])
                elif isinstance(q["metadata"], str):
                    output_data["question_data"][q["question_id"]] = q["metadata"]
        elif "question_id" in item and "metadata" in item and item["metadata"] is not None:
            if isinstance(item["metadata"], dict):
                output_data["question_data"][item["question_id"]] = json.dumps(item["metadata"])
            elif isinstance(item["metadata"], str):
                output_data["question_data"][item["question_id"]] = item["metadata"]

def main():
    try:
        with open("input.json", "r") as f:
            data = json.load(f)
            
        output_data = {"question_data": {}}
        
        if isinstance(data, list):
            for item in data:
                process_item(item, output_data)
        elif isinstance(data, dict):
            process_item(data, output_data)
                
        with open("input_metadata.json", "w") as f:
            json.dump(output_data, f, indent=4)
            
        print("Successfully formatted input.json to input_metadata.json")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
