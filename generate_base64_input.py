import json
import os

def process_item(item, final_data):
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

    # Map coding items by language for easy retrieval
    coding_details = {d["language"]: d for d in item.get("coding_question_details", []) if "language" in d}
    repo_details = {d["language"]: d for d in item.get("language_code_repository_details", []) if "language" in d}

    # If both are empty, skip
    if not coding_details and not repo_details:
        return

    entry = {
        "question_id": question_id,
        "content_to_update": "",
        "language_code_repositories": []
    }

    # Determine languages to process
    common_langs = set(coding_details.keys()).intersection(set(repo_details.keys()))

    for lang in common_langs:
        # Get code content from coding_question_details
        code_content = coding_details[lang].get("code_content", "")
        
        # Get repo data from language_code_repository_details
        repo_item = repo_details[lang]
        code_repo = repo_item.get("code_repository", [])
        
        if not code_repo:
            continue
            
        file_path_to_execute = repo_item.get("file_path_to_execute", "")
        default_file_path_to_submit_code = repo_item.get("default_file_path_to_submit_code", "")

        file_details = []
        for file_info in code_repo:
            file_details.append({
                "file_name": file_info.get("file_name", ""),
                "file_type": "FILE",
                "file_content": file_info.get("file_content", ""),
                "child_files": []
            })

        lang_repo = {
            "language": lang,
            "default_code": code_content,
            "file_path_to_execute": file_path_to_execute,
            "default_file_path_to_submit_code": default_file_path_to_submit_code,
            "file_details": file_details
        }
        entry["language_code_repositories"].append(lang_repo)

    if entry["language_code_repositories"]:
        final_data.append(entry)

def main():
    print("Reading input.json...")
    try:
        if not os.path.exists("input.json"):
            print("Error: input.json not found.")
            return

        with open("input.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        final_data = []

        if isinstance(data, list):
            for item in data:
                process_item(item, final_data)
        elif isinstance(data, dict):
            process_item(data, final_data)

        # Save to a new JSON file
        with open("input_base64.json", "w", encoding="utf-8") as f:
            json.dump(final_data, f, indent=4)
            
        print(f"Successfully generated input_base64.json with {len(final_data)} questions!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
