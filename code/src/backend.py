from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain.chat_models import init_chat_model
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from seclookup import (CIKLookup, SECRiskAnalyzer)
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

load_dotenv()

# if not os.environ.get("TOGETHER_API_KEY"):
#     os.environ["TOGETHER_API_KEY"] = os.getenv("TOGETHER_API_KEY")
df=pd.read_csv("/home/nithish/home/applAI/aidel-llmao/code/src/sdn.csv")
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
            """You are a helpful assistant specialized in extracting structured data from transaction records and identifying the nature of entities such as 
            corporations, non-profits, shell companies, and financial intermediaries."""
        )

        # Define the human message with instructions and the expected JSON schema.
        human_message = HumanMessagePromptTemplate.from_template(
            """
            Extract all relevant entities from the following transaction record and output a JSON object with the following format:

            {{
             "Transaction_ID":"Transaction id",
            "sender": {{
                "name": "ENTITY_NAME",
                "location": "ENTITY_LOCATION",
                "country_code": "ISO 3166-1 alpha-2 country code",
                "jurisdiction": "ENTITY_JURISDICTION",
                "identifiers": {{"registration_number": "VALUE", "tax_id": "VALUE"}},
                "additional_details": "Additional sender details"
            }},
            "receiver": {{
                "name": "ENTITY_NAME",
                "location": "ENTITY_LOCATION",
                "country_code": "ISO 3166-1 alpha-2 country code",
                "jurisdiction": "ENTITY_JURISDICTION",
                "identifiers": {{"registration_number": "VALUE", "tax_id": "VALUE"}},
                "additional_details": "Additional receiver details"
            }},
            "intermediaries": [
                {{
                "name": "ENTITY_NAME",
                "country_code": "ISO 3166-1 alpha-2 country code",
                "jurisdiction": "ENTITY_JURISDICTION",
                "role": "Financial intermediary / Shell company",
                "location": "ENTITY_LOCATION"
                }}
            ],
            "beneficiaries": [
                {{
                "name": "ENTITY_NAME",
                "country_code": "ISO 3166-1 alpha-2 country code",
                "jurisdiction": "ENTITY_JURISDICTION",
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
        Transaction_ID = result_json["Transaction_ID"]
        sender_name = result_json.get("sender", {}).get("name", "Unknown")
        receiver_name = result_json.get("receiver", {}).get("name", "Unknown")
        # intermediaries = result_json.get("intermediaries", {}).get("name", "Unknown")
        # beneficiaries = result_json.get("beneficiaries", {}).get("name", "Unknown")
        intermediaries = None
        beneficiaries = None
        
        getllmResponse=getRiskScore(Transaction_ID, sender_name, receiver_name, intermediaries, beneficiaries)
        print("in backend.py - risk json ==>",getllmResponse)
        # print(getllmResponse.type())
        # extract_llmresponse_entities(getllmResponse,result_json)
        
        # print(result_json)
        if "error" in result_json:
            return {"error": result_json["error"]}
        return getllmResponse
    except Exception as e:
        print(str(e))
        # return {"error": f"LLM processing failed: {str(e)}"}

def getSECEdgar_data(entity_name):
    print(entity_name)
    lookup = CIKLookup('cik_mapping.csv')
    lookup_result = lookup.find_cik(entity_name)
    print(lookup_result)
    try:
        with open("companyfacts/"+lookup_result['filename'], 'r') as f:
            entity_data = json.load(f)
        # Analyze risks
        analyzer = SECRiskAnalyzer(entity_data)
        risk_report = analyzer.analyze()
        summary = analyzer.get_risk_summary()

        sec_summary = {
            "entity_name" : entity_name,
            "match_type" : lookup_result["match_type"],
            "confidence_score" : lookup_result["score"],
            "risk_summary" : summary,
            "full analysis from SEC Edgar" : risk_report
        }
        print("sec summary -->", sec_summary)
        return sec_summary
    except Exception as e:
        print(e)
        return "error while sec lookup"


def getRiskScore(Transaction_ID, senderCompany, receiverCompany, intermediaries, beneficiaries):
    #sender
    print(1)
    isSenderSanctioned=fetch_sanctions(senderCompany)
    print(2)
    senderwikipediaData=fetch_duckduckgo_risk_data(senderCompany)
    print(3)
    sendergoogleData=google_search(senderCompany)
    print(4)
    senderSecData = getSECEdgar_data(senderCompany)
    print(5)

    #receiver
    print(1)
    receiverwikipediaData=fetch_duckduckgo_risk_data(receiverCompany)
    print(2)
    receivergoogleData=google_search(receiverCompany)
    print(3)
    isReceiverSanctioned=fetch_sanctions(receiverCompany)
    print(4)
    receiverSecData = getSECEdgar_data(receiverCompany)
    print(5)
    return llmResponseChain(
        Transaction_ID,
        isSenderSanctioned, senderwikipediaData, sendergoogleData, senderSecData, 
        isReceiverSanctioned, receiverwikipediaData, receivergoogleData, receiverSecData,
        senderCompany, receiverCompany, intermediaries, beneficiaries
    )
      
def llmResponseChain(Transaction_ID, 
                     isSenderSanctioned, senderwikipediaData, sendergoogleData, senderSecData,
                     isReceiverSanctioned, receiverwikipediaData, receivergoogleData, receiverSecData,
                     senderCompany, receiverCompany, intermediaries, beneficiaries
                    ):
    url = "https://api.together.xyz/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer API KEY",
        "Content-Type": "application/json"
    }

    # Format the prompt
    system_message = SystemMessage(
        """You are a highly specialized AI designed for **financial, regulatory, and reputational risk assessment**. 
        Your task is to analyze transactions based on **structured entity data** from various sources such as SEC Edgar, OFAC, offshore database leaks, Wikipedia, and Google.

        ### **Behavior Guidelines**
        1. **Risk Analysis**: Perform **deep semantic analysis** of the provided data to detect legal, financial, and reputational risks.
        2. **Implicit Risk Detection**: Identify risks even if explicit terms like *lawsuit, fraud, bankruptcy, sanctions* are absent but implied in the context.
        3. **Risk Score Assignment**: Assign a **quantitative risk score** based on severity, frequency, and impact of identified risks.
        4. **Output Structure**: Ensure the response follows the exact **JSON structure** provided below. No additional text should be included.
        5. **Confidence Score**: Assign a confidence level based on **the amount and quality of supporting data**.
        6. **Evidence-Based Conclusion**: Summarize key findings using **verifiable data** from **Google and Wikipedia** sources.

        ### **Output Format**
        The response must strictly follow this JSON format:
        ```json
        {
            "Transaction ID": "transaction id",
            "Extracted Entity": [<sender>, <receiver>, <intermediaries>, <beneficiaries>],
            "Entity Type": [<sender entity type>, <receiver entity type>, <intermediary type>, <beneficiary type>],
            "Risk Score": assigned risk score,
            "Supporting Evidence": "...",
            "Confidence Score": calculated confidence score,
            "Reason": "Brief reason explaining the risk score"
        }
        <> these are used as placeholder, values enclosed in <> are not exact values. You should find them in the data given to you.
        If you beneficiaries and intermediaries are not mentioned as "None" in the data given to feel free to not include them in "Extracted Entity" and "Entity Type"
        """
    )

    human =HumanMessage(f"""
    ### Combined Company Risk Score Analysis
    **Transaction ID:** {Transaction_ID}
    **Entities Involved**  
        - *Sender:* {senderCompany}  
        - *Receiver:* {receiverCompany}  
        {f'- *Intermediaries:*{intermediaries}' if intermediaries else ''}  
        {f'- *Beneficiaries:* {beneficiaries}' if beneficiaries else ''}

    *Sender:* {senderCompany}  
    *Receiver:* {receiverCompany}  
    #### 🛑 *Sanctions Status*
    - "⚠️ HIGH RISK: if {senderCompany} has {isSenderSanctioned} give HIGH else LOW and if {receiverCompany} has {isReceiverSanctioned} give HIGH else LOW"

    ### SEC Edgar data
    *Sender:* {senderSecData}  
    *Receiver:* {receiverSecData}

    ### *Task*  
    1. *Perform a semantic search* within the provided data to detect regulatory, financial, and reputational risks {receiverwikipediaData and senderwikipediaData and sendergoogleData and receivergoogleData}.  
    2. *Identify implicit risks* even if exact words (lawsuit, fraud, bankruptcy, controversy) are not present but are implied through context.  
    3. *Analyze risk indicators* related to compliance violations, financial instability, and reputational concerns from both sender and receiver perspectives.  
    4. *Assign risk scores* (HIGH, MEDIUM or LOW) based on severity and frequency of identified risks.  
    5. *Provide supporting evidence* by extracting relevant portions of the data that justify the assigned scores.  

    ### *Risk Scoring Breakdown*  
    - *Regulatory or Legal Risks* → Score based on *semantic indications* of lawsuits, investigations, regulatory actions, fines, compliance failures, or SEC-related scrutiny across sender and receiver data.  
    - *Financial Instability * → Score based on *contextual analysis* of financial distress, bankruptcy risks, debt burdens, or cash flow issues in the sender and receiver data.  
    - *Market Reputation Risks* → Score based on *insights from semantic search* regarding past controversies, negative public sentiment, media scrutiny, or brand damage.  

    ### 🏆 *Final Risk Score Calculation*
    - Sanctions Risk: {"50" if isSenderSanctioned and isReceiverSanctioned else "30" if isSenderSanctioned or isReceiverSanctioned else 0}
    - Regulatory Risk: Assign a score based on available data (7->HIGH,3->MEDIUM 1->LOW).
    - Financial Risk: Assign a score based on available data (7->HIGH,3->MEDIUM 1->LOW).
    - Reputation Risk: Assign a score based on available data (7->HIGH,3->MEDIUM 1->LOW).
    the output should have only sender,receiver,risk score and conclusion, don't give risk score breakdown and final risk score calculation details in output
    don't give note in output and don't repeat the data twice

    📌 *Risk Score (out of 100):* Calculate and provide the total score.

   
    *📝 Conclusion:*  
    Generate the conclusion from the available data from google and wikipedia data for both sender and receiver be precise dont mention th percentage in conclusion.  
    Mention Both sender and receiver company details

    ### **📝 Final Output (JSON Format Only)**
    {{
        "Transaction ID": {Transaction_ID},
        "Extracted Entity": ["{senderCompany}", "{receiverCompany}", "{intermediaries}", "{beneficiaries}"],
        "Entity Type": ["senderEntityType", "receiverEntityType", "intermediaryType", "beneficiaryType"],
        "Risk Score": calculated_risk_score,
        "Supporting Evidence": "...",
        "Confidence Score": "confidence_score",
        "Reason": "Summarized risk factors"
    }}
    """)
    # data = {
    #     "model": "meta-llama/Llama-Vision-Free",
    #     "messages": [{"role": "user", "content": prompt}],
    #     "temperature": 0.3
    # }
    # response = requests.post(url, headers=headers, data=json.dumps(data))

    # if response.status_code == 200:
    #     result = response.json()
    # else:
    #     print("Error:", response.text)
    #     return response.text
    # print("llm response")
    # print(result["choices"][0]["message"]["content"])
    # return result["choices"][0]["message"]["content"]
    chat_model = init_chat_model("meta-llama/Llama-Vision-Free", model_provider="together")
    response = chat_model.invoke([system_message, human])
    print("In backend - ",response.content)
    return response.content


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


#give API and CX keys
API_KEY=""""""
CX=""


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
