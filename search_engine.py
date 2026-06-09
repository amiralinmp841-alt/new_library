import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

class BotSearchEngine:
    def __init__(self):
        # مدل بسیار سبک که روی رم کم Render خوب کار میکند
        self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        self.index = None
        self.node_map = [] # لیست نودها که با ایندکس بردارها مچ است

    def flatten_db(self, db):
        """دیتابیس درختی را تبدیل به لیستی از نام مسیرها می‌کند"""
        flattened = []
        
        def traverse(node_id, current_path):
            node = db.get(node_id)
            if not node: return
            
            # نام نود فعلی به مسیر اضافه می‌شود
            new_path = f"{current_path} {node['name']}"
            flattened.append({"path": new_path, "id": node_id})
            
            for child_id in node.get("children", []):
                traverse(child_id, new_path)
        
        traverse("root", "")
        return flattened

    def build_index(self, db):
        items = self.flatten_db(db)
        self.node_map = [item["id"] for item in items]
        paths = [item["path"] for item in items]
        
        embeddings = self.model.encode(paths, convert_to_numpy=True)
        dimension = embeddings.shape[1]
        
        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(embeddings)
        print(f"✅ Search index built with {len(items)} nodes.")

    def search(self, query, top_k=3):
        if not self.index: return []
        
        query_vec = self.model.encode([query], convert_to_numpy=True)
        distances, indices = self.index.search(query_vec, top_k)
        
        results = []
        for idx in indices[0]:
            if idx != -1:
                results.append(self.node_map[idx])
        return results
