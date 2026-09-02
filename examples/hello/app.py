from pathlib import Path


message = (Path(__file__).parent / "hello.txt").read_text(encoding="utf-8").strip()
print(message)
