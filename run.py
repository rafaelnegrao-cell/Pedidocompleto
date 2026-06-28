import os
from app import create_app

# Objeto de aplicação a nível de módulo — usado pelo gunicorn no Railway:
#   gunicorn run:app
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
