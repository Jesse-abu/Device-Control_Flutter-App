import os, json, lancedb
from langchain_community.vectorstores import LanceDB
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document

#path to LanceDB directory
DB_PATH = "./lancedb_data"

def initialize_lancedb_index(trace_file="workflow_traces.jsonl"):
    """Reads JSONL logs from Phase 4, converts them to documents, and stores in LanceDB."""
    if not os.path.exists(trace_file):
        print(f"No trace file found at '{trace_file}'. Run Phase 4 first.")
        return None

    documents = []
    with open(trace_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            trace = json.loads(line)
            
            #compose readable text representation for vector indexing
            text_content = (
                f"Application: {trace.get('app_name')}\n"
                f"Window Title: {trace.get('window_title')}\n"
                f"Screen OCR Summary: {trace.get('screen_ocr_summary')}\n"
                f"Recorded Actions: {json.dumps(trace.get('recent_actions'))}"
            )
            
            doc = Document(
                page_content=text_content,
                metadata={
                    "app_name": trace.get("app_name", ""),
                    "timestamp": trace.get("timestamp", ""),
                    "actions_count": trace.get("actions_count", 0)
                }
            )
            documents.append(doc)

    if not documents:
        print("No trace documents found to index.")
        return None

    #load local open-source embedding model
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    #initialize LanceDB connection
    db = lancedb.connect(DB_PATH)
    table = db.create_table("workflow_traces", data=[{"vector": [0.0]*384, "text": "init", "id": "0"}], mode="overwrite")
    
    #create vector store
    vector_store = LanceDB.from_documents(documents, embeddings, connection=db, table_name="workflow_traces")
    print(f" Successfully indexed {len(documents)} trace frames into LanceDB!")
    return vector_store

def query_similar_workflows(query_text: str, k=3):
    """Retrieves top-k similar workflow traces for an intent query."""
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    db = lancedb.connect(DB_PATH)
    vector_store = LanceDB(connection=db, embedding=embeddings, table_name="workflow_traces")
    
    docs = vector_store.similarity_search(query_text, k=k)
    return docs

if __name__ == "__main__":
    initialize_lancedb_index()