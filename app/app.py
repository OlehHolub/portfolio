from flask import Flask, jsonify

app = Flask(__name__)

@app.get("/")
def index():
    return "Flask (pure) behind local Traefik at /app: OK"

@app.get("/health")
def health():
    return jsonify(status="ok"), 200

if __name__ == "__main__":
    # Flask будет доступен на порту 8000
    app.run(host="0.0.0.0", port=8000, debug=False)
