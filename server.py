from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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


class StrainResearchRequest(BaseModel):
    action: Literal["research_strain"] = "research_strain"
    candidate_name: str = Field(min_length=1, max_length=240)
    normalized_name: str | None = Field(default=None, max_length=240)
    review_id: int | None = Field(default=None, ge=1)
    marketplace_mentions: int = Field(default=0, ge=0)
    research_queries: list[str] = Field(default_factory=list)
    requested_by: str = Field(default="system", max_length=240)
    scope: Literal["identity_lineage_flower_chemistry"] = (
        "identity_lineage_flower_chemistry"
    )


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
    version="1.1",
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
# NATURAL-LANGUAGE EXECUTION
# ==========================================================

@app.post("/execute")
async def execute(request: AgentRequest):

    if agent is None:
        raise HTTPException(503, "Brain unavailable")

    result = await agent.run(request.message)

    return result


# ==========================================================
# TYPED GOVERNED STRAIN RESEARCH
# ==========================================================

@app.post("/execute/strain-research")
async def execute_strain_research(request: StrainResearchRequest):
    """Execute the first-class strain-research command without NLP routing."""

    if agent is None:
        raise HTTPException(503, "Brain unavailable")

    payload = (
        request.model_dump()
        if hasattr(request, "model_dump")
        else request.dict()
    )
    result = await agent.run_command(payload)

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
