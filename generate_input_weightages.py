import json
import sys


def add_weightages(item, output_data):
    if isinstance(item, dict) and "test_cases" in item and isinstance(item["test_cases"], list):
        for tc in item["test_cases"]:
            if not isinstance(tc, dict):
                continue
            testcase_id = tc.get("id")
            if testcase_id is None:
                continue
            if "weightage" in tc:
                output_data[str(testcase_id)] = tc.get("weightage")
    elif isinstance(item, dict) and "id" in item and "weightage" in item:
        output_data[str(item["id"])] = item.get("weightage")


def main():
    try:
        with open("input.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        output_data = {}
        if isinstance(data, list):
            for item in data:
                add_weightages(item, output_data)
        elif isinstance(data, dict):
            add_weightages(data, output_data)

        with open("input_weightages.json", "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=4)

        print("Successfully formatted input.json to input_weightages.json (testcase id -> weightage)")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
