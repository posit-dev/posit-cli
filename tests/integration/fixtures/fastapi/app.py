from fastapi import FastAPI


VERSION = "one"

app = FastAPI(title="Posit CLI integration test")


@app.get("/")
def root():
    return {
        "service": "posit-cli-fastapi",
        "version": VERSION,
    }
