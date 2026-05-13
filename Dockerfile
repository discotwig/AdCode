FROM python:3.12-slim
WORKDIR /app
# Use requirements-email.txt — the email bot (mailroom) does not need
# the facebook-business SDK or mcp package. Engine runs locally.
COPY requirements-email.txt .
RUN pip install --no-cache-dir -r requirements-email.txt
COPY . .
# Keep a copy of customer configs outside the volume mount so entrypoint can sync them
RUN cp -r /app/customers /app/customers_defaults
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 8080
CMD ["/entrypoint.sh"]
