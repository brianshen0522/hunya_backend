from openai import OpenAI, AzureOpenAI
import requests
import os
from dotenv import load_dotenv
import requests
import time

# Load environment variables from .env file
load_dotenv()
llm_type = os.getenv("LLM_TYPE")
def llm(prompt):
    if llm_type == "openai":
        client = OpenAI(
            api_key=os.getenv("LLM_API_KEY"),
            base_url=os.getenv("LLM_BASE_URL"),
        )
        response = client.chat.completions.create(
            model=os.getenv("LLM_MODEL"),
            messages=[
                {"role": "system", "content": "You are a package proofreading system"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            stream=False
        )
        return response.choices[0].message.content

    elif llm_type == "azure":
        client = AzureOpenAI(
            api_key=os.getenv("LLM_API_KEY"),
            api_version=os.getenv("LLM_API_VERSION"),
            base_url=os.getenv("LLM_BASE_URL"),
        )
        response = client.chat.completions.create(
            model=os.getenv("LLM_MODEL"),
            messages=[
                {"role": "system", "content": "You are a package proofreading system"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            stream=False
        )
        return response.choices[0].message.content

    elif llm_type == "ollama":
        base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434")
        model = os.getenv("LLM_MODEL", "llama2")
        
        url = f"{base_url}/api/chat"
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a package proofreading system"},
                {"role": "user", "content": prompt}
            ],
            "options": {
                "temperature": 0
            },
            "stream": False
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            # print(response.json()["message"]["content"])
            return response.json()["message"]["content"]
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to connect to Ollama: {str(e)}")
        except (KeyError, ValueError) as e:
            raise ValueError(f"Invalid response from Ollama: {str(e)}")
    
    else:
        raise ValueError(f"Unsupported LLM type: {llm_type}")

if __name__ == '__main__':
    print(llm('hi'))