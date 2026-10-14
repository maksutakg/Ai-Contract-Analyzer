import uvicorn

from law_rag.config import Settings


if __name__ == "__main__":
    # Bound to localhost: the API has no authentication yet.
    uvicorn.run("law_rag.api:app", host="127.0.0.1", port=Settings().app_port, reload=True)
