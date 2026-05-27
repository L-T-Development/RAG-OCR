# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

# Copy lock files first for better layer caching
COPY package.json package-lock.json ./

# Install dependencies (clean install from lockfile)
RUN npm ci

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Production stage with nginx
FROM nginx:alpine

# Copy built files from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
