import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

class SemanticSearch:

    def __init__(self):
        self.model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        self.index = None
        self.texts = []

    def build_index(self, text_list):
        self.texts = text_list

        embeddings = self.model.encode(text_list, convert_to_numpy=True)

        dimension = embeddings.shape[1]
        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(embeddings)

    def search(self, query, top_k=3):
        query_vector = self.model.encode([query], convert_to_numpy=True)
        distances, indices = self.index.search(query_vector, top_k)

        results = []
        for idx in indices[0]:
            results.append(self.texts[idx])

        return results
