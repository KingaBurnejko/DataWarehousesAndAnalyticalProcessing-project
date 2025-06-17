FROM python:3.11-slim

WORKDIR /app

COPY import_to_questdb.py .

RUN pip install psycopg2-binary pandas


CMD ["python", "import_to_questdb.py"]
