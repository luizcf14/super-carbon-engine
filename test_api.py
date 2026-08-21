from agno.models.google import Gemini
import inspect

print("Gemini model class signature:")
print(inspect.signature(Gemini.__init__))

try:
    from agno.knowledge.embedder.google import GeminiEmbedder
    print("\nGeminiEmbedder class signature:")
    print(inspect.signature(GeminiEmbedder.__init__))
except Exception as e:
    print("Error loading GeminiEmbedder:", e)
