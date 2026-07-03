import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing_extensions import TypedDict
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Update the target model parameter here 👇
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2")
CHROMA_PATH = "./chroma_db"

resume_vectorstore = Chroma(collection_name="resume_collection", embedding_function=embeddings, persist_directory=CHROMA_PATH)
github_vectorstore = Chroma(collection_name="github_collection", embedding_function=embeddings, persist_directory=CHROMA_PATH)

class AgentState(TypedDict):
    messages: list
    user_query: str
    next_agent: str
    final_output: str

# Blazing-fast orchestration execution via standard flash tier
llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.1)

def supervisor_router(state: AgentState):
    last_message = state['messages'][-1].content
    system_prompt = (
        "You are an AI routing supervisor. Analyze the user request. "
        "If they ask about background, contact, experience, or hiring, reply exactly with 'resume_agent'. "
        "If they ask about code, GitHub, repositories, or specific tech projects, reply exactly with 'github_agent'. "
        "Do not include any other words or punctuation in your answer."
    )
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=last_message)])
    return {"next_agent": response.content.strip(), "user_query": last_message}

def resume_agent(state: AgentState):
    query = state["user_query"]
    docs = resume_vectorstore.similarity_search(query, k=2)
    context = "\n".join([d.page_content for d in docs])
    system_prompt = f"You are Yiga Junior's Personal Resume Assistant. Professionally answer using this context:\n\n{context}"
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=query)])
    return {"final_output": response.content}

def github_agent(state: AgentState):
    query = state["user_query"]
    docs = github_vectorstore.similarity_search(query, k=2)
    context = "\n".join([d.page_content for d in docs])
    system_prompt = f"You are Yiga Junior's Technical Code Assistant. Deeply explain your repo implementations using this context:\n\n{context}"
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=query)])
    return {"final_output": response.content}

workflow = StateGraph(AgentState)
workflow.add_node("router", supervisor_router)
workflow.add_node("resume_agent", resume_agent)
workflow.add_node("github_agent", github_agent)

workflow.set_entry_point("router")
workflow.add_conditional_edges("router", lambda state: state["next_agent"], {"resume_agent": "resume_agent", "github_agent": "github_agent"})
workflow.add_edge("resume_agent", END)
workflow.add_edge("github_agent", END)
graph = workflow.compile()

class QueryInput(BaseModel):
    text: str

@app.post("/api/chat")
async def chat_endpoint(data: QueryInput):
    result = await graph.ainvoke({"messages": [HumanMessage(content=data.text)]})
    return {"reply": result.get("final_output"), "agent_used": result.get("next_agent")}
