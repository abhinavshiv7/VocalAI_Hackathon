FROM node:22-alpine
WORKDIR /app
COPY fake-target/package*.json ./
RUN npm ci --omit=dev
COPY fake-target/server.js ./server.js
USER node
EXPOSE 3000
CMD ["npm", "start"]
