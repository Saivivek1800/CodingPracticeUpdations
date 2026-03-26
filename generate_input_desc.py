import json

def process_item(item, output_data):
    if isinstance(item, dict):
        if "question" in item:
            q = item["question"]
            if "question_id" in q and "content" in q:
                output_data["question_data"][q["question_id"]] = q["content"]
        elif "question_id" in item and "content" in item:
            output_data["question_data"][item["question_id"]] = item["content"]

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
                
        with open("input_description.json", "w") as f:
            json.dump(output_data, f, indent=4)
            
        print("Successfully formatted input.json to input_description.json")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
