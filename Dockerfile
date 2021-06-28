FROM public.ecr.aws/bitnami/python:3.9

COPY requirements.txt /tmp/
RUN pip install -r /tmp/requirements.txt

COPY tacostats_listener /run/tacostats_listener
COPY ecs.env /run/.env

# Command can be overwritten by providing a different command in the template directly.
WORKDIR /run
CMD ["python", "-m", "tacostats_listener.listener"]
