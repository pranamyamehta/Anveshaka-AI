"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(
    title="Anvesaka",
    description="Agentic AI assistant for data center incident triage.",
    version="0.1.0",
)

# Allow the Next.js dev server (and production build) to call the API.
# Adjust origins as needed for production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["health"])
def root() -> dict[str, str]:
    """Return a short message confirming the API process is running."""
    return {"message": "Anvesaka API is running", "docs": "/docs"}


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Report the API process health."""
    return {"status": "ok"}
