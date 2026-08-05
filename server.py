from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent import KushwellAgent


# ==========================================================
# GLOBAL AGENT
# ==========================================================

agent: KushwellAgent | None = None


# ==========================================================
# REQUEST MODELS
# ==========================================================

class AgentRequest(BaseModel):
    message: str


# ==========================================================
# FASTAPI LIFECYCLE
# ==========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent

    print("\n🚀 Starting Kushwell Brain...")

    agent = KushwellAgent()
    await agent.start()

    print("✅ Brain Ready")

    yield

    print("\n🛑 Shutting down Brain...")

    try:
        await agent.mcp.stop()
    except Exception:
        pass


app = FastAPI(
    title="Kushwell Brain",
    version="1.0",
    lifespan=lifespan,
)


# ==========================================================
# HEALTH
# ==========================================================

@app.get("/health")
async def health():

    return {
        "status": "ok",
        "brain": "online"
    }


# ==========================================================
# STATUS
# ==========================================================

@app.get("/status")
async def status():

    if agent is None:
        raise HTTPException(503, "Brain not started")

    return {
        "status": "running",
        "memory_entries": len(agent.memory.get_all())
    }


# ==========================================================
# EXECUTE
# ==========================================================

@app.post("/execute")
async def execute(request: AgentRequest):

    if agent is None:
        raise HTTPException(503, "Brain unavailable")

    result = await agent.run(request.message)

    return result


# ==========================================================
# MEMORY
# ==========================================================

@app.get("/memory")
async def memory():

    if agent is None:
        raise HTTPException(503, "Brain unavailable")

    return {
        "memory": agent.memory.get_all()
    }


# ==========================================================
# CLEAR MEMORY
# ==========================================================

@app.delete("/memory")
async def clear_memory():

    if agent is None:
        raise HTTPException(503, "Brain unavailable")

    agent.memory.clear()

    return {
        "status": "cleared"
    }


# ==========================================================
# LAST TRACE
# ==========================================================

@app.get("/memory/last")
async def last_memory():

    if agent is None:
        raise HTTPException(503, "Brain unavailable")

    return {
        "memory": agent.memory.last(20)
    }   