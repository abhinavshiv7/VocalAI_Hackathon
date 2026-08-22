FROM node:22-bookworm-slim
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build
EXPOSE 3000
CMD ["npm", "run", "start", "--", "--host", "0.0.0.0"]
