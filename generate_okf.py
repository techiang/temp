import os
import json
from pathlib import Path
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from google.cloud import storage
# 1. Pydantic Schema (模型動態決定檔案數量與檔名)
class OKFFile(BaseModel):
    filename: str = Field(
        description="Markdown 檔名，模型應自主命名（例如 index.md, leave_rules.md, travel_rules.md 等）"
    )
    content: str = Field(
        description="Markdown 內容，包含標題、表格、硬性數字天花板、審核權限矩陣與禁忌"
    )
class OKFPackage(BaseModel):
    files: list[OKFFile] = Field(description="模型自主評估後決定的 OKF 檔案列表")
# 2. 同步上傳至 Cloud Storage (專為 ADK Runtime 設計)
def upload_to_gcs(local_dir: str, bucket_name: str, gcs_prefix: str = "okf_policies"):
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    print(f"\n[GCS Sync] 同步 OKF 檔案至 Cloud Storage: gs://{bucket_name}/{gcs_prefix}/...")
    for filepath in Path(local_dir).glob("*.md"):
        blob_path = f"{gcs_prefix}/{filepath.name}"
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(str(filepath))
        print(f"  [GCS 上傳成功] gs://{bucket_name}/{blob_path}")
# 3. 核心生成與同步邏輯
def generate_and_sync_okf(pdf_path: str, output_dir: str = "okf_policies"):
    client = genai.Client()
    bucket_name = os.environ.get("BUCKET_NAME")
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"找不到指定的 PDF 檔案: {pdf_path}")
    if not bucket_name:
        raise ValueError("環境變數 BUCKET_NAME 未設定！")
    print(f"[Step 1] 上傳 PDF 檔案 [{pdf_path}] 到 Gemini API...")
    uploaded_file = client.files.upload(file=pdf_path)
    prompt = """
    你是一位極度嚴謹的企業知識庫架構師。
    請深入分析這份 PDF 文件，並【自主判斷與決定最適合的 OKF (Open Knowledge Format) 檔案數量與切分架構】。
    【核心目標】：
    為 AI Agent 提取最核心、絕不能算錯或遺漏的控制規則（如「硬性數字天花板」、「審核權限矩陣」、「時間限制 Deadlines」與「嚴格禁止事項 Gotchas」）。
    【檔案切分原則】：
    1. 自行決定要切分成幾個 Markdown 檔案（不要勉強合在同一個檔，也不要過度細碎）。
    2. 第一個檔案必須固定命名為 `index.md`，作為總目錄與路由原則說明。
    3. 其他檔案請依據主題給予清晰代表性的英文檔名。
    """
    print("[Step 2] 呼叫 Gemini 3.6 Flash 生成 OKF 結構...")
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=[uploaded_file, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=OKFPackage,
            temperature=0.1,
        )
    )
    print("[Step 3] 寫入本地臨時目錄...")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    okf_package = OKFPackage.model_validate_json(response.text)
    print(f"💡 Gemini 3.6 Flash 自主決定產出 {len(okf_package.files)} 個 OKF 檔案：")
    for okf_file in okf_package.files:
        file_full_path = output_path / okf_file.filename
        with open(file_full_path, "w", encoding="utf-8") as f:
            f.write(okf_file.content)
        print(f"  [本地生成成功] {file_full_path}")
    # [Step 4] 上傳至 Cloud Storage
    upload_to_gcs(output_dir, bucket_name)
if __name__ == "__main__":
    generate_and_sync_okf("Altostrat_Employee_Policy.pdf")
