import re
import json
import os
import docx2txt
import PyPDF2
from ocr import process_image
from llm import llm
from typing import Dict, Any, List, Tuple, Optional, Union
from collections import defaultdict
from table import process_table
from concurrent.futures import ThreadPoolExecutor, Future
from threading import Lock
import traceback
import time

def merged(data):
    if isinstance(data, str):
        data = json.loads(data)
    y_text_mapping = defaultdict(list)

    def get_average_y(boundingPolygon):
        return sum(point["y"] for point in boundingPolygon) / len(boundingPolygon)

    error_margin = 5

    def find_nearest_y(target_y, existing_ys, margin):
        for y in existing_ys:
            if abs(target_y - y) <= margin:
                return y
        return target_y

    for block in data["readResult"]["blocks"]:
        for line in block["lines"]:
            avg_y = get_average_y(line["boundingPolygon"])
            nearest_y = find_nearest_y(round(avg_y), y_text_mapping.keys(), error_margin)
            y_text_mapping[nearest_y].append(line["text"])

    y_sorted = sorted(y_text_mapping.keys())
    merged_lines = [" ".join(y_text_mapping[y]) for y in y_sorted]
    
    # Join the merged lines into a single string with newline characters between lines
    full_text = "\n".join(merged_lines)
    
    # List of substrings for which we want to add an extra newline before
    substrings = [
        "品名:",
        "原料:",
        "過敏原資訊:",
        "淨重:",
        "原產地:",
        "注意事項:",
        "有效日期:",
        "工廠地址:",
        "消費者免費服務專線:"
    ]
    
    # For each target substring, insert an additional newline before it
    for substring in substrings:
        full_text = full_text.replace(substring, "\n" + substring)
    
    return full_text

def docx_to_json(docx_path: str) -> Dict:
    print("starting docx_to_json")
    print(docx_path)
    all_text = ""
    if not os.path.exists(docx_path):
        raise ValueError(f"DOCX file not found: {docx_path}")
    with open(docx_path, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        # Loop through all pages in the PDF
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text()
            # Append the current page text to the variable
            all_text += text
    prompt_path = os.path.join(os.getenv("PROMPTS_FOLDER_PATH"), 'docx2json_prompt_template.txt')
    template_path = os.path.join(os.getenv("JSONS_FOLDER_PATH"), 'docx2json_template.json')
    
    with open(prompt_path, 'r', encoding='utf-8') as f:
        prompt_template = f.read()
    
    json_str = clean_json_string(llm(prompt_template + all_text))
    json_str = update_title_vailed(json_str)
    # Replace single quotes with double quotes in the string before parsing
    json_str = json_str.replace("'", '"')
    result = json.loads(json_str)
    
    if not validate_json_format(result, template_path):
        raise ValueError("DOCX JSON format invalid")

    def check_content(data: Dict[str, Any]) -> List[Tuple[str, str]]:
        missing_entries = []

        def validate_content(key: str, value: Any, parent: str) -> None:
            current_path = f"{parent} -> {key}" if parent else key
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    validate_content(sub_key, sub_value, current_path)
            elif key == "content" and not value:
                missing_entries.append((parent))
            elif key in {"每份", "每100公克"} and not value:
                missing_entries.append((parent, key))

        for key, value in data.items():
            validate_content(key, value, "")

        return missing_entries

    missing = check_content(result)
    if missing:
        print({"error": "Missing content", "missing": missing})
        return {"error": "Missing content", "missing": missing}
    print('done')
    return result

def remove_json_comments(json_str: str) -> str:
    """
    Remove single-line and multi-line comments from a JSON-like string.
    """
    json_str = re.sub(r'//.*?\n', '', json_str)  # Remove single-line comments
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)  # Remove multi-line comments
    return json_str

