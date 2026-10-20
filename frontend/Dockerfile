# Frontend estático (HTML + CSS + JS sin build) servido por nginx.
# nginx también hace de proxy /api/ -> backend, así el navegador habla con un solo origen
# y la misma imagen funciona en local y en EC2 cambiando solo BACKEND_URL.
FROM nginx:1.27-alpine
ENV BACKEND_URL=http://api:8000
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY public /usr/share/nginx/html
EXPOSE 80
