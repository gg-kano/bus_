FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir streamlit>=1.32.0 requests>=2.31.0 pandas>=2.0.0

COPY . .

EXPOSE 8502

CMD ["streamlit", "run", "chat.py", \
     "--server.port=8502", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]