import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

# NOTE: Ollama (llama3.2:3b) was tested but doesn't support tool-calling reliably
#       enough for MCP ReAct agents.
# NOTE: Gemini was also tested, but some Swiggy MCP tool schemas use JSON Schema
#       features (additionalProperties, nested anyOf/oneOf) that Gemini's
#       function-declaration validator rejects at tool-binding time.
# Both alternatives are left commented-out below for reference.
# from langchain_google_genai import ChatGoogleGenerativeAI
# from langchain_ollama import ChatOllama

load_dotenv()

PROVIDER   = "groq"
MODEL_NAME = os.getenv("ROUTER_MODEL", "openai/gpt-oss-20b")


def get_llm(model: str = MODEL_NAME) -> ChatGroq:
    """Return a Groq LLM instance. Pass ``model`` to override the default."""
    return ChatGroq(model=model, temperature=0, api_key=os.getenv("GROQ_API_KEY"))
    # Uncomment to switch to Gemini (requires schema-compatible Swiggy MCP):
    # return ChatGoogleGenerativeAI(
    #     model=model, temperature=0, google_api_key=os.getenv("GEMINI_API_KEY")
    # )
    # Uncomment to switch to Ollama (local):
    # return ChatOllama(model=model, temperature=0)


llm = get_llm()
