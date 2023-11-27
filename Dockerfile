FROM python:3.11.4

SHELL ["/bin/bash", "-c"]

# set enviroment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN pip install --upgrade pip

RUN apt update

RUN useradd -rms /bin/bash admin && chmod 777 /opt /run

WORKDIR /starburger

RUN mkdir /starburger/static && mkdir /starburger/media && chown -R starburger:starburger /starburger && chmod 755 /starburger

COPY --chown=starburger:starburger . .

RUN pip install -r requirements.txt

USER admin

CMD ["qunicorn", "-b", "0.0.0.0:8001", "star_burger.wsgi:application"]
