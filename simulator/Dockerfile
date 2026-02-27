FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

RUN mkdir -p /app/data

ENV SIM_HOST=0.0.0.0
ENV SIM_PORT=8079
ENV SIM_DB_PATH=/app/data/simulator.db
ENV SIM_TEMPLATES_DIR=/app/src/helpdesk_sim/templates

EXPOSE 8079

CMD ["uvicorn", "helpdesk_sim.main:app", "--host", "0.0.0.0", "--port", "8079"]
