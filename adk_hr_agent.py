import os
import asyncio
from google.antigravity import Agent, LocalAgentConfig
from google.cloud import discoveryengine_v1 as discoveryengine
from google.cloud import storage
# ---------------------------------------------------------------------------
# 1. 環境變數
# ---------------------------------------------------------------------------
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "ai-lab-666")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "ai-lab-666-policy-rag-bucket")
DATA_STORE_ID = os.environ.get("DATA_STORE_ID", "employee-policy-datastore_1785427499020")
LOCATION = "global"
# ---------------------------------------------------------------------------
# 2. ADK Custom Tool: Vertex AI Search RAG 檢索工具 (FR-5.1 & FR-5.3)
# ---------------------------------------------------------------------------
def search_policy_rag(query: str) -> str:
    """
    當 OKF 核心矩陣不足以回答，或需要查詢條文全文細節、解釋、範例時呼叫此工具。
    傳回包含原文引用連結與頁碼 metadata 的片段。
    """
    print(f"\n[ADK Tool] 觸發 RAG 全文檢索，查詢: '{query}'...")
    
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
            snippet_text = snippet_obj.get("snippet", "")
            uri = data.get("link", "")
            snippets.append(f"{snippet_text}\n(來源出處: {uri})")
            
    return "\n---\n".join(snippets) if snippets else "RAG 檢索未找到相關細節。"
# ---------------------------------------------------------------------------
# 3. GCS OKF 熱加載邏輯 (FR-5.2 事實接地與零幻覺)
# ---------------------------------------------------------------------------
def load_okf_instructions_from_gcs() -> str:
    if not BUCKET_NAME:
        raise ValueError("未設定 BUCKET_NAME 環境變數")
        
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    combined_okf = ""
    blobs = bucket.list_blobs(prefix="okf_policies/")
    for blob in blobs:
        if blob.name.endswith(".md"):
            filename = os.path.basename(blob.name)
            content = blob.download_as_text()
            combined_okf += f"\n\n--- 【GCS OKF 控制矩陣: {filename}】 ---\n" + content
    return f"""
你是一位專業的 Altostrat HR 與企業合規 AI 助手。
【最高指導原則與 OKF 控制矩陣】：
{combined_okf}
【雙軌決策與 Guardrails 流程】：
1. 涉及金額天花板、報帳門檻、請假時限、核准權限矩陣等「硬性規定」，請**直接參考 OKF 矩陣**回答。
2. 若使用者詢問條文背後的詳細說明、特殊例外狀況、申請範例或微觀步驟，請**調用 `search_policy_rag` 工具**向 Vertex AI Search 查詢手冊原文。
3. 任何情況下都不得違反 OKF 內標註的 ⚠️ Gotcha 或 ❌ 禁止事項。
4. 若資料庫無記載，必須明確說明「政策無相關規定」，嚴禁虛構政策 (0% Hallucination)。
"""
# ---------------------------------------------------------------------------
# 4. ADK Agent 初始化與運行進入點
# ---------------------------------------------------------------------------
def create_hr_agent() -> Agent:
    # 自 GCS 讀取最新 OKF 導引
    system_instruction = load_okf_instructions_from_gcs()
    
    # 配置 ADK LocalAgentConfig
    config = LocalAgentConfig(
        model="gemini-3.6-flash",
        system_instructions=system_instruction,
        tools=[search_policy_rag],
    )
    
    return Agent(config=config)
async def main():
    agent = create_hr_agent()
    async with agent:
        # 測試執行對話
        response = await agent.chat("我下週要請客戶吃飯，預算一個人 600 美金，請問報帳規定是什麼？")
        print("\n[ADK Agent 輸出]:")
        print(response.text)
if __name__ == "__main__":
    asyncio.run(main())
