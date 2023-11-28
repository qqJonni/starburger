FROM python:3.11.4

SHELL ["/bin/bash", "-c"]

# set enviroment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN pip install --upgrade pip

RUN apt update

# Create the admin user and add it to the existing group "burger_django"
RUN groupadd -r burger_django && useradd -rms /bin/bash -g burger_django admin && chmod 777 /opt /run

WORKDIR /starburger

RUN mkdir /starburger/static && mkdir /starburger/media && \
    chown -R admin:burger_django /starburger && \
    chmod 755 /starburger

COPY --chown=admin:burger_django . .

RUN pip install -r requirements.txt

USER admin

CMD ./manage.py migrate
CMD ./manage.py runserver 0.0.0.0:8000

#CMD ["qunicorn", "-b", "0.0.0.0:8001", "star_burger.wsgi:application"]
