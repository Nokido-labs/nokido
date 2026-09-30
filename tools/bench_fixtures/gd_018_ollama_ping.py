import urllib.request

r = urllib.request.urlopen("http://127.0.0.1:11434", timeout=5)
print("ollama:", r.status)
