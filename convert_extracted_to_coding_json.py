import json


REQUIRED_KEYS_IN_ORDER = [
    "test_cases",
    "total_score",
    "question_type",
    "question_asked_by_companies_info",
    "question",
    "coding_question_details",
    "code_repository_details",
    "language_code_repository_details",
    "solutions",
    "hints",
    "test_case_evaluation_metrics"
]

LANG_ORDER = ["CPP", "PYTHON", "JAVA", "NODE_JS"]

TESTCASE_KEYS_IN_ORDER = [
    "id",
    "input",
    "output",
    "is_hidden",
    "weightage",
    "evaluation_type",
    "display_text",
    "criteria",
    "tags",
    "order"
]

CODING_QUESTION_KEYS_ORDER = [
    "code_content",
    "default_code",
    "language",
    "code_id",
    "is_function_based",
    "debug_helper_code"
]


def order_by_language(items):
    """Order items strictly as CPP -> PYTHON -> JAVA -> NODE_JS."""
    ordered = []
    for lang in LANG_ORDER:
        for item in items:
            item_lang = item.get("language")
            if item_lang == lang:
                ordered.append(item)
            elif lang == "PYTHON" and item_lang == "PYTHON39":
                ordered.append(item)
    return ordered


def filter_testcases(testcases):
    """Keep testcase keys in exact order."""
    result = []
    for tc in testcases:
        ordered_tc = {}
        for key in TESTCASE_KEYS_IN_ORDER:
            ordered_tc[key] = tc.get(key)
        result.append(ordered_tc)
    return result


def order_coding_question_details(entries):
    """Order coding_question_details keys + language order."""
    ordered_langs = order_by_language(entries)
    result = []

    for item in ordered_langs:
        ordered_item = {}
        for key in CODING_QUESTION_KEYS_ORDER:
            ordered_item[key] = item.get(key)
        result.append(ordered_item)

    return result


def convert_language_code_repo(entries):
    ordered = order_by_language(entries)
    output = []

    for e in ordered:
        repo_files = []
        for f in e.get("code_repository", []):
            repo_files.append({
                "file_name": f.get("file_path"),
                "file_type": "FILE",
                "file_content": f.get("file_contents")
            })

        output.append({
            "language": e.get("language"),
            "file_path_to_execute": e.get("file_path_to_execute"),
            "default_file_path_to_submit_code": e.get("default_file_path_to_submit_code"),
            "code_repository": repo_files
        })

    return output


def convert(input_data):
    if not isinstance(input_data, list):
        raise ValueError("Input JSON must be a LIST of questions")

    final_output = []

    for q in input_data:
        new_q = {}

        for key in REQUIRED_KEYS_IN_ORDER:
            if key not in q:
                if key in [
                    "test_cases",
                    "coding_question_details",
                    "language_code_repository_details",
                    "solutions",
                    "hints",
                    "test_case_evaluation_metrics",
                    "question_asked_by_companies_info"
                ]:
                    new_q[key] = []
                elif key in ["question", "code_repository_details"]:
                    new_q[key] = {}
                elif key == "total_score":
                    new_q[key] = 0
                elif key == "question_type":
                    new_q[key] = "CODING"
                continue

            if key == "test_cases":
                new_q[key] = filter_testcases(q[key])
            elif key == "coding_question_details":
                new_q[key] = order_coding_question_details(q[key])
            elif key == "language_code_repository_details":
                new_q[key] = convert_language_code_repo(q[key])
            elif key == "total_score":
                new_q[key] = int(q[key])
            else:
                new_q[key] = q[key]

        final_output.append(new_q)

    return final_output


if __name__ == "__main__":
    INPUT_FILE = "extracted_coding_questions.json"
    OUTPUT_FILE = "coding_questions_output.json"

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        input_json = json.load(f)

    output_json = convert(input_json)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_json, f, indent=2)

    print("Output generated with correct format, order, and integer total_score")
