import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.backend.app.main:app",
        host="127.0.0.1",
        port=8001,
        reload=False,
        reload_dirs=["src"]
    )