def process_llm_task(prompt_path: str, ocr_result: str, lock: Lock) -> Dict:
    """
    Process a single LLM task with thread safety.
    """
    try:
        with lock:  # Ensure thread safety when reading the file
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
        llm_return = llm(prompt_template + str(ocr_result))
        json_str = clean_json_string(llm_return)
        json_str = update_title_vailed(json_str)
        json_str = json_str.replace("'", '"')  # Convert single quotes to double quotes for valid JSON
        json_str = remove_json_comments(json_str)  # Remove any annotations
        return json.loads(json_str)  # Parse cleaned JSON
    except Exception as e:
        print(f"Error in LLM processing: {str(e)}")
        traceback.print_exc()
        raise

def image_to_json(image_path: str, scope: Union[Tuple[int, int, int, int], str] = "full") -> Dict:
    """
    Process image to JSON with parallel LLM processing
    """
    print("starting image_to_json")
    if not os.path.exists(image_path):
        raise ValueError(f"Image file not found: {image_path}")

    # Process table and OCR
    table_result = process_table(image_path)
    if table_result is None:
        return table_result

    nutrition_image_path, main_image_path = table_result
    ocr_result = merged(process_image(main_image_path, scope))
    nutrition_ocr_result = merged(process_image(nutrition_image_path, scope))

    if not ocr_result or not nutrition_ocr_result:
        raise ValueError("OCR processing failed")
    # Set up paths
    prompt_path = os.path.join(os.getenv("PROMPTS_FOLDER_PATH"), 'proofreading_prompt_template.txt')
    nutrition_prompt_path = os.path.join(os.getenv("PROMPTS_FOLDER_PATH"), 'proofreading_prompt_template(nutrition).txt')
    template_path = os.path.join(os.getenv("JSONS_FOLDER_PATH"), 'proofreading_template.json')

    # Create a lock for thread-safe file operations
    file_lock = Lock()

    # Process LLM tasks in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        # Submit both tasks
        main_future: Future = executor.submit(
            process_llm_task, 
            prompt_path, 
            ocr_result, 
            file_lock
        )
        nutrition_future: Future = executor.submit(
            process_llm_task, 
            nutrition_prompt_path, 
            nutrition_ocr_result, 
            file_lock
        )

        try:
            # Get results from both futures
            main_result = main_future.result()
            nutrition_result = nutrition_future.result()
        except Exception as e:
            print(f"Error in parallel processing: {str(e)}")
            traceback.print_exc()
            raise
    if '每份 每100公克' in nutrition_ocr_result:
        nutrition_result["營養標示"]["每100公克"] = {"title_vailed": "true"}
    else:
        nutrition_result["營養標示"]["每100公克"] = {"title_vailed": "false"}
    # Merge results
    merged_json = {**main_result, **nutrition_result}

    if not validate_json_format(merged_json, template_path):
        raise ValueError("OCR JSON format invalid")
    return merged_json

def check_title_valid(data: Dict[str, Any]) -> List[Tuple[str, str]]:
    """
    Validate titles in the JSON data
    """
    invalid_titles = []
    
    def validate_titles(key: str, value: Any, parent: str) -> None:
        current_path = f"{parent} -> {key}" if parent else key
        if isinstance(value, dict):
            if 'title_vailed' in value and value['title_vailed'] != "true":
                invalid_titles.append((current_path, 'title_vailed'))
            for sub_key, sub_value in value.items():
                validate_titles(sub_key, sub_value, current_path)

    for key, value in data.items():
        validate_titles(key, value, "")
    return invalid_titles

