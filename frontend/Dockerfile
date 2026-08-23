FROM node:22-bookworm-slim AS builder
WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

COPY frontend ./
# Empty is intentional: the client derives the current host at runtime, which
# makes the published image work on a VM without rebuilding it.  Set this build
# argument only when the API is hosted on a different public origin.
ARG NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build && mkdir -p .next dist

FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production

# Keep build tooling and npm's download cache out of the final image.
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/vite.config.ts ./vite.config.ts
COPY --from=builder /app/next.config.ts ./next.config.ts
COPY --from=builder /app/tsconfig.json ./tsconfig.json
COPY --from=builder /app/.openai ./.openai
COPY --from=builder /app/app ./app
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/dist ./dist

EXPOSE 3000
CMD ["npm", "run", "start", "--", "--host", "0.0.0.0"]
