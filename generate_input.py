import json
import sys

def process_item(item, final_data):
    if not isinstance(item, dict):
        return
        
    try:
        question_id = item["question"]["question_id"]
        
        coding_details = {d["language"]: d for d in item.get("coding_question_details", [])}
        repo_details = {d["language"]: d for d in item.get("language_code_repository_details", [])}
        
        languages = ["CPP", "PYTHON", "JAVA", "NODE_JS"]
        
        item_data = {
            "question_id": question_id,
            "content_to_update": "",
            "language_code_repositories": []
        }
        
        for lang in languages:
            if lang in coding_details and lang in repo_details and repo_details[lang].get("code_repository"):
                code_content = coding_details[lang].get("code_content", "")
                repo_list = repo_details[lang]["code_repository"]
                
                if len(repo_list) > 0:
                    file_content = repo_list[0].get("file_content", "")
                    file_name = repo_list[0].get("file_name", "")
                    file_path_to_execute = repo_details[lang].get("file_path_to_execute", "")
                    default_file_path_to_submit_code = repo_details[lang].get("default_file_path_to_submit_code", "")
                    
                    lang_repo = {
                        "language": lang,
                        "default_code": code_content,
                        "file_path_to_execute": file_path_to_execute,
                        "default_file_path_to_submit_code": default_file_path_to_submit_code,
                        "file_details": [
                            {
                                "file_name": file_name,
                                "file_type": "FILE",
                                "file_content": file_content,
                                "child_files": []
                            }
                        ]
                    }
                    item_data["language_code_repositories"].append(lang_repo)
                    
        final_data.append(item_data)
    except KeyError as e:
        print(f"Skipping an item due to missing key: {e}")

def main():
    try:
        with open("input.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading input.json: {e}")
        sys.exit(1)

    final_data = []

    if isinstance(data, list):
        for item in data:
            process_item(item, final_data)
    elif isinstance(data, dict):
        process_item(data, final_data)

    with open("generated_input.py", "w", encoding="utf-8") as f:
        f.write("question_code_repository_data = " + json.dumps(final_data, indent=4) + "\n")
        
    print(f"Successfully generated generated_input.py with {len(final_data)} items!")

if __name__ == "__main__":
    main()