def compare_jsons(docx_json: Dict, ocr_json: Dict) -> Dict:
    differences = {}
    invalid_titles = []
    
    def normalize_text(text: str) -> str:
        """Normalize text by removing spaces, newlines, and converting Chinese punctuation."""
        if text is None:
            return ""
        text = text.strip().replace(" ", "").replace("\n", "").translate(str.maketrans('：（）', ':()'))
        if text.endswith(".") or text.endswith("。"):
            text = text[:-1]
        return text
    
    def is_numeric_field(key: str) -> bool:
        """Check if the field typically contains numeric values."""
        numeric_fields = {"每份", "每100公克 or 每日參考值百分比"}
        return key in numeric_fields
    
    def check_invalid_titles(data: Dict, path: str = "") -> None:
        """Recursively check for invalid titles in the OCR JSON structure."""
        if not isinstance(data, dict):
            return
        
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            
            if isinstance(value, dict):
                if "title_vailed" in value and value["title_vailed"].lower() == "false":
                    invalid_titles.append(key)
                check_invalid_titles(value, new_path)

    def compare_values(docx_data: Dict, ocr_data: Optional[Dict], path: str = "") -> None:
        """Compare two dictionaries recursively and collect differences."""
        if not isinstance(docx_data, dict) or not ocr_data:
            return
            
        for key, value in docx_data.items():
            new_path = f"{path}.{key}" if path else key
            
            if key == "content" or is_numeric_field(key):
                docx_content = normalize_text(value)
                ocr_content = normalize_text(ocr_data.get(key) if ocr_data else None)
                
                if docx_content != ocr_content:
                    differences[new_path] = {
                        "docx": value,
                        "ocr": ocr_data.get(key) if ocr_data else None
                    }
            
            elif key in ocr_data and isinstance(value, dict):
                compare_values(value, ocr_data[key], new_path)
    
    # Check for invalid titles in ocr_json
    check_invalid_titles(ocr_json)
    
    # Then compare the values
    compare_values(docx_json, ocr_json)
    
    return {
        "compare_result": {
            "invalid_titles": invalid_titles,
            "differences": differences
        }
    }


def clean_json_string(text: str) -> str:
    """Extract valid JSON from text"""
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        raise ValueError("No valid JSON found in response")
    return text[start:end + 1]

def update_title_vailed(json_str: str) -> str:
    """Find all 'title_vailed' keys and replace boolean values with string 'true' or 'false'"""
    data = json.loads(json_str)
    
    def update_values(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "title_vailed" and isinstance(value, bool):
                    obj[key] = "true" if value else "false"
                else:
                    update_values(value)
        elif isinstance(obj, list):
            for item in obj:
                update_values(item)
    
    update_values(data)
    return json.dumps(data, indent=4)
def validate_json_format(data: Dict, template_path: str) -> bool:
    """Validate JSON against template"""
    with open(template_path, 'r', encoding='utf-8') as f:
        template = json.load(f)
        
    def validate_structure(data: Dict, template: Dict) -> bool:
        if not isinstance(data, dict) or not isinstance(template, dict):
            return False
        return all(key in data and (not isinstance(value, dict) or 
                  validate_structure(data[key], value)) 
                  for key, value in template.items())
    
    return validate_structure(data, template)

if __name__ == "__main__":
    docx_path = "../AI校稿/莓果白巧瑪德蓮(單入) 莓果白巧瑪德蓮(單入) 標示說明書_114.01.03_ V.3.docx"
    docx_json = docx_to_json(docx_path)
    print(docx_json)
    # docx_path = "./test.docx"
    # image_path = "/codes/hunyaproof/AI校稿/錯5.png"
    # image_path = "/codes/hunyaproof/AI校稿/正確01.png"
    
    # try:
    #     docx_json = docx_to_json(docx_path)
    #     ocr_json = image_to_json(image_path)
    #     differences = compare_jsons(docx_json, ocr_json)
        
    #     with open('differences.json', 'w', encoding='utf-8') as f:
    #         json.dump(differences, f, ensure_ascii=False, indent=2)
            
    # except Exception as e:
    #     print(f"Error: {str(e)}")
    # ocr_json = image_to_json('../AI校稿/錯5.png', 'full')
    # print(ocr_json)
    # result = docx_to_json(docx_path)
    # print(result)