import requests
from PIL import Image
from typing import Dict, Union, BinaryIO, Union, Tuple
import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class AzureOCRClient:
    def __init__(self, endpoint: str, subscription_key: str):
        self.endpoint = endpoint.rstrip('/')
        self.subscription_key = subscription_key

    def recognize_text(
        self,
        image: Union[str, bytes, BinaryIO],
        detect_orientation: bool = True,
        language: str = 'zh-Hant'
    ) -> Dict:
        url = f"{self.endpoint}/computervision/imageanalysis:analyze?features=read&model-version=latest&language=en&gender-neutral-caption=false&api-version=2023-10-01"
        params = {
            'detectOrientation': str(detect_orientation).lower(),
            'language': language
        }
        headers = {
            'Content-Type': 'application/octet-stream',
            'Ocp-Apim-Subscription-Key': self.subscription_key
        }
        
        if isinstance(image, str):
            with open(image, 'rb') as f:
                image_data = f.read()
        elif isinstance(image, bytes):
            image_data = image
        else:
            image_data = image.read()

        try:
            response = requests.post(url, headers=headers, params=params, data=image_data)
            response.raise_for_status()
            result = response.json()
            return self.remove_words_objects(result)
        except requests.exceptions.RequestException as e:
            if response.content:
                error_detail = response.json()
                raise Exception(f"Azure OCR API Error: {error_detail.get('message', str(e))}")
            raise Exception(f"Failed to recognize text: {str(e)}")

    def remove_words_objects(self, data: Dict) -> Dict:
        if isinstance(data, dict):
            return {k: self.remove_words_objects(v) for k, v in data.items() if k != "words"}
        elif isinstance(data, list):
            return [self.remove_words_objects(item) for item in data]
        return data

    def extract_text(self, ocr_result: Dict) -> str:
        if not ocr_result or 'regions' not in ocr_result:
            return ''
        
        text_blocks = []
        for region in ocr_result['regions']:
            region_text = []
            for line in region['lines']:
                if 'words' in line:
                    line_text = ' '.join(word['text'] for word in line['words'])
                    region_text.append(line_text)
            text_blocks.append('\n'.join(region_text))
        
        return '\n\n'.join(text_blocks)

def process_image(image_path: str, scope: Union[Tuple[int, int, int, int], str] = "full"):
    try:
        # Load and crop image if needed
        img = Image.open(image_path)
        
        if scope != "full":
            x_min, y_min, x_max, y_max = scope
            img = img.crop((x_min, y_min, x_max, y_max))
        
        # Save cropped image temporarily
        rgb_img = img.convert('RGB')
        # temp_path = f"./cropped.jpg"
        # img.save(temp_path)
        
        client = AzureOCRClient(
            endpoint=os.getenv("AZURE_ENDPOINT"),
            subscription_key=os.getenv("AZURE_SUBSCRIPTION_KEY")
        )
        
        result = client.recognize_text(image_path)
        print()
        # os.remove(temp_path)
        return json.dumps(result, indent=2, ensure_ascii=False)
        
    except Exception as e:
        print('Error:', str(e))
        return None

def save_result_to_json(result: str, output_path: str = 'ocr_result.json'):
    if not result:
        return
        
    try:
        parsed_json = json.loads(result)
        formatted_json = json.dumps(parsed_json, indent=2, ensure_ascii=False)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(formatted_json)
        print(f'Result saved to {output_path}')
    except Exception as e:
        print(f'Error saving result: {str(e)}')

if __name__ == '__main__':
    result = process_image('/home/user/project/hunyaproof/git/uploads/images/1_cropped_no_table.png', 'full')
    save_result_to_json(result)