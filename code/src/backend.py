from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain.chat_models import init_chat_model
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from duckduckgo_search import DDGS
from langchain.chains import LLMChain
import getpass
import os
import io
from googlesearch import search
import re,requests
import json
import PyPDF2
import pandas as pd
from dotenv import load_dotenv

# load_dotenv()

# if not os.environ.get("TOGETHER_API_KEY"):
#     os.environ["TOGETHER_API_KEY"] = os.getenv("TOGETHER_API_KEY")
df=pd.read_csv("sdn.csv")
os.environ["TOGETHER_API_KEY"] = "tgp_v1_pTSXsrZo4FJSVoAuRWcrjYVuEFe_67YW5FizKzJuo2g"
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
    filename = file.filename
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

        result_json = extract_json(result.content)
          # Access .content property
        sender_name = result_json.get("sender", {}).get("name", "Unknown")
        receiver_name = result_json.get("receiver", {}).get("name", "Unknown")
        print(sender_name)
        print(receiver_name)
        getllmResponse=getRiskScore(sender_name,receiver_name)
        print(getllmResponse)
        # print(result_json)
        if "error" in result_json:
            return {"error": result_json["error"]}
        return getllmResponse
    except Exception as e:
        print(str(e))
        # return {"error": f"LLM processing failed: {str(e)}"}
def getRiskScore(senderCompany,receiverCompany):
    isSenderSanctioned=fetch_sanctions(senderCompany)
    senderwikipediaData=fetch_duckduckgo_risk_data(senderCompany)
    sendergoogleData=google_search(senderCompany)
    isReceiverSanctioned=fetch_sanctions(receiverCompany)
    receiverwikipediaData=fetch_duckduckgo_risk_data(receiverCompany)
    receivergoogleData=google_search(receiverCompany)
    print("1:")
    print(isSenderSanctioned)
    print("2:")
    print(isReceiverSanctioned)
    print("Wikidata")
    print(senderwikipediaData)
    print("google data:")
    print(sendergoogleData)
    print("Wikidata")
    print(receiverwikipediaData)
    print("google data:")
    print(receivergoogleData)
    return llmResponseChain(isSenderSanctioned,senderwikipediaData,sendergoogleData,isReceiverSanctioned,receiverwikipediaData,receivergoogleData,senderCompany,receiverCompany)
def llmResponseChain(isSenderSanctioned,senderwikipediaData,sendergoogleData,isReceiverSanctioned,receiverwikipediaData,receivergoogleData,senderCompany,receiverCompany):
    url = "https://api.together.xyz/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer tgp_v1_pTSXsrZo4FJSVoAuRWcrjYVuEFe_67YW5FizKzJuo2g",
        "Content-Type": "application/json"
    }

    # Format the prompt
    prompt = f"""
### Combined Company Risk Score Analysis  

**Sender:** {senderCompany}  
**Receiver:** {receiverCompany}  
#### 🛑 **Sanctions Status**
- "⚠️ HIGH RISK: This company is sanctioned or has a history of sanctions, significantly increasing the risk score.{ isSenderSanctioned and isReceiverSanctioned}"

#### 📖 **Wikipedia Risk Insights**
    - Analyze  {receiverwikipediaData and senderwikipediaData}"

#### 🌐 **Google Risk Insights**
- Analyze  {sendergoogleData and receivergoogleData }"
### 📊 **Risk Scoring Breakdown**
- **Regulatory or Legal Risks (15%)** → Rate from 1 to 5 based on the presence of terms related to lawsuits, investigations, regulatory fines, compliance failures, or SEC filings in Google search data from both sender and receiver data.
- **Financial Instability (10%)** → Rate from 1 to 5 based on indications of financial distress, bankruptcy, high debt, cash flow problems, or revenue decline in Google search from both sender and receiver data.
- **Market Reputation Risks (5%)** → Rate from 1 to 5 based on signs of scandals, controversies, public backlash, negative media coverage, or customer complaints in Google search from both sender and receiver data.

### 🏆 **Final Risk Score Calculation**
- Sanctions Risk: {"50" if isSenderSanctioned and isReceiverSanctioned else "30" if isSenderSanctioned or isReceiverSanctioned else 0}
- Regulatory Risk: Assign a score based on available data.
- Financial Risk: Assign a score based on available data.
- Reputation Risk: Assign a score based on available data.


📌 **Total Risk Score (out of 100):** Calculate and provide the total score.
Just show Total Risk Score and conclusion in output
**📝 Conclusion:**  
- Generate the conclusion from the available data from google and wikipedia data for both sender and receiver be precise dont mention th percentage in conclusion.  Mention Both sender and receiver company details
"""
    data = {
        "model": "meta-llama/Llama-Vision-Free",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))

    if response.status_code == 200:
        result = response.json()
    else:
        print("Error:", response.text)
        return response.text
    return result["choices"][0]["message"]["content"]


def fetch_sanctions(company_name):
    if company_name in df.iloc[:, 1].values:
        return True
    else:
        return False
    
def fetch_duckduckgo_risk_data(company_name, num_results=5):
    """Fetch risk-related data about a company using DuckDuckGo search (avoiding duplicate snippets)."""

    query = f"{company_name} regulatory violations OR lawsuits OR fines OR risk score summary OR risk assessment OR financial risks OR regulatory risks OR contraverseries"
    
    with DDGS() as ddgs:
        search_results = list(ddgs.text(query, max_results=num_results))

    if not search_results:
        return f"No relevant risk data found for {company_name}."

    # Use a set to store unique snippets
    unique_snippets = set()
    extracted_texts = []

    for result in search_results:
        snippet = result.get("body", "").strip()
        if snippet and snippet not in unique_snippets:
            unique_snippets.add(snippet)
            extracted_texts.append(snippet)

    # Concatenate the unique extracted snippets
    risk_summary = " ".join(extracted_texts)

    return f"🔹 **Extended Risk Summary for {company_name}:**\n\n{risk_summary}"




def llmresponse(prompt):
    response = requests.post(
    url="https://openrouter.ai/api/v1/chat/completions",
    headers={
      "Authorization": "Bearer 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}",
      "Content-Type": "application/json",
    },
    data=json.dumps({
      "model": "nvidia/llama-3.1-nemotron-70b-instruct:free",
      "messages": [
        {
          "role": "user",
          "content": [
            {
              "type": "text",
              "text": prompt
            }
          ]
        }
      ],
      "temperature": 0.5
    })
    )

    result = response.json()
    print("llms response:")
    print(result)
    return result["choices"][0]["message"]["content"] if "choices" in result else "Error generating justification."


API_KEY = "AIzaSyDyHPR19wz3olz4oS73ole5emeU3-tUgzM"  
CX = "8337469a8b81e435d"  # Custom Search Engine ID

def google_search(query, num_results=5):
    url = f"https://www.googleapis.com/customsearch/v1"
    
    params = {
        "key": API_KEY,
        "cx": CX,
        "q": f"{query} regulatory violations OR lawsuits OR fines OR risk score summary OR risk assessment OR financial risks OR regulatory risks OR contraverseries",
        "num": num_results
    }

    response = requests.get(url, params=params)
    data = response.json()
   
    unique_snippets = set()  # Using a set to store unique snippets
    
    if "items" in data:
        for item in data["items"]:
            snippet = item.get("snippet", "")
            if snippet and snippet not in unique_snippets:
                unique_snippets.add(snippet)
                
    return unique_snippets
