# Frontend image — Next.js standalone build, multi-stage.
#
# Build from the frontend/ directory:
#   docker build -t gcc-jobs-web --build-arg NEXT_PUBLIC_API_URL="" ./frontend
#
# NEXT_PUBLIC_API_URL is baked at BUILD time (Next.js inlines NEXT_PUBLIC_*):
#   ""                      -> same-origin relative URLs (production, behind nginx)
#   "http://localhost:8000" -> direct backend (dev compose without nginx)

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npx next build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN addgroup -S app && adduser -S app -G app
USER app

# Standalone output = minimal server.js + only the node_modules it needs.
# public/ and .next/static aren't included automatically — copy them in.
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -q -O /dev/null http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
