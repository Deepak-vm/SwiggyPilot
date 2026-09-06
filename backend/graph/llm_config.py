import os
from dotenv import load_dotenv
# from langchain_google_genai import ChatGoogleGenerativeAI
# from langchain_ollama import ChatOllama
# pyrefly: ignore [missing-import]
from langchain_groq import ChatGroq

#Ollama (llama3.2:3b) was tested but doesn't support tool-calling reliably enough for MCP ReAct agents. Groq is used instead.
#Gemini was also tested, but some Swiggy MCP schemas are incompatible with Gemini's function-declaration schema requirements.

load_dotenv()

PROVIDER   = "groq"
MODEL_NAME = "openai/gpt-oss-20b"

PROVIDER = "gemini"
MODEL_NAME = "gemini-3-flash-preview"


def get_llm(model: str = MODEL_NAME):
    return ChatGroq(model=model, temperature=0, api_key=os.getenv("GROQ_API_KEY"))
    # return ChatGoogleGenerativeAI(
    #     model=model,
    #     temperature=0,
    #     google_api_key=os.getenv("GEMINI_API_KEY"),
    # )


llm = get_llm()
