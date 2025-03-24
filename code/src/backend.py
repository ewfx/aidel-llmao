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
        senderRiskScore=getRiskScore(sender_name)
        print(senderRiskScore)
        # print(result_json)
        if "error" in result_json:
            return {"error": result_json["error"]}
        return senderRiskScore
    except Exception as e:
        print(str(e))
        # return {"error": f"LLM processing failed: {str(e)}"}
def getRiskScore(company):
    isSanctioned=fetch_sanctions(company)
    wikipediaData=fetch_duckduckgo_risk_data(company)
    googleData=google_search(company)
    return llmResponseChain(isSanctioned,company,wikipediaData,googleData)
def llmResponseChain(isSanctioned,company,wikipediaData,googleData):
    url = "https://api.together.xyz/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer tgp_v1_pTSXsrZo4FJSVoAuRWcrjYVuEFe_67YW5FizKzJuo2g",
        "Content-Type": "application/json"
    }

    # Format the prompt
    prompt = f"""
    ### Company Risk Score Analysis

    **Company Name:** {company}  

    #### 🛑 Sanctions Status (70% Weight)
    { "⚠️ HIGH RISK: This company is sanctioned or has past sanctions. This significantly increases the overall risk score." if isSanctioned else "✅ No known sanctions. Sanctions risk is minimal." }

    #### 📖 Wikipedia Risk Insights (15% Weight)
    Analyze the { wikipediaData } data to get more insights to generate summary

    #### 🌐 Google Risk Insights (15% Weight)
    Analyze the { googleData } data to get more insights to generate summary
    
    #### 📊 Risk Scoring Criteria
    - **Sanctions Risk (70%)** → **{"10/10" if isSanctioned else "0/10"}**
    - **Regulatory or legal issues (15%)** → **{"7/10" if 'lawsuit' in googleData or 'SEC' in googleData else "3/10"}**
    - **Financial instability concerns (10%)** → **{"6/10" if 'debt' in googleData or 'financial trouble' in googleData else "2/10"}**
    - **Market reputation risks (5%)** → **{"8/10" if 'controversy' in googleData else "4/10"}**
    
    #### 🏆 Final Risk Score Calculation
    - **Sanctions Weight:** { "50" if isSanctioned else "0" }  
    - **Regulatory Risk Weight:** { "7" if 'lawsuit' in googleData or 'SEC' in googleData else "3" }  
    - **Financial Risk Weight:** { "6" if 'debt' in googleData or 'financial trouble' in googleData else "2" }  
    - **Reputation Risk Weight:** { "8" if 'controversy' in googleData else "4" }  

    📌 **Total Risk Score (out of 100):** { 50 * (1 if isSanctioned else 0) + 7 + 6 + 8 } / 100  
    dont show risk Scoring creiteria in output and weights and percentages also in output
    **📝 Conclusion:**  
    { "generate the conclusion from available data be precise" }
    """

    data = {
        "model": "meta-llama/Llama-Vision-Free",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))

    if response.status_code == 200:
        result = response.json()
    else:
        print("Error:", response.text)
        return response.text
    return result["choices"][0]["message"]["content"]

def generatePrompt(isSanctioned,wikipediaData,googleData,company):
    prompt = f"""
    **🔍 Company Risk Score Analysis: {company}**
    
    ### 🛑 **Sanctions Status (70% Weight)**
    { "⚠️ HIGH RISK: This company is sanctioned or has past sanctions. This significantly increases the overall risk score." if isSanctioned else "✅ No known sanctions. Sanctions risk is minimal." }

    ### 📖 **Wikipedia Risk Insights (15% Weight)**
    { wikipediaData if wikipediaData else "No significant risk-related data found on Wikipedia." }

    ### 🌐 **Google Risk Insights (15% Weight)**
    { googleData if googleData else "No major risk-related findings from Google search." }

    ### 📊 **Risk Scoring Criteria**
    - **Sanctions Risk** (60%) → **{"10/10" if isSanctioned else "0/10"}**
    - **Regulatory or legal issues?** (15%) → **{"7/10" if 'lawsuit' in googleData or 'SEC' in googleData else "3/10"}**
    - **Financial instability concerns?** (12%) → **{"6/10" if 'debt' in googleData or 'financial trouble' in googleData else "2/10"}**
    - **Market reputation risks?** (10%) → **{"8/10" if 'controversy' in googleData else "4/10"}**
    - **Environmental or operational risks?** (3%) → **{"7/10" if 'violation' in googleData or 'fines' in googleData else "3/10"}**

    ### 🏆 **Final Risk Score Calculation**
    - **Sanctions Weight:** { "50" if isSanctioned else "0" }  
    - **Regulatory Risk Weight:** { "7" if 'lawsuit' in googleData or 'SEC' in googleData else "3" }  
    - **Financial Risk Weight:** { "6" if 'debt' in googleData or 'financial trouble' in googleData else "2" }  
    - **Reputation Risk Weight:** { "8" if 'controversy' in googleData else "4" }  
    - **Environmental/Operational Risk Weight:** { "7" if 'violation' in googleData or 'fines' in googleData else "3" }  

    **📌 Total Risk Score (out of 100):** { 50 * (1 if isSanctioned else 0) + 7 + 6 + 8 + 7 } / 100  

    **📝 Conclusion:**  
    { "🚨 HIGH RISK: Due to active sanctions, regulatory, and financial concerns, this company poses a significant risk." if isSanctioned else "⚖️ MODERATE RISK: No sanctions, but regulatory and financial risks should be monitored." }
    """
    return prompt

def fetch_sanctions(company_name):
    if company_name in df.iloc[:, 1].values:
        return True
    else:
        return False
    
def fetch_duckduckgo_risk_data(company_name, num_results=5):
    """Fetch risk-related data about a company using DuckDuckGo search (avoiding duplicate snippets)."""

    query = f"{company_name} regulatory violations lawsuits fines risks"
    
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
        "q": f"{query} risk score summary OR risk assessment OR financial risks OR regulatory risks OR risk factors site:investing.com OR site:reuters.com OR site:sec.gov OR site:morningstar.com",
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
