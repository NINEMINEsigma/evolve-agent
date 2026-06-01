if not exist venv (
    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
)
else (
    venv\Scripts\activate
)