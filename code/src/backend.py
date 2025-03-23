from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain.chat_models import init_chat_model
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain.chains import LLMChain
import getpass
import os
import io
import re
import json
import PyPDF2
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("TOGETHER_API_KEY"):
    os.environ["TOGETHER_API_KEY"] = os.getenv("TOGETHER_API_KEY")

def extract_json(response_content):
    try:
        # First try to parse directly if response is clean JSON
        return json.loads(response_content)
    except json.JSONDecodeError:
        # If direct parse fails, use regex extraction
        try:
            # Handle both ```json and ``` wrapped responses
            json_match = re.search(
                r'```(?:json)?\s*({.*?})\s*```', 
                response_content, 
                re.DOTALL
            )
            
            if json_match:
                json_str = json_match.group(1)
                
                # Clean common LLM artifacts
                json_str = json_str.strip()
                json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)  # Remove comments
                json_str = re.sub(r'//.*$', '', json_str, flags=re.MULTILINE)    # Remove line comments
                json_str = re.sub(r',\s*}', '}', json_str)                       # Fix trailing commas
                json_str = re.sub(r',\s*]', ']', json_str)                       # Fix trailing commas in arrays
                
                return json.loads(json_str)
            
            # Fallback: Try to find deepest JSON structure
            stack = []
            start_index = end_index = -1
            for i, c in enumerate(response_content):
                if c == '{':
                    if not stack:
                        start_index = i
                    stack.append(c)
                elif c == '}':
                    if stack:
                        stack.pop()
                        if not stack:
                            end_index = i + 1
            
            if start_index != -1 and end_index != -1:
                json_str = response_content[start_index:end_index]
                return json.loads(json_str)
            
            return {"error": "No valid JSON structure found"}
            
        except json.JSONDecodeError as e:
            print(f"JSON decoding failed: {str(e)}")
            # Try to find the error position
            error_line = re.sub(r'\r\n', '\n', json_str).split('\n')[e.lineno - 1]
            return {
                "error": f"JSON parsing error: {str(e)}",
                "context": f"At line {e.lineno}: {error_line}"
            }
        except Exception as e:
            return {"error": f"JSON extraction failed: {str(e)}"}

def process_file(file):
    filename = file.filename.lower()
    if filename.endswith('.txt'):
        text = file.read().decode('utf-8')
    elif filename.endswith('.pdf'):
        pdf_reader = PyPDF2.PdfReader(file)
        text = "\n".join([page.extract_text() for page in pdf_reader.pages if page.extract_text()])
    elif filename.endswith('.csv'):
        df = pd.read_csv(file)
        text = df.to_string(index=False)
    return text

def extract_entities(text):
    try:
        # Define a system prompt to set the context and desired behavior.
        system_message = SystemMessagePromptTemplate.from_template(
            "You are a helpful assistant specialized in extracting structured data from transaction records and identifying the nature of entities such as corporations, non-profits, shell companies, and financial intermediaries."
        )

        # Define the human message with instructions and the expected JSON schema.
        human_message = HumanMessagePromptTemplate.from_template(
            """
            Extract all relevant entities from the following transaction record and output a JSON object with the following format:

            {{
            "sender": {{
                "name": "ENTITY_NAME",
                "location": "ENTITY_LOCATION",
                "identifiers": {{"registration_number": "VALUE", "tax_id": "VALUE"}},
                "additional_details": "Additional sender details"
            }},
            "receiver": {{
                "name": "ENTITY_NAME",
                "location": "ENTITY_LOCATION",
                "identifiers": {{"registration_number": "VALUE", "tax_id": "VALUE"}},
                "additional_details": "Additional receiver details"
            }},
            "intermediaries": [
                {{
                "name": "ENTITY_NAME",
                "role": "Financial intermediary / Shell company",
                "location": "ENTITY_LOCATION"
                }}
            ],
            "beneficiaries": [
                {{
                "name": "ENTITY_NAME",
                "relationship": "Beneficiary or payee",
                "details": "Additional notes"
                }}
            ],
            "transaction_metadata": {{
                "transaction_id": "VALUE",
                "date": "YYYY-MM-DD HH:MM:SS",
                "amount": "VALUE",
                "currency": "CURRENCY_CODE",
                "transaction_type": "Wire Transfer/Payment/Other"
            }},
            "risk_indicators": "Any suspicious flags or additional risk notes."
            }}

            If any field is missing in the transaction record, output null for that field.

            Here is the transaction data:
            {transaction_data}
            """
        )

        # Combine the system and human messages into a chat prompt.
        chat_prompt = ChatPromptTemplate.from_messages([system_message, human_message])

        # Initialize the chat model using your provided function.
        chat_model = init_chat_model("meta-llama/Llama-Vision-Free", model_provider="together")

        # Create the chain.
        # chain = LLMChain(llm=chat_model, prompt=chat_prompt)
        chain = chat_prompt | chat_model

        # Run the chain to extract entities.
        result = chain.invoke({'transaction_data': text})
        # print(result)

        result_json = extract_json(result.content)  # Access .content property
        # print(result_json)
        
        if "error" in result_json:
            return {"error": result_json["error"]}
        return result_json
    except Exception as e:
        print(str(e))
        # return {"error": f"LLM processing failed: {str(e)}"}