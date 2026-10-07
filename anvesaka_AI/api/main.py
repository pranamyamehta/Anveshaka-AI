"""FastAPI application entry point."""

from fastapi import FastAPI


app = FastAPI(
    title="Anvesaka",
    description="Agentic AI assistant for data center incident triage.",
    version="0.1.0",
)


@app.get("/", tags=["health"])
def root() -> dict[str, str]:
    """Return a short message confirming the API process is running."""
    return {"message": "Anvesaka API is running", "docs": "/docs"}


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Report the API process health."""
    return {"status": "ok"}
