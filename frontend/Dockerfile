FROM node:22-bookworm-slim
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build
EXPOSE 3000
CMD ["npm", "run", "start", "--", "--host", "0.0.0.0"]
