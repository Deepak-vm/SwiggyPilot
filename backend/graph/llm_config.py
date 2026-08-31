import os
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from langchain_groq import ChatGroq

load_dotenv()

PROVIDER   = "groq"
MODEL_NAME = "openai/gpt-oss-120b"


def get_llm(model: str = MODEL_NAME):    
    return ChatGroq(model=model, temperature=0, api_key=os.getenv("GROQ_API_KEY"))


llm = get_llm()
