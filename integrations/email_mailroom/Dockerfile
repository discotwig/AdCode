FROM python:3.12-slim

WORKDIR /app

# The email mailroom does not need facebook-business or mcp.
COPY integrations/email_mailroom/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080
CMD ["uvicorn", "integrations.email_mailroom.app:app", "--host", "0.0.0.0", "--port", "8080"]
