from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain.chat_models import init_chat_model
import getpass
import os
import re
import json
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("TOGETHER_API_KEY"):
    os.environ["TOGETHER_API_KEY"] = os.getenv("TOGETHER_API_KEY")

def extract_json(response_content):
    # Use regex to extract the JSON portion from the response
    json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
    
    if json_match:
        json_str = json_match.group(0)  # Extract matched JSON string
        try:
            return json.loads(json_str)  # Convert to Python dictionary
        except json.JSONDecodeError:
            print("Error decoding JSON")
            return None
    else:
        print("No JSON found in response")
        return None

def extract_entities(text):
    human = HumanMessage(
        # content= text + ". Make sure your output has only the JSON object and no other strings"
        content = text
    )
    system = SystemMessage(
        content='''You are an amazing Natural Language processing AI assistant.
        When you receive a text you identifiy entities in it output a json with their categories as keys.'''
    )
    # aimsg = AIMessage()

    chat_model = init_chat_model("meta-llama/Llama-Vision-Free", model_provider="together")
    response = chat_model.invoke([system, human])
    parsed_data = extract_json(response.content)
    return parsed_data