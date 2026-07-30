import os
from google import genai
from google.genai import types
from google.cloud import discoveryengine_v1 as discoveryengine
from google.cloud import storage
# 1. 讀取環境變數
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
BUCKET_NAME = os.environ.get("BUCKET_NAME")
DATA_STORE_ID = os.environ.get("DATA_STORE_ID", "employee-policy-datastore")
LOCATION = "global"
client = genai.Client()
# 2. RAG 工具函數 (Vertex AI Search API)
def search_policy_rag(query: str) -> str:
    """當 OKF 核心矩陣不足以回答，或需要查詢條文全文細節、解釋、範例時呼叫此工具。"""
    print(f"\n[Tool Called] 觸發 RAG 全文檢索，查詢關鍵字: '{query}'...")
    
    search_client = discoveryengine.SearchServiceClient()
    serving_config = search_client.serving_config_path(
        project=PROJECT_ID,
        location=LOCATION,
        data_store=DATA_STORE_ID,
        serving_config="default_config",
    )
    
    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=query,
        page_size=3,
    )
    
    response = search_client.search(request)
    
    snippets = []
    for result in response.results:
        data = result.document.derived_struct_data
        for snippet_obj in data.get("snippets", []):
            snippets.append(snippet_obj.get("snippet", ""))
            
    return "\n---\n".join(snippets) if snippets else "RAG 檢索未找到相關細節。"
# 3. 從 GCS 動態讀取所有的 OKF 檔案內容 (適配 ADK Agent Runtime)
def get_system_instruction_from_gcs() -> str:
    if not BUCKET_NAME:
        raise ValueError("環境變數 BUCKET_NAME 未設定！")
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    combined_okf = ""
    # 列出 GCS 上的 okf_policies/ 目錄下所有 .md 檔案
    blobs = bucket.list_blobs(prefix="okf_policies/")
    for blob in blobs:
        if blob.name.endswith(".md"):
            filename = os.path.basename(blob.name)
            content = blob.download_as_text() # 直接在記憶體中讀取
            combined_okf += f"\n\n--- 【GCS 託管 OKF 檔案: {filename}】 ---\n" + content
    return f"""
你是一位專業的 Altostrat HR 與企業合規問答助手。
【OKF 最高指導原則與控制矩陣】：
{combined_okf}
【雙軌決策流程】：
1. 涉及金額天花板、報帳門檻、請假時限、核准權限矩陣等「硬性規定」，請**直接參考 OKF 矩陣**回答。
2. 若使用者詢問條文背後的詳細說明、特殊例外狀況、申請範例或微觀步驟，請**調用 `search_policy_rag` 工具**向 Vertex AI Search 查詢手冊原文。
3. 任何情況下都不得違反 OKF 內標註的 ⚠️ Gotcha 或 ❌ 禁止事項。
"""
# 4. Agent 問答對話邏輯 (Gemini 3.6 Flash)
def ask_agent(user_query: str):
    print(f"\n==================================================")
    print(f"使用者提問: {user_query}")
    print(f"==================================================")
    # 動態從 GCS 拉取 OKF 上下文
    system_prompt = get_system_instruction_from_gcs()
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=user_query,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[search_policy_rag],
            temperature=0.1,
        )
    )
    
    print("\n[Agent 最終回答]:")
    print(response.text)
if __name__ == "__main__":
    ask_agent("我下週要請客戶吃飯，預算一個人 600 美金，請問報帳規定是什麼？")
    ask_agent("請告訴我 WorkWeek 上申請 Maternity Leave 的兩組官方系統 Code 名稱是什麼？")
