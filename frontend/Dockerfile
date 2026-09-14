# ── Stage 1: install dependencies ─────────────────────────────────────────────
FROM node:20-alpine AS deps

# Check https://github.com/nodejs/docker-node/tree/b4117f9333da4138b03a546ec926ef50a31506c3#nodealpine
RUN apk add --no-cache libc6-compat

WORKDIR /app

# Copy lockfile + manifests only — cache this layer
COPY package.json package-lock.json* ./

# ci install respects lockfile exactly; --prefer-offline uses npm cache
RUN npm ci --prefer-offline

# ── Stage 2: build the application ────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Pull installed node_modules from deps stage
COPY --from=deps /app/node_modules ./node_modules

# Copy the full source (respects .dockerignore)
COPY . .

# Disable Next.js telemetry during build
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

# Build — output is standalone (set in next.config.mjs: output: 'standalone')
RUN npm run build

# ── Stage 3: lean production runtime ──────────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser  --system --uid 1001 nextjs

# Static assets from build
COPY --from=builder /app/public ./public

# standalone output: self-contained server.js + minimal node_modules
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static   ./.next/static

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD wget -qO- http://localhost:3000/api/health 2>/dev/null || exit 1

CMD ["node", "server.js"]